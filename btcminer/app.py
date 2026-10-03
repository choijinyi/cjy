"""채굴기 본체: 워커 프로세스, 풀 연결, 통계를 하나로 묶는다."""

import collections
import logging
import multiprocessing as mp
import threading
import time

from . import __version__
from .core import (bits_to_target, difficulty_to_target, format_duration, format_hashrate,
                   target_to_difficulty)
from .stratum import StratumClient
from .worker import mine

log = logging.getLogger("miner")


class Miner:
    def __init__(self, host, port, username, password="x", threads=None):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.threads = threads or max(1, mp.cpu_count() - 1)

        self.difficulty = 1.0
        self.current_job = None
        self.client = None
        self.connected = False
        self.started_at = time.time()

        self.stats = {"accepted": 0, "rejected": 0, "blocks": 0, "best_share": 0.0}
        self.recent_shares = collections.deque(maxlen=20)
        self.log_lines = collections.deque(maxlen=200)
        self._rate_samples = collections.deque(maxlen=30)
        self._lock = threading.Lock()

        self._stop = mp.Event()
        self._hash_counter = mp.Value("Q", 0)
        self._result_queue = mp.Queue()
        self._job_queues = []
        self._procs = []

    # --- 워커 관리 --------------------------------------------------------
    def start_workers(self):
        for i in range(self.threads):
            q = mp.Queue()
            p = mp.Process(target=mine, name=f"worker-{i}", daemon=True,
                           args=(i, self.threads, q, self._result_queue,
                                 self._hash_counter, self._stop))
            p.start()
            self._job_queues.append(q)
            self._procs.append(p)
        log.info("채굴 워커 %d개 시작", self.threads)

    def broadcast(self, job):
        for q in self._job_queues:
            q.put(job)

    def shutdown(self):
        self._stop.set()
        for q in self._job_queues:
            try:
                q.put_nowait(None)
            except Exception:
                pass
        for p in self._procs:
            p.join(timeout=2)
            if p.is_alive():
                p.terminate()
        if self.client:
            self.client.close()

    # --- 풀 이벤트 처리 ---------------------------------------------------
    def _on_job(self, params):
        job_id, prevhash, coinb1, coinb2, branches, version, nbits, ntime, clean = params[:9]
        job = {
            "job_id": job_id,
            "prevhash": prevhash,
            "coinb1": coinb1,
            "coinb2": coinb2,
            "extranonce1": self.client.extranonce1,
            "extranonce2_size": self.client.extranonce2_size,
            "merkle_branch": [bytes.fromhex(b) for b in branches],
            "version": version,
            "nbits": nbits,
            "ntime": ntime,
            "share_target": difficulty_to_target(self.difficulty),
            "block_target": bits_to_target(nbits),
            "clean": bool(clean),
        }
        self.current_job = job
        self.broadcast(job)
        log.debug("새 작업 %s (clean=%s)", job_id, clean)

    def _on_difficulty(self, difficulty):
        self.difficulty = difficulty
        log.info("share 난이도 설정: %s", difficulty)
        if self.current_job:
            job = dict(self.current_job, share_target=difficulty_to_target(difficulty), clean=False)
            self.current_job = job
            self.broadcast(job)

    def _on_submit_result(self, accepted, error, share):
        with self._lock:
            self.stats["accepted" if accepted else "rejected"] += 1
        if share:
            share["status"] = "accepted" if accepted else f"rejected {error}"
        if accepted:
            log.info("share 승인 (난이도 %.4g)", share["difficulty"] if share else 0)
        else:
            log.warning("share 거절: %s", error)

    def _result_loop(self):
        while not self._stop.is_set():
            try:
                share = self._result_queue.get(timeout=0.5)
            except Exception:
                continue
            share_diff = target_to_difficulty(int(share["hash"], 16))
            share["difficulty"] = share_diff
            share["time"] = time.strftime("%H:%M:%S")
            share["status"] = "submitted"
            with self._lock:
                self.stats["best_share"] = max(self.stats["best_share"], share_diff)
                self.recent_shares.appendleft(share)
                if share["is_block"]:
                    self.stats["blocks"] += 1
            if share["is_block"]:
                log.warning("*** 블록 발견! hash=%s ***", share["hash"])
            client = self.client
            if client and self.connected:
                try:
                    client.submit(share["job_id"], share["extranonce2"], share["ntime"],
                                  format(share["nonce"], "08x"), share)
                except OSError as e:
                    log.error("share 제출 실패: %s", e)

    def _rate_loop(self):
        while not self._stop.is_set():
            with self._hash_counter.get_lock():
                total = self._hash_counter.value
            self._rate_samples.append((time.time(), total))
            time.sleep(1)

    # --- 실행 -------------------------------------------------------------
    def run(self):
        self.start_workers()
        threading.Thread(target=self._result_loop, daemon=True).start()
        threading.Thread(target=self._rate_loop, daemon=True).start()
        threading.Thread(target=self._report_loop, daemon=True).start()

        backoff = 5
        while not self._stop.is_set():
            self.client = StratumClient(self.host, self.port, self.username, self.password,
                                        agent=f"cjy-btcminer/{__version__}",
                                        on_job=self._on_job, on_difficulty=self._on_difficulty,
                                        on_submit_result=self._on_submit_result)
            try:
                self.client.connect()
                self.connected = True
                backoff = 5
                self.client.loop()
            except Exception as e:
                if self._stop.is_set():
                    break
                log.error("연결 문제: %s", e)
            finally:
                self.connected = False
                if self.client.reconnect_target:
                    self.host, self.port = self.client.reconnect_target
                    backoff = 1
                self.client.close()
            if self._stop.wait(backoff):
                break
            log.info("%d초 후 재접속 시도...", backoff)
            backoff = min(backoff * 2, 120)

    # --- 통계 -------------------------------------------------------------
    def hashrate(self):
        if len(self._rate_samples) < 2:
            return 0.0
        (t0, h0), (t1, h1) = self._rate_samples[0], self._rate_samples[-1]
        return (h1 - h0) / (t1 - t0) if t1 > t0 else 0.0

    def status(self):
        rate = self.hashrate()
        job = self.current_job
        net_diff = target_to_difficulty(job["block_target"]) if job else 0
        # 블록 하나를 찾는 데 필요한 평균 해시 수 = 네트워크 난이도 × 2^32
        expected = (net_diff * 2 ** 32 / rate) if rate and net_diff else float("inf")
        with self._lock:
            stats = dict(self.stats)
            shares = list(self.recent_shares)
        with self._hash_counter.get_lock():
            total_hashes = self._hash_counter.value
        return {
            "version": __version__,
            "pool": f"{self.host}:{self.port}",
            "user": self.username,
            "connected": self.connected,
            "threads": self.threads,
            "uptime": int(time.time() - self.started_at),
            "hashrate": rate,
            "hashrate_text": format_hashrate(rate),
            "total_hashes": total_hashes,
            "share_difficulty": self.difficulty,
            "network_difficulty": net_diff,
            "expected_block_time": format_duration(expected),
            "job_id": job["job_id"] if job else None,
            **stats,
            "recent_shares": [{k: s[k] for k in ("time", "difficulty", "status", "hash", "is_block")}
                              for s in shares],
            "log": list(self.log_lines)[-50:],
        }

    def _report_loop(self):
        while not self._stop.wait(30):
            s = self.status()
            log.info("해시레이트 %s | 승인 %d / 거절 %d | 최고 share %.4g | 연결=%s",
                     s["hashrate_text"], s["accepted"], s["rejected"], s["best_share"],
                     "예" if s["connected"] else "아니오")


class DequeLogHandler(logging.Handler):
    def __init__(self, target):
        super().__init__()
        self.target = target

    def emit(self, record):
        self.target.append(self.format(record))

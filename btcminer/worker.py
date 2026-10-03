"""채굴 워커 프로세스. CPU 코어마다 하나씩 실행되어 nonce 공간을 탐색한다."""

import hashlib
import queue
import signal
import struct
import time

from .core import build_coinbase, build_header_prefix, build_merkle_root

BATCH_SIZE = 32_768
NONCE_LIMIT = 2 ** 32


def _extranonce2(counter: int, size: int) -> str:
    return (counter % (256 ** size)).to_bytes(size, "big").hex()


def mine(worker_id: int, worker_count: int, job_queue, result_queue, hash_counter, stop_event):
    """Job을 받아 채굴하고, 타깃을 만족하는 share를 result_queue로 보낸다.

    워커끼리 작업이 겹치지 않도록 extranonce2를 worker_id부터 worker_count 간격으로 쓴다.
    """
    # Ctrl+C는 본체 프로세스가 받아서 정리한다. 워커는 stop_event로만 멈춘다.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, signal.SIG_DFL)

    sha256 = hashlib.sha256
    pack_nonce = struct.Struct("<I").pack
    job = None
    en2_counter = worker_id
    nonce = 0
    prefix = midstate = tail = None

    while not stop_event.is_set():
        try:
            new_job = job_queue.get(timeout=0.5) if job is None else job_queue.get_nowait()
            if new_job is None:
                return
            restart = job is None or new_job["clean"] or new_job["job_id"] != job["job_id"]
            job = new_job
            if restart:
                en2_counter = worker_id
                nonce = 0
                prefix = None
        except queue.Empty:
            pass

        if job is None:
            continue

        if prefix is None:
            en2 = _extranonce2(en2_counter, job["extranonce2_size"])
            coinbase = build_coinbase(job["coinb1"], job["extranonce1"], en2, job["coinb2"])
            merkle_root = build_merkle_root(coinbase, job["merkle_branch"])
            prefix = build_header_prefix(job["version"], job["prevhash"], merkle_root,
                                         job["ntime"], job["nbits"])
            midstate = sha256(prefix[:64])  # 앞 64바이트는 nonce와 무관하므로 한 번만 계산
            tail = prefix[64:]

        share_target = job["share_target"]
        block_target = job["block_target"]
        end = min(nonce + BATCH_SIZE, NONCE_LIMIT)

        for n in range(nonce, end):
            h = midstate.copy()
            h.update(tail + pack_nonce(n))
            digest = sha256(h.digest()).digest()
            if digest[31] == 0 or share_target > 2 ** 248:
                value = int.from_bytes(digest, "little")
                if value <= share_target:
                    result_queue.put({
                        "job_id": job["job_id"],
                        "extranonce2": en2,
                        "ntime": job["ntime"],
                        "nonce": n,
                        "hash": digest[::-1].hex(),
                        "is_block": value <= block_target,
                        "worker": worker_id,
                    })

        with hash_counter.get_lock():
            hash_counter.value += end - nonce
        nonce = end

        if nonce >= NONCE_LIMIT:
            # nonce 공간을 다 썼으면 extranonce2를 바꿔 새로운 헤더로 계속한다
            en2_counter += worker_count
            nonce = 0
            prefix = None


def benchmark_job(extranonce2_size: int = 4) -> dict:
    """실제 풀 없이 해시 속도를 측정하기 위한 가짜 job (절대 share가 나오지 않는 타깃)."""
    return {
        "job_id": "benchmark",
        "prevhash": "00" * 32,
        "coinb1": "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff",
        "coinb2": "ffffffff0100f2052a010000000000000000",
        "extranonce1": "00000000",
        "extranonce2_size": extranonce2_size,
        "merkle_branch": [],
        "version": "20000000",
        "nbits": "1703a30c",
        "ntime": format(int(time.time()), "08x"),
        "share_target": 0,
        "block_target": 0,
        "clean": True,
    }

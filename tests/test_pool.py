"""가짜 Stratum 풀을 띄워 접속 → 작업 수신 → share 제출 → 검증까지 전 과정을 시험한다."""

import hashlib
import json
import socket
import struct
import threading
import time
import unittest

from btcminer.app import Miner

EXTRANONCE1 = "f000000d"
DIFFICULTY = 1 / 4096  # 약 2^20 해시당 share 1개 → 수 초 안에 나온다
DIFF1 = 0xFFFF * 2 ** 208


def dsha(b):
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


class FakePool:
    """채굴기 코드와 독립적으로 share를 검증하는 최소 Stratum 서버."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.job = {
            "id": "job1",
            "prevhash": "".join(f"{i:02x}" for i in range(32)),
            "coinb1": "01000000010000000000000000000000000000000000000000000000000000000000000000ffffffff20",
            "coinb2": "ffffffff0100f2052a010000001976a914000000000000000000000000000000000000000088ac00000000",
            "branch": [hashlib.sha256(b"tx").hexdigest()],
            "version": "20000000",
            "nbits": "1703a30c",
            "ntime": "65000000",
        }
        self.valid = []
        self.invalid = []
        threading.Thread(target=self.serve, daemon=True).start()

    def check(self, params):
        user, job_id, en2, ntime, nonce = params
        j = self.job
        cb = bytes.fromhex(j["coinb1"] + EXTRANONCE1 + en2 + j["coinb2"])
        root = dsha(cb)
        for br in j["branch"]:
            root = dsha(root + bytes.fromhex(br))
        prev = bytes.fromhex(j["prevhash"])
        prev = b"".join(prev[i:i + 4][::-1] for i in range(0, 32, 4))
        header = (bytes.fromhex(j["version"])[::-1] + prev + root + bytes.fromhex(ntime)[::-1]
                  + bytes.fromhex(j["nbits"])[::-1] + struct.pack("<I", int(nonce, 16)))
        return int.from_bytes(dsha(header), "little") <= int(DIFF1 / DIFFICULTY)

    def serve(self):
        conn, _ = self.sock.accept()
        f = conn.makefile("r")
        send = lambda obj: conn.sendall((json.dumps(obj) + "\n").encode())
        for line in f:
            msg = json.loads(line)
            if msg["method"] == "mining.subscribe":
                send({"id": msg["id"], "result": [[["mining.notify", "x"]], EXTRANONCE1, 4], "error": None})
            elif msg["method"] == "mining.authorize":
                send({"id": msg["id"], "result": True, "error": None})
                send({"id": None, "method": "mining.set_difficulty", "params": [DIFFICULTY]})
                j = self.job
                send({"id": None, "method": "mining.notify",
                      "params": [j["id"], j["prevhash"], j["coinb1"], j["coinb2"], j["branch"],
                                 j["version"], j["nbits"], j["ntime"], True]})
            elif msg["method"] == "mining.submit":
                ok = self.check(msg["params"])
                (self.valid if ok else self.invalid).append(msg["params"])
                send({"id": msg["id"], "result": ok, "error": None if ok else [23, "Low difficulty", None]})


class PoolTest(unittest.TestCase):
    def test_end_to_end_mining(self):
        pool = FakePool()
        miner = Miner("127.0.0.1", pool.port, "bc1qtest.worker", threads=2)
        threading.Thread(target=miner.run, daemon=True).start()
        try:
            deadline = time.time() + 60
            while time.time() < deadline and miner.stats["accepted"] < 3:
                time.sleep(0.2)
            status = miner.status()
        finally:
            miner.shutdown()
        self.assertGreaterEqual(len(pool.valid), 3, f"유효 share 부족: {status}")
        self.assertEqual(pool.invalid, [])
        self.assertEqual(status["rejected"], 0)
        self.assertGreaterEqual(status["accepted"], 3)
        # 제출된 share는 모두 설정한 사용자 이름으로 나가야 한다
        self.assertTrue(all(p[0] == "bc1qtest.worker" for p in pool.valid))


if __name__ == "__main__":
    unittest.main()

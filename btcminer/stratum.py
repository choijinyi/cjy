"""Stratum v1 프로토콜 클라이언트 (채굴 풀과의 통신)."""

import json
import logging
import socket
import threading

log = logging.getLogger("stratum")


class StratumError(Exception):
    pass


class StratumClient:
    """풀에 접속해 subscribe/authorize를 수행하고, 알림을 콜백으로 전달한다."""

    def __init__(self, host, port, username, password="x", agent="cjy-btcminer/1.0",
                 on_job=None, on_difficulty=None, on_submit_result=None, timeout=300):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.agent = agent
        self.on_job = on_job
        self.on_difficulty = on_difficulty
        self.on_submit_result = on_submit_result
        self.timeout = timeout

        self.extranonce1 = None
        self.extranonce2_size = None
        self.reconnect_target = None
        self._sock = None
        self._file = None
        self._send_lock = threading.Lock()
        self._next_id = 1
        self._pending = {}  # id -> (method, extra)

    # --- 연결 -------------------------------------------------------------
    def connect(self):
        log.info("풀에 접속 중: %s:%s", self.host, self.port)
        self._sock = socket.create_connection((self.host, self.port), timeout=30)
        self._sock.settimeout(self.timeout)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self._file = self._sock.makefile("r", encoding="utf-8", newline="\n")

        result = self._call_blocking("mining.subscribe", [self.agent])
        if not isinstance(result, list) or len(result) < 3:
            raise StratumError(f"subscribe 응답이 올바르지 않습니다: {result!r}")
        self.extranonce1 = result[1]
        self.extranonce2_size = int(result[2])
        log.info("subscribe 완료 (extranonce1=%s, extranonce2_size=%d)",
                 self.extranonce1, self.extranonce2_size)

        if not self._call_blocking("mining.authorize", [self.username, self.password]):
            raise StratumError("인증 실패: 사용자 이름(비트코인 주소)을 확인하세요.")
        log.info("인증 완료: %s", self.username)

    def close(self):
        # 다른 스레드가 readline()에서 대기 중일 수 있으므로 소켓을 먼저 shutdown해 깨운다.
        # (파일 객체를 바로 close하면 읽기 잠금 때문에 멈춘다)
        sock = self._sock
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    # --- 송수신 -----------------------------------------------------------
    def _send(self, method, params, extra=None):
        with self._send_lock:
            msg_id = self._next_id
            self._next_id += 1
            self._pending[msg_id] = (method, extra)
            line = json.dumps({"id": msg_id, "method": method, "params": params}) + "\n"
            self._sock.sendall(line.encode())
        return msg_id

    def _read_message(self):
        line = self._file.readline()
        if not line:
            raise ConnectionError("풀이 연결을 끊었습니다.")
        return json.loads(line)

    def _call_blocking(self, method, params):
        """핸드셰이크용: 응답이 올 때까지 기다리되, 그 사이 오는 알림도 처리한다."""
        msg_id = self._send(method, params)
        while True:
            msg = self._read_message()
            if msg.get("id") == msg_id and "method" not in msg:
                self._pending.pop(msg_id, None)
                if msg.get("error"):
                    raise StratumError(f"{method} 오류: {msg['error']}")
                return msg.get("result")
            self._dispatch(msg)

    def submit(self, job_id, extranonce2, ntime, nonce_hex, share_info=None):
        params = [self.username, job_id, extranonce2, ntime, nonce_hex]
        return self._send("mining.submit", params, extra=share_info)

    def loop(self):
        """연결이 끊길 때까지 메시지를 읽어 처리한다."""
        while True:
            self._dispatch(self._read_message())

    def _dispatch(self, msg):
        method = msg.get("method")
        params = msg.get("params") or []

        if method == "mining.notify":
            if self.on_job:
                self.on_job(params)
        elif method == "mining.set_difficulty":
            if self.on_difficulty:
                self.on_difficulty(float(params[0]))
        elif method == "mining.set_extranonce":
            self.extranonce1 = params[0]
            self.extranonce2_size = int(params[1])
            log.info("extranonce 변경: %s / %d", self.extranonce1, self.extranonce2_size)
        elif method == "client.reconnect":
            host = params[0] if len(params) > 0 and params[0] else self.host
            port = int(params[1]) if len(params) > 1 and params[1] else self.port
            self.reconnect_target = (host, port)
            raise ConnectionError(f"풀이 재접속을 요청했습니다: {host}:{port}")
        elif method == "client.show_message":
            log.info("풀 메시지: %s", params[0] if params else "")
        elif method == "client.get_version":
            with self._send_lock:
                self._sock.sendall((json.dumps({"id": msg.get("id"), "result": self.agent,
                                                "error": None}) + "\n").encode())
        elif method is None and "id" in msg:
            pending = self._pending.pop(msg["id"], None)
            if pending and pending[0] == "mining.submit" and self.on_submit_result:
                accepted = bool(msg.get("result")) and not msg.get("error")
                self.on_submit_result(accepted, msg.get("error"), pending[1])
        else:
            log.debug("처리하지 않은 메시지: %s", msg)

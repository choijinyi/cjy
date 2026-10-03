"""비트코인 채굴의 핵심 계산: SHA-256d, 블록 헤더 조립, 난이도/타깃 변환."""

import hashlib
import struct

# 난이도 1에 해당하는 타깃 (pdiff 기준, 풀에서 사용하는 값)
DIFF1_TARGET = 0xFFFF * 2 ** 208
MAX_TARGET = 2 ** 256 - 1


def sha256d(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def bits_to_target(nbits_hex: str) -> int:
    """compact 형식(nBits, 빅엔디언 hex)을 정수 타깃으로 변환한다."""
    nbits = int(nbits_hex, 16)
    exponent = nbits >> 24
    mantissa = nbits & 0xFFFFFF
    if exponent <= 3:
        return mantissa >> (8 * (3 - exponent))
    return mantissa << (8 * (exponent - 3))


def difficulty_to_target(difficulty: float) -> int:
    if difficulty <= 0:
        return MAX_TARGET
    return min(int(DIFF1_TARGET / difficulty), MAX_TARGET)


def target_to_difficulty(target: int) -> float:
    return DIFF1_TARGET / target if target else float("inf")


def hash_to_int(hash_bytes: bytes) -> int:
    """sha256d 결과(내부 바이트 순서)를 비교용 정수로 바꾼다."""
    return int.from_bytes(hash_bytes, "little")


def swap_words(data: bytes) -> bytes:
    """4바이트 단위로 바이트 순서를 뒤집는다 (Stratum prevhash 변환용)."""
    return b"".join(data[i:i + 4][::-1] for i in range(0, len(data), 4))


def build_coinbase(coinb1: str, extranonce1: str, extranonce2: str, coinb2: str) -> bytes:
    return bytes.fromhex(coinb1 + extranonce1 + extranonce2 + coinb2)


def build_merkle_root(coinbase: bytes, branches) -> bytes:
    root = sha256d(coinbase)
    for branch in branches:
        root = sha256d(root + branch)
    return root


def build_header_prefix(version_hex: str, prevhash_stratum: str, merkle_root: bytes,
                        ntime_hex: str, nbits_hex: str) -> bytes:
    """nonce를 제외한 76바이트 블록 헤더를 만든다.

    Stratum의 version/ntime/nbits는 빅엔디언 hex이므로 뒤집어서 넣고,
    prevhash는 4바이트 워드마다 뒤집힌 형태로 오므로 워드 단위로 되돌린다.
    """
    return (
        bytes.fromhex(version_hex)[::-1]
        + swap_words(bytes.fromhex(prevhash_stratum))
        + merkle_root
        + bytes.fromhex(ntime_hex)[::-1]
        + bytes.fromhex(nbits_hex)[::-1]
    )


def header_hash(header_prefix: bytes, nonce: int) -> bytes:
    return sha256d(header_prefix + struct.pack("<I", nonce))


def format_hashrate(hps: float) -> str:
    units = ["H/s", "kH/s", "MH/s", "GH/s", "TH/s", "PH/s", "EH/s"]
    i = 0
    while hps >= 1000 and i < len(units) - 1:
        hps /= 1000
        i += 1
    return f"{hps:.2f} {units[i]}"


def format_duration(seconds: float) -> str:
    if seconds == float("inf"):
        return "∞"
    years = seconds / (365.25 * 86400)
    if years >= 1:
        return f"{years:,.0f}년" if years < 1e15 else f"{years:.2e}년"
    days = seconds / 86400
    if days >= 1:
        return f"{days:,.1f}일"
    hours = seconds / 3600
    if hours >= 1:
        return f"{hours:.1f}시간"
    return f"{seconds / 60:.1f}분"

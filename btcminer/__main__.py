"""실행 진입점: python -m btcminer --address <비트코인 주소>"""

import argparse
import logging
import multiprocessing as mp
import signal
import sys
import time
import webbrowser

from .app import DequeLogHandler, Miner
from .core import format_hashrate

DEFAULT_POOL = "solo.ckpool.org:3333"


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="btcminer", description="CJY 비트코인 CPU 채굴기 (Stratum v1)")
    p.add_argument("-a", "--address", help="보상을 받을 비트코인 주소 (솔로 풀의 사용자 이름)")
    p.add_argument("-u", "--user", help="풀 사용자 이름을 직접 지정 (기본값: 주소.워커이름)")
    p.add_argument("-w", "--worker", default="cjy", help="워커 이름 (기본값: cjy)")
    p.add_argument("-p", "--password", default="x", help="풀 비밀번호 (기본값: x)")
    p.add_argument("-o", "--pool", default=DEFAULT_POOL, help=f"풀 주소 host:port (기본값: {DEFAULT_POOL})")
    p.add_argument("-t", "--threads", type=int, default=None, help="사용할 CPU 코어 수 (기본값: 전체-1)")
    p.add_argument("--port", type=int, default=8080, help="대시보드 포트 (기본값: 8080)")
    p.add_argument("--no-dashboard", action="store_true", help="웹 대시보드를 끈다")
    p.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않는다")
    p.add_argument("--benchmark", type=int, metavar="초", help="풀 접속 없이 해시 속도만 측정")
    p.add_argument("-v", "--verbose", action="store_true", help="자세한 로그")
    return p.parse_args(argv)


def run_benchmark(threads, seconds):
    from .worker import benchmark_job
    miner = Miner("benchmark", 0, "benchmark", threads=threads)
    miner.start_workers()
    miner.broadcast(benchmark_job())
    print(f"벤치마크: 워커 {miner.threads}개로 {seconds}초 동안 측정합니다...")
    time.sleep(1)
    with miner._hash_counter.get_lock():
        start = miner._hash_counter.value
    t0 = time.time()
    time.sleep(seconds)
    with miner._hash_counter.get_lock():
        end = miner._hash_counter.value
    rate = (end - start) / (time.time() - t0)
    miner.shutdown()
    print(f"결과: {format_hashrate(rate)} (코어당 {format_hashrate(rate / miner.threads)})")


def main(argv=None):
    args = parse_args(argv)
    level = logging.DEBUG if args.verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logging.basicConfig(level=level, handlers=[console])

    if args.benchmark:
        run_benchmark(args.threads, args.benchmark)
        return 0

    username = args.user or (f"{args.address}.{args.worker}" if args.address else None)
    if not username:
        print("비트코인 주소가 필요합니다. 예: python -m btcminer --address bc1q...", file=sys.stderr)
        return 2

    host, _, port = args.pool.replace("stratum+tcp://", "").rpartition(":")
    if not host or not port.isdigit():
        print(f"풀 주소 형식이 올바르지 않습니다: {args.pool} (예: solo.ckpool.org:3333)", file=sys.stderr)
        return 2

    miner = Miner(host, int(port), username, args.password, args.threads)
    memory = DequeLogHandler(miner.log_lines)
    memory.setFormatter(fmt)
    logging.getLogger().addHandler(memory)

    if not args.no_dashboard:
        from .dashboard import start_dashboard
        start_dashboard(miner, port=args.port)
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{args.port}")

    def stop(*_):
        logging.info("종료합니다...")
        miner.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    miner.run()
    return 0


if __name__ == "__main__":
    mp.freeze_support()
    sys.exit(main())

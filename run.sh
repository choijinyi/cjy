#!/usr/bin/env sh
# macOS / Linux 실행 스크립트
cd "$(dirname "$0")" || exit 1
if [ -z "$BTC_ADDRESS" ]; then
  printf "보상을 받을 비트코인 주소를 입력하세요: "
  read -r BTC_ADDRESS
fi
exec python3 -m btcminer --address "$BTC_ADDRESS" "$@"

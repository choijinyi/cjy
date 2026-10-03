@echo off
chcp 65001 > nul
cd /d "%~dp0"
where python > nul 2>&1 || (echo Python 3.8 이상이 필요합니다: https://www.python.org/downloads/ & pause & exit /b 1)
if "%BTC_ADDRESS%"=="" set /p BTC_ADDRESS=보상을 받을 비트코인 주소를 입력하세요: 
python -m btcminer --address %BTC_ADDRESS% %*
pause

#!/bin/bash
# ==============================================================================
# norosi 디스코드 봇 - 서버 수동 원클릭 업데이트 스크립트
# ==============================================================================
set -e

BOT_DIR="$HOME/norosi"
if [ ! -d "$BOT_DIR" ]; then
    BOT_DIR="$(pwd)"
fi

cd "$BOT_DIR"
echo "📂 작업 디렉토리: $BOT_DIR"

echo "🔄 [1/4] 프라이빗 깃허브 저장소에서 최신 코드 수신 중..."
git fetch origin main
git reset --hard origin/main

echo "📦 [2/4] 가상환경 활성화 및 패키지 점검..."
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
fi

echo "🔄 [3/4] norosi systemd 서비스 재시작..."
sudo systemctl restart norosi

echo "✅ [4/4] 서비스 상태 확인:"
sudo systemctl status norosi --no-pager -l

#!/bin/bash
# ==============================================================================
# norosi 디스코드 봇 - 서버 수동 원클릭 업데이트 스크립트
# ==============================================================================
set -e

BOT_DIR="$HOME/Desktop/norosi"
if [ ! -d "$BOT_DIR" ]; then
    BOT_DIR="$HOME/norosi"
fi
if [ ! -d "$BOT_DIR" ]; then
    BOT_DIR="$(pwd)"
fi

cd "$BOT_DIR"
echo "📂 작업 디렉토리: $BOT_DIR"

echo "🔄 [1/4] 프라이빗 깃허브 저장소에서 최신 코드 수신 중..."
git fetch origin
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "master")
git reset --hard "origin/$CURRENT_BRANCH" 2>/dev/null || git reset --hard origin/master 2>/dev/null || git reset --hard origin/main

echo "📦 [2/4] 가상환경 활성화 및 패키지 점검..."
if [ -d "venv" ]; then
    source venv/bin/activate
elif [ -d ".venv" ]; then
    source .venv/bin/activate
fi

if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt --quiet
fi
pip install -U yt-dlp --quiet || true

echo "🔄 [3/4] norosi 봇 재시작..."
if [ -d /run/systemd/system ] && sudo -n systemctl restart norosi 2>/dev/null; then
    echo "✅ [4/4] systemd 서비스 상태 확인:"
    sudo systemctl status norosi --no-pager -l
else
    echo "ℹ️ 컨테이너/비-systemd 환경 감지됨 -> 24/7 백그라운드 데몬 모드로 재기동합니다."
    if [ -f "$BOT_DIR/.norosi_supervisor.pid" ]; then
        kill -9 $(cat "$BOT_DIR/.norosi_supervisor.pid") 2>/dev/null || true
        rm -f "$BOT_DIR/.norosi_supervisor.pid"
    fi
    pkill -9 -f "[n]orosi_keepalive" 2>/dev/null || true

    if [ -f "$BOT_DIR/.norosi.pid" ]; then
        kill $(cat "$BOT_DIR/.norosi.pid") 2>/dev/null || true
        rm -f "$BOT_DIR/.norosi.pid"
    fi
    pkill -f "[p]ython.*bot\.py" 2>/dev/null || true
    sleep 1
    pkill -9 -f "[p]ython.*bot\.py" 2>/dev/null || true

    cat << 'DAEMON_EOF' > "$BOT_DIR/.norosi_keepalive.sh"
#!/usr/bin/env bash
cd "$(dirname "$0")"
WORK_DIR="$(pwd)"
echo $$ > "$WORK_DIR/.norosi_supervisor.pid"
if [ -x "$WORK_DIR/.venv/bin/python3" ]; then
  PY_BIN="$WORK_DIR/.venv/bin/python3"
elif [ -x "$WORK_DIR/venv/bin/python3" ]; then
  PY_BIN="$WORK_DIR/venv/bin/python3"
else
  PY_BIN="python3"
fi
while true; do
  "$PY_BIN" -u "$WORK_DIR/bot.py" >> "$WORK_DIR/bot.log" 2>&1 &
  BOT_PID=$!
  echo $BOT_PID > "$WORK_DIR/.norosi.pid"
  wait $BOT_PID
  EXIT_CODE=$?
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ bot.py 종료됨 (코드: $EXIT_CODE) - 5초 후 자동 재시작..." >> "$WORK_DIR/bot.log"
  sleep 5
done
DAEMON_EOF
    chmod +x "$BOT_DIR/.norosi_keepalive.sh"
    : > "$BOT_DIR/bot.log"
    setsid nohup bash -c "exec -a norosi_keepalive '$BOT_DIR/.norosi_keepalive.sh'" </dev/null >/dev/null 2>&1 &
    sleep 3
    echo "✅ [4/4] 백그라운드 데몬 가동 상태 및 최근 로그:"
    pgrep -af "[p]ython.*bot\.py" || true
    tail -n 40 "$BOT_DIR/bot.log" 2>/dev/null || true
fi


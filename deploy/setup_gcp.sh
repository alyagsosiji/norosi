#!/usr/bin/env bash
# ==============================================================================
# norosi 디스코드 봇 - Google Cloud Platform (GCP e2-micro) 원클릭 자동 배포 스크립트
# OS 지원: Ubuntu 22.04 LTS / Ubuntu 24.04 LTS (x86_64)
# ==============================================================================

set -e

echo "🚀 [1/6] norosi 디스코드 봇 GCP 무료 인스턴스 자동 설정을 시작합니다..."

CURRENT_USER=$(whoami)
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "📂 설치 경로: $APP_DIR"
echo "👤 실행 유저: $CURRENT_USER"

# ------------------------------------------------------------------------------
# 1. 2GB 스왑(Swap) 메모리 설정 (1GB RAM e2-micro OOM 크래시 방어 필수)
# ------------------------------------------------------------------------------
echo "🧠 [2/6] e2-micro 메모리 부족 방어용 2GB 가상 스왑(Swap) 메모리를 설정합니다..."
if [ ! -f /swapfile ]; then
    sudo fallocate -l 2G /swapfile || sudo dd if=/dev/zero of=/swapfile bs=1M count=2048
    sudo chmod 600 /swapfile
    sudo mkswap /swapfile
    sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    echo "✅ 2GB 스왑 메모리 생성 및 활성화 완료!"
else
    echo "ℹ️ 이미 /swapfile이 존재합니다. 건너뜁니다."
fi

# ------------------------------------------------------------------------------
# 2. 필수 시스템 패키지 설치
# ------------------------------------------------------------------------------
echo "📦 [3/6] 필수 시스템 패키지(Python3, venv, pip, git, ffmpeg)를 설치합니다..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git curl ffmpeg

# ------------------------------------------------------------------------------
# 3. Python 가상환경(venv) 구성 및 패키지 설치
# ------------------------------------------------------------------------------
echo "🐍 [4/6] Python 가상환경을 구축하고 requirements.txt를 설치합니다..."
cd "$APP_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# ------------------------------------------------------------------------------
# 4. .env 환경설정 파일 확인
# ------------------------------------------------------------------------------
echo "🔑 [5/6] 환경 변수(.env) 파일을 점검합니다..."
if [ ! -f "$APP_DIR/.env" ]; then
    if [ -f "$APP_DIR/deploy/.env.example" ]; then
        cp "$APP_DIR/deploy/.env.example" "$APP_DIR/.env"
        echo "⚠️  새로운 .env 파일이 생성되었습니다! (경로: $APP_DIR/.env)"
        echo "👉 나중에 'nano $APP_DIR/.env' 명령어로 디스코드 봇 토큰을 꼭 입력해주세요."
    fi
else
    echo "✅ 기존 .env 파일이 확인되었습니다."
fi

# ------------------------------------------------------------------------------
# 5. systemd 24시간 무중단 백그라운드 서비스 등록
# ------------------------------------------------------------------------------
echo "⚙️ [6/6] systemd 24/7 상시 가동 서비스(/etc/systemd/system/norosi.service)를 등록합니다..."

SERVICE_FILE="/etc/systemd/system/norosi.service"

sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=norosi Discord Bot (24/7 Service)
After=network.target

[Service]
Type=simple
User=$CURRENT_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=-$APP_DIR/.env
ExecStart=$APP_DIR/venv/bin/python3 $APP_DIR/bot.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable norosi.service
sudo systemctl restart norosi.service

echo ""
echo "=============================================================================="
echo "🎉 norosi 디스코드 봇 GCP 24/7 백그라운드 설정이 완료되었습니다!"
echo "=============================================================================="
echo "📌 유용한 관리 명령어:"
echo "  • 봇 상태 확인   : sudo systemctl status norosi"
echo "  • 실시간 로그 보기: journalctl -u norosi -f"
echo "  • 봇 재시작       : sudo systemctl restart norosi"
echo "  • 봇 중지         : sudo systemctl stop norosi"
echo "  • 환경변수 수정   : nano $APP_DIR/.env (수정 후 반드시 restart 실행)"
echo "=============================================================================="

#!/bin/bash
# ==============================================================================
# norosi 디스코드 봇 - GCP VM 전용 프라이빗 깃허브 SSH Deploy Key 자동 발급 및 환경 설정
# ==============================================================================
set -e

KEY_PATH="$HOME/.ssh/id_ed25519_deploy"
PUB_PATH="${KEY_PATH}.pub"
CONFIG_PATH="$HOME/.ssh/config"

echo "===================================================================="
echo "🔑 [1/4] 프라이빗 깃허브 전용 SSH 배포 키(Deploy Key) 점검 및 생성..."
echo "===================================================================="

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

if [ -f "$KEY_PATH" ]; then
    echo "ℹ️ 이미 기존 Deploy Key가 존재합니다: $KEY_PATH"
else
    echo "✨ 신규 Ed25519 배포 키를 생성합니다..."
    ssh-keygen -t ed25519 -C "norosi-gcp-deploy-key" -f "$KEY_PATH" -N ""
    chmod 600 "$KEY_PATH"
    chmod 644 "$PUB_PATH"
    echo "✅ SSH 배포 키 생성 완료!"
fi

echo ""
echo "===================================================================="
echo "⚙️ [2/4] SSH 접속 설정 (~/.ssh/config) 자동 구성..."
echo "===================================================================="

# github.com 접속 시 자동으로 Deploy Key를 사용하도록 등록
if grep -q "IdentityFile $KEY_PATH" "$CONFIG_PATH" 2>/dev/null; then
    echo "ℹ️ ~/.ssh/config에 이미 GitHub Deploy Key 설정이 등록되어 있습니다."
else
    cat <<EOF >> "$CONFIG_PATH"

# GitHub Private Repo Deploy Key for norosi
Host github.com
    HostName github.com
    User git
    IdentityFile $KEY_PATH
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
EOF
    chmod 600 "$CONFIG_PATH"
    echo "✅ ~/.ssh/config 설정 완료!"
fi

echo ""
echo "===================================================================="
echo "🛡️ [3/4] GitHub Actions 무중단 배포를 위한 systemctl 권한 설정 (NOPASSWD)..."
echo "===================================================================="

SUDOERS_FILE="/etc/sudoers.d/norosi-restart"
CURRENT_USER=$(whoami)

if [ -f "$SUDOERS_FILE" ]; then
    echo "ℹ️ 이미 systemctl 비밀번호 면제 권한이 설정되어 있습니다."
else
    echo "비밀번호 없이 GitHub Actions가 norosi 봇 서비스를 재시작할 수 있도록 권한을 부여합니다..."
    echo "$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart norosi, /bin/systemctl status norosi, /bin/systemctl is-active norosi" | sudo tee "$SUDOERS_FILE" > /dev/null
    sudo chmod 0440 "$SUDOERS_FILE"
    echo "✅ sudoers 권한 설정 완료!"
fi

echo ""
echo "===================================================================="
echo "📋 [4/4] 깃허브(GitHub)에 등록할 공개키(Public Key)"
echo "===================================================================="
echo "👉 아래 박스 안의 키 전체를 복사하여 깃허브 저장소에 등록하세요:"
echo "--------------------------------------------------------------------"
cat "$PUB_PATH"
echo "--------------------------------------------------------------------"
echo ""
echo "📌 [깃허브 등록 순서]:"
echo "1. 깃허브 프라이빗 저장소 페이지 접속 (https://github.com/사용자/저장소)"
echo "2. [Settings] 메뉴 탭 클릭"
echo "3. 좌측 사이드바의 [Deploy keys] 클릭"
echo "4. 우측 상단의 [Add deploy key] 녹색 버튼 클릭"
echo "5. Title: GCP-VM-Deploy-Key 입력"
echo "6. Key: 위에서 복사한 ssh-ed25519 ... 키 붙여넣기"
echo "7. (보안을 위해 'Allow write access'는 체크 해제한 채로) [Add key] 클릭!"
echo ""
echo "연결 테스트 명령어: ssh -T git@github.com"
echo "프라이빗 저장소 복제 명령어:"
echo "  git clone git@github.com:깃허브아이디/저장소이름.git ~/norosi"
echo "===================================================================="

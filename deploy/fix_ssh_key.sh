#!/bin/bash
# ==============================================================================
# norosi 디스코드 봇 - 원격 서버 GitHub Actions SSH 연동 스크립트
# 비밀키로부터 공개키를 직접 계산하여 authorized_keys와 100% 일치 보장
# ==============================================================================
set -e

KEY_PATH="$HOME/.ssh/id_ed25519_deploy"
AUTH_KEYS="$HOME/.ssh/authorized_keys"
SSH_HOST_DEFAULT="${SSH_HOST:-<서버_도메인_또는_IP>}"
SSH_PORT_DEFAULT="${SSH_PORT:-22}"

echo "===================================================================="
echo "🧹 [1/3] 기존 키 완전 초기화 및 100% 신규 SSH 배포 키 생성 중..."
echo "===================================================================="

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

# 충돌 방지를 위해 이전 키를 완전히 삭제하고 새 키로 재생성
rm -f "$KEY_PATH" "${KEY_PATH}.pub"
ssh-keygen -t ed25519 -C "norosi-remote-deploy" -f "$KEY_PATH" -N ""
chmod 600 "$KEY_PATH"

echo "===================================================================="
echo "🔑 [2/3] 비밀키에서 추출한 100% 동일 공개키를 authorized_keys에 즉시 동기화..."
echo "===================================================================="

# 비밀키(id_ed25519_deploy)로부터 계산된 100% 정확한 공개키 추출
DERIVED_PUB=$(ssh-keygen -y -f "$KEY_PATH")

touch "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

# 기존 중복 항목 정리 후 정확히 삽입
grep -vE "norosi-gcp-deploy|norosi-remote-deploy" "$AUTH_KEYS" > "${AUTH_KEYS}.tmp" 2>/dev/null || true
mv "${AUTH_KEYS}.tmp" "$AUTH_KEYS"
echo "$DERIVED_PUB norosi-remote-deploy" >> "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

# NOPASSWD systemctl & journalctl 재시작/로그조회 권한 보장
SUDOERS_FILE="/etc/sudoers.d/norosi-restart"
CURRENT_USER=$(whoami)
echo "$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart norosi, /bin/systemctl status norosi, /bin/systemctl is-active norosi, /usr/bin/systemctl restart norosi, /usr/bin/systemctl status norosi, /usr/bin/systemctl is-active norosi, /bin/journalctl -u norosi *, /usr/bin/journalctl -u norosi *" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 0440 "$SUDOERS_FILE"

echo ""
echo "===================================================================="
echo "🎉 [3/3] 깃허브 시크릿(GitHub Secrets) 설정 값 안내"
echo "===================================================================="
echo "📌 깃허브 저장소 > Settings > Secrets and variables > Actions 에서 아래 값을 설정하세요:"
echo ""
echo "1️⃣ GCP_HOST (또는 SSH_HOST):"
echo "--------------------------------------------------------------------"
echo "$SSH_HOST_DEFAULT"
echo "--------------------------------------------------------------------"
echo ""
echo "2️⃣ GCP_PORT (또는 SSH_PORT):"
echo "--------------------------------------------------------------------"
echo "$SSH_PORT_DEFAULT"
echo "--------------------------------------------------------------------"
echo ""
echo "3️⃣ GCP_USER (또는 SSH_USER):"
echo "--------------------------------------------------------------------"
echo "$CURRENT_USER"
echo "--------------------------------------------------------------------"
echo ""
echo "4️⃣ GCP_SSH_KEY (---BEGIN부터 END까지 전체 복사):"
echo "--------------------------------------------------------------------"
cat "$KEY_PATH"
echo "--------------------------------------------------------------------"
echo "===================================================================="

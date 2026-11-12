#!/bin/bash
# ==============================================================================
# norosi 디스코드 봇 - GCP VM SSH Permission Denied (publickey) 100% 완벽 해결 스크립트
# 비밀키로부터 공개키를 직접 계산하여 authorized_keys와 100% 수공학적 일치 보장
# ==============================================================================
set -e

KEY_PATH="$HOME/.ssh/id_ed25519_deploy"
AUTH_KEYS="$HOME/.ssh/authorized_keys"

echo "===================================================================="
echo "🧹 [1/3] 기존 키 완전 초기화 및 100% 신규 SSH 배포 키 생성 중..."
echo "===================================================================="

mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"

# 충돌 방지를 위해 이전 키를 완전히 삭제하고 새 키로 재생성
rm -f "$KEY_PATH" "${KEY_PATH}.pub"
ssh-keygen -t ed25519 -C "norosi-gcp-deploy" -f "$KEY_PATH" -N ""
chmod 600 "$KEY_PATH"

echo "===================================================================="
echo "🔑 [2/3] 비밀키에서 추출한 100% 동일 공개키를 authorized_keys에 즉시 동기화..."
echo "===================================================================="

# 비밀키(.id_ed25519_deploy)로부터 계산된 100% 정확한 공개키 추출
DERIVED_PUB=$(ssh-keygen -y -f "$KEY_PATH")

touch "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

# 기존 중복 항목 정리 후 정확히 삽입
grep -v "norosi-gcp-deploy" "$AUTH_KEYS" > "${AUTH_KEYS}.tmp" 2>/dev/null || true
mv "${AUTH_KEYS}.tmp" "$AUTH_KEYS"
echo "$DERIVED_PUB norosi-gcp-deploy" >> "$AUTH_KEYS"
chmod 600 "$AUTH_KEYS"

# NOPASSWD systemctl 재시작 권한 보장
SUDOERS_FILE="/etc/sudoers.d/norosi-restart"
CURRENT_USER=$(whoami)
echo "$CURRENT_USER ALL=(ALL) NOPASSWD: /bin/systemctl restart norosi, /bin/systemctl status norosi, /bin/systemctl is-active norosi" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 0440 "$SUDOERS_FILE"

EXT_IP=$(curl -s ifconfig.me 2>/dev/null || echo "GCP 콘솔의 외부 IP")

echo ""
echo "===================================================================="
echo "🎉 [3/3] 깃허브 시크릿(GitHub Secrets) 3종 100% 일치 값 출력"
echo "===================================================================="
echo "📌 깃허브 저장소 > Settings > Secrets and variables > Actions 에서 아래 3개를 설정하세요:"
echo ""
echo "1️⃣ GCP_HOST (값 1줄 복사):"
echo "--------------------------------------------------------------------"
echo "$EXT_IP"
echo "--------------------------------------------------------------------"
echo ""
echo "2️⃣ GCP_USER (값 1줄 복사 - 대소문자 정확히 일치 필수):"
echo "--------------------------------------------------------------------"
echo "$CURRENT_USER"
echo "--------------------------------------------------------------------"
echo ""
echo "3️⃣ GCP_SSH_KEY (---BEGIN부터 END까지 전체 복사):"
echo "--------------------------------------------------------------------"
cat "$KEY_PATH"
echo "--------------------------------------------------------------------"
echo ""
echo "💡 복사 시 주의사항:"
echo "   - GCP_SSH_KEY 복사 시 '-----BEGIN OPENSSH PRIVATE KEY-----' 및"
echo "     '-----END OPENSSH PRIVATE KEY-----' 포함 전체를 복사해야 합니다."
echo "   - 복사 후 GitHub Actions 탭에서 Re-run all jobs를 실행하세요!"
echo "===================================================================="

#!/usr/bin/env bash
# =============================================================================
#  bat-duckdns.sh — Bật HTTPS + đăng nhập Google qua tên miền DuckDNS
#
#  Dùng:  bash bat-duckdns.sh <duckdns-token> [ten-mien-con] [email]
#  Ví dụ: bash bat-duckdns.sh 1a2b3c4d-.... edugiaovien thay.abc@gmail.com
#
#  Script tự làm: trỏ DuckDNS -> VPS, cấu hình nginx, xin chứng chỉ HTTPS,
#  lưu cấu hình, khởi động lại và kiểm tra.
# =============================================================================
set -euo pipefail

TOKEN="${1:-}"
TEN="${2:-edugiaovien}"
EMAIL="${3:-}"

do_ok()   { echo -e "  \033[32m✓\033[0m $*"; }
do_err()  { echo -e "  \033[31m✗\033[0m $*"; }
do_step() { echo -e "\n\033[1;36m==> $*\033[0m"; }

[ -z "$TOKEN" ] && { echo "Thiếu token DuckDNS."; exit 1; }

MIEN="${TEN}.duckdns.org"
ENV_FILE=/etc/eduassist.env
NGINX_CONF=/etc/nginx/sites-available/eduassist
IP_VPS=$(curl -4 -s --max-time 10 https://api.ipify.org)

# --- 1. Trỏ DuckDNS về máy chủ -------------------------------------------------
do_step "1. Trỏ $MIEN về $IP_VPS"
KQ=$(curl -s --max-time 20 "https://www.duckdns.org/update?domains=${TEN}&token=${TOKEN}&ip=${IP_VPS}")
if [ "$KQ" != "OK" ]; then
  do_err "DuckDNS trả về: '$KQ'"
  echo "     Thường gặp khi: token sai, hoặc tên '$TEN' đã bị người khác dùng."
  echo "     Hãy thử tên khác, ví dụ: bash $0 <token> edugiaovien-edu"
  exit 1
fi
do_ok "DuckDNS đã nhận"

for i in $(seq 1 40); do
  IP_DNS=$(getent hosts "$MIEN" | awk '{print $1}' | head -1 || true)
  [ "$IP_DNS" = "$IP_VPS" ] && break
  sleep 3
done
if [ "$IP_DNS" != "$IP_VPS" ]; then
  do_err "DNS chưa cập nhật (đang là '${IP_DNS:-trống}'), cần là $IP_VPS. Đợi thêm 1–2 phút rồi chạy lại."
  exit 1
fi
do_ok "DNS đã trỏ đúng về máy chủ"

# --- 2. nginx ------------------------------------------------------------------
do_step "2. Cấu hình nginx"
cp -a "$NGINX_CONF" "${NGINX_CONF}.bak-$(date +%Y%m%d%H%M%S)"
mkdir -p /var/www/certbot
cat > "$NGINX_CONF" <<NGINX
# EduAssist — sinh tự động bởi bat-duckdns.sh
server {
 listen 80;
 listen [::]:80;
 server_name $MIEN;
 server_tokens off;
 client_max_body_size 16M;
 location /.well-known/acme-challenge/ { root /var/www/certbot; }
 location / {
  proxy_pass http://127.0.0.1:8080;
  proxy_set_header Host \$host;
  proxy_set_header X-Real-IP \$remote_addr;
  proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto \$scheme;
  proxy_read_timeout 120s;
 }
}
NGINX
ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/eduassist
nginx -t && systemctl reload nginx
do_ok "nginx đã nhận $MIEN"

# --- 3. Chứng chỉ HTTPS --------------------------------------------------------
do_step "3. Xin chứng chỉ HTTPS"
if ! command -v certbot >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
fi
if [ -d "/etc/letsencrypt/live/$MIEN" ]; then
  do_ok "đã có chứng chỉ"
else
  if [ -n "$EMAIL" ]; then
    certbot certonly --webroot -w /var/www/certbot -d "$MIEN" --non-interactive --agree-tos -m "$EMAIL"
  else
    certbot certonly --webroot -w /var/www/certbot -d "$MIEN" --non-interactive --agree-tos --register-unsafely-without-email
  fi
fi
do_ok "đã có chứng chỉ HTTPS"
CERT=/etc/letsencrypt/live/$MIEN

# --- 4. Cấu hình HTTPS cho nginx (giữ luôn cổng 80 để tự gia hạn) --------------
cat > "$NGINX_CONF" <<NGINX
# EduAssist — sinh tự động bởi bat-duckdns.sh
server {
 listen 80;
 listen [::]:80;
 server_name $MIEN;
 server_tokens off;
 location /.well-known/acme-challenge/ { root /var/www/certbot; }
 location / { return 301 https://\$host\$request_uri; }
}
server {
 listen 443 ssl;
 listen [::]:443 ssl;
 http2 on;
 server_name $MIEN;
 server_tokens off;
 client_max_body_size 16M;
 ssl_certificate     $CERT/fullchain.pem;
 ssl_certificate_key $CERT/privkey.pem;
 ssl_protocols TLSv1.2 TLSv1.3;
 ssl_prefer_server_ciphers off;
 add_header Strict-Transport-Security "max-age=31536000" always;
 location / {
  proxy_pass http://127.0.0.1:8080;
  proxy_set_header Host \$host;
  proxy_set_header X-Real-IP \$remote_addr;
  proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
  proxy_set_header X-Forwarded-Proto \$scheme;
  proxy_read_timeout 120s;
 }
}
NGINX
nginx -t && systemctl reload nginx
do_ok "nginx đang chạy HTTPS"

# --- 5. Lưu cấu hình ứng dụng --------------------------------------------------
do_step "5. Lưu địa chỉ HTTPS vào cấu hình"
touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
if grep -q '^PUBLIC_BASE_URL=' "$ENV_FILE"; then
  sed -i "s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://$MIEN|" "$ENV_FILE"
else
  echo "PUBLIC_BASE_URL=https://$MIEN" >> "$ENV_FILE"
fi
echo "HTTPS_ONLY=1" >> "$ENV_FILE"
sed -i '0,/^HTTPS_ONLY=/{/^HTTPS_ONLY=/d}' "$ENV_FILE"
echo "HTTPS_ONLY=1" >> "$ENV_FILE"
do_ok "PUBLIC_BASE_URL=https://$MIEN"
systemctl restart eduassist && sleep 4
systemctl is-active eduassist >/dev/null && do_ok "đã khởi động lại EduAssist"

# --- 6. Kiểm tra ---------------------------------------------------------------
do_step "6. Kiểm tra kết quả"
LOI=0
curl -s -o /dev/null --max-time 20 "https://$MIEN/suc-khoe" \
  && do_ok "https://$MIEN truy cập được" || { do_err "chưa truy cập được"; LOI=1; }

if curl -s --max-time 20 "https://$MIEN/login" | grep -q '/login/google"'; then
  do_ok "nút 'Đăng nhập bằng Google' đã BẬT"
else
  do_err "nút Google vẫn tắt — còn thiếu Google Client ID / Client Secret"
  echo "     Nhập tại: https://$MIEN/quan-tri/cai-dat  (mục 🔑 Đăng nhập Google)"; LOI=1
fi

echo
echo "=============================================================="
echo " DÁN DÒNG NÀY VÀO GOOGLE CLOUD CONSOLE"
echo " (Clients → OAuth client → Authorized redirect URIs)"
echo
echo "   https://$MIEN/login/google/callback"
echo "=============================================================="
exit "$LOI"

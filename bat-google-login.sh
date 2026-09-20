#!/usr/bin/env bash
# =============================================================================
#  bat-google-login.sh — Bật đăng nhập Google cho EduAssist trên VPS
#
#  Cách dùng:
#     bash bat-google-login.sh <ten-mien> <email-nhan-thong-bao> [client_id] [client_secret]
#
#  Ví dụ:
#     bash bat-google-login.sh eduassist.vn thay.abc@gmail.com \
#          1234567890-xxx.apps.googleusercontent.com GOCSPX-xxxxxxxx
#
#  Script làm 4 việc:
#     1. Trỏ nginx sang tên miền mới
#     2. Xin chứng chỉ HTTPS Let's Encrypt (bắt buộc, Google không nhận http://)
#     3. Lưu địa chỉ HTTPS + khoá Google vào cấu hình
#     4. Khởi động lại và tự kiểm tra
# =============================================================================
set -euo pipefail

TEN_MIEN="${1:-}"
EMAIL="${2:-}"
CLIENT_ID="${3:-}"
CLIENT_SECRET="${4:-}"
ENV_FILE=/etc/eduassist.env
NGINX_CONF=/etc/nginx/sites-available/eduassist

do_ok()   { echo -e "  \033[32m✓\033[0m $*"; }
do_err()  { echo -e "  \033[31m✗\033[0m $*"; }
do_step() { echo -e "\n\033[1;36m==> $*\033[0m"; }

if [ -z "$TEN_MIEN" ] || [ -z "$EMAIL" ]; then
  echo "Thiếu tham số."
  echo "Dùng: bash bat-google-login.sh <ten-mien> <email> [client_id] [client_secret]"
  exit 1
fi

# --- 0. Kiểm tra DNS đã trỏ đúng về máy chủ chưa -----------------------------
do_step "0. Kiểm tra DNS của $TEN_MIEN"
IP_BEN_NGOAI=$(curl -4 -s --max-time 10 https://api.ipify.org || curl -4 -s --max-time 10 https://ifconfig.me || echo "")
IP_TEN_MIEN=$(getent hosts "$TEN_MIEN" | awk '{print $1}' | head -1 || echo "")
echo "  IP máy chủ hiện tại : ${IP_BEN_NGOAI:-không xác định được}"
echo "  IP mà tên miền trỏ tới: ${IP_TEN_MIEN:-không phân giải được}"
if [ -z "$IP_TEN_MIEN" ]; then
  do_err "Tên miền chưa phân giải được. Hãy thêm bản ghi A trỏ $TEN_MIEN -> ${IP_BEN_NGOAI:-<IP VPS>} rồi chạy lại."
  exit 1
fi
if [ -n "$IP_BEN_NGOAI" ] && [ "$IP_TEN_MIEN" != "$IP_BEN_NGOAI" ]; then
  do_err "DNS chưa trỏ đúng về máy chủ này. Cần chờ DNS cập nhật (có thể mất 5–30 phút)."
  exit 1
fi
do_ok "DNS đã trỏ đúng về máy chủ"

# --- 1. Cấu hình nginx cho tên miền ------------------------------------------
do_step "1. Cấu hình nginx cho $TEN_MIEN"
cp -a "$NGINX_CONF" "${NGINX_CONF}.bak-$(date +%Y%m%d%H%M%S)"
mkdir -p /var/www/certbot
cat > "$NGINX_CONF" <<NGINX
# EduAssist — sinh tự động bởi bat-google-login.sh
server {
 listen 80;
 listen [::]:80;
 server_name $TEN_MIEN;
 server_tokens off;
 client_max_body_size 16M;

 # Let's Encrypt xác thực qua đường dẫn này
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
do_ok "nginx đã nhận tên miền"

# --- 2. Xin chứng chỉ HTTPS ---------------------------------------------------
do_step "2. Xin chứng chỉ HTTPS (Let's Encrypt)"
if ! command -v certbot >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq certbot python3-certbot-nginx
fi
if [ -d "/etc/letsencrypt/live/$TEN_MIEN" ]; then
  certbot renew --cert-name "$TEN_MIEN" --quiet || true
  do_ok "đã có chứng chỉ, tiến hành gia hạn nếu cần"
else
  certbot --nginx -d "$TEN_MIEN" --non-interactive --agree-tos -m "$EMAIL" --redirect
  do_ok "đã cấp chứng chỉ HTTPS"
fi

# nginx đã được certbot sửa; thêm header bảo mật nếu certbot chưa thêm
if ! grep -q "Strict-Transport-Security" "$NGINX_CONF"; then
  sed -i "/server_tokens off;/a\\ add_header Strict-Transport-Security \"max-age=31536000\" always;" "$NGINX_CONF"
fi
nginx -t && systemctl reload nginx
do_ok "nginx đang chạy HTTPS"

# --- 3. Lưu cấu hình cho ứng dụng --------------------------------------------
do_step "3. Lưu cấu hình đăng nhập Google"
touch "$ENV_FILE"; chmod 600 "$ENV_FILE"
dat_bien() {  # dat_bien KEY VALUE  (ghi đè nếu đã có)
  local k="$1" v="$2"
  [ -z "$v" ] && return 0
  if grep -q "^${k}=" "$ENV_FILE"; then
    sed -i "s|^${k}=.*|${k}=${v}|" "$ENV_FILE"
  else
    printf '%s=%s\n' "$k" "$v" >> "$ENV_FILE"
  fi
}
dat_bien PUBLIC_BASE_URL "https://$TEN_MIEN"
[ -n "$CLIENT_ID" ]     && dat_bien GOOGLE_CLIENT_ID "$CLIENT_ID"
[ -n "$CLIENT_SECRET" ] && dat_bien GOOGLE_CLIENT_SECRET "$CLIENT_SECRET"
do_ok "PUBLIC_BASE_URL=https://$TEN_MIEN"
if [ -n "$CLIENT_ID" ]; then do_ok "đã lưu Google Client ID"; else
  echo "  ⚠ chưa truyền Client ID — thầy/cô có thể nhập sau trong Cài đặt hệ thống"
fi
if [ -n "$CLIENT_SECRET" ]; then do_ok "đã lưu Google Client Secret"; fi

systemctl restart eduassist
sleep 3
do_ok "đã khởi động lại EduAssist"

# --- 4. Tự kiểm tra -----------------------------------------------------------
do_step "4. Kiểm tra kết quả"
LOI=0
if curl -s -o /dev/null --max-time 15 "https://$TEN_MIEN/suc-khoe"; then
  do_ok "https://$TEN_MIEN truy cập được"
else
  do_err "chưa truy cập được https://$TEN_MIEN"; LOI=1
fi

if curl -s --max-time 15 "https://$TEN_MIEN/login" | grep -q "/login/google\""; then
  do_ok "nút 'Đăng nhập bằng Google' đã hiện trên trang đăng nhập"
else
  do_err "nút Google chưa hiện — nhiều khả năng còn thiếu Client ID / Client Secret"; LOI=1
fi

if curl -s -o /dev/null -w '%{http_code}' --max-time 15 -L "https://$TEN_MIEN/login/google" | grep -qE '200|302'; then
  do_ok "đường dẫn /login/google phản hồi tốt"
else
  do_err "/login/google có vấn đề"; LOI=1
fi

echo
echo "=============================================================="
echo " ĐỊA CHỈ CHUYỂN HƯỚNG cần dán vào Google Cloud Console:"
echo "   https://$TEN_MIEN/login/google/callback"
echo " (mục Authorized redirect URIs khi tạo OAuth client ID)"
echo "=============================================================="
[ "$LOI" -eq 0 ] && do_ok "HOÀN TẤT" || do_err "còn lỗi cần xử lý ở trên"
exit "$LOI"

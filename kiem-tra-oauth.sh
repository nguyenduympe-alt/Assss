#!/usr/bin/env bash
# kiem-tra-oauth.sh <ten-mien>  — kiểm thử thực tế đăng nhập Google, không cần trình duyệt
# Dùng: bash kiem-tra-oauth.sh edugiaovien.duckdns.org
set -uo pipefail
D="${1:-}"
[ -z "$D" ] && { echo "Dùng: bash $0 <ten-mien>"; exit 1; }
ok(){ echo -e "  \033[32m✓\033[0m $*"; }; loi(){ echo -e "  \033[31m✗\033[0m $*"; }

echo "== Kiểm thử đăng nhập Google cho $D =="

# 1. HTTPS sống chưa
c=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$D/suc-khoe")
[ "$c" = "200" ] && ok "HTTPS sống" || { loi "HTTPS chưa sống (HTTP $c)"; exit 1; }

# 2. Nút Google đã bật chưa
HTML=$(curl -s --max-time 20 "https://$D/login")
echo "$HTML" | grep -q '/login/google"' && ok "nút Google đã BẬT" || { loi "nút Google còn tắt"; exit 1; }

# 3. Trang /login/google có đẩy sang Google không, redirect_uri nhận được là gì
LOC=$(curl -s -o /dev/null -w '%{redirect_url}' --max-time 20 "https://$D/login/google")
echo "$LOC" | grep -q '^https://accounts.google.com/' || { loi "không đẩy sang Google: $LOC"; exit 1; }
ok "đẩy sang Google"
RU=$(printf '%s' "$LOC" | sed -n 's/.*redirect_uri=\([^&]*\).*/\1/p' | python3 -c 'import sys,urllib.parse;print(urllib.parse.unquote(sys.stdin.read().strip()))')
[ "$RU" = "https://$D/login/google/callback" ] && ok "redirect_uri = $RU" || loi "redirect_uri lạ: $RU"

# 4. Google có chấp nhận yêu cầu này không
BODY=$(curl -s --max-time 25 -A 'Mozilla/5.0' "$LOC")
if echo "$BODY" | grep -q 'redirect_uri_mismatch'; then
  loi "Google TỪ CHỐI: redirect URI '$RU' CHƯA được khai trên Google Cloud Console"
  echo "     → Cần thêm đúng dòng này vào Authorized redirect URIs:"
  echo "       $RU"
  exit 2
elif echo "$BODY" | grep -qi 'invalid_client'; then
  loi "Google báo client_id không tồn tại"; exit 3
else
  ok "GOOGLE ĐÃ CHẤP NHẬN — sẵn sàng đăng nhập thật bằng trình duyệt"
  echo "     Mở: https://$D/login  → bấm 'Đăng nhập bằng Google'"
  exit 0
fi

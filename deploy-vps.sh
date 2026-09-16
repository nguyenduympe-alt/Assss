#!/usr/bin/env bash
# ============================================================
#  Script cài đặt EduAssist lên VPS Ubuntu 22.04/24.04
#  Chạy với quyền root:  sudo bash deploy-vps.sh ten-mien.com email@cua-ban.com
# ============================================================
set -e

DOMAIN="${1:-}"
EMAIL="${2:-}"
APP_DIR="/opt/eduassist"
SERVICE="eduassist"

if [ -z "$DOMAIN" ]; then
  echo "Cách dùng: sudo bash deploy-vps.sh ten-mien.com email@cua-ban.com"
  exit 1
fi

echo "==> [1/7] Cài gói hệ thống"
apt update -y
apt install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx rsync

echo "==> [2/7] Sao chép mã nguồn vào $APP_DIR"
mkdir -p "$APP_DIR"
rsync -a --exclude 'data' --exclude '__pycache__' --exclude '.git' ./ "$APP_DIR"/
mkdir -p /var/lib/eduassist

echo "==> [3/7] Tạo môi trường ảo và cài thư viện"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> [4/7] Tạo dịch vụ systemd (tự khởi động cùng máy)"
SECRET=$(python3 -c "import secrets;print(secrets.token_hex(32))")
cat > /etc/systemd/system/$SERVICE.service <<EOF
[Unit]
Description=EduAssist - Tro ly giao vien
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=$APP_DIR
Environment="SECRET_KEY=$SECRET"
Environment="DB_DIR=/var/lib/eduassist"
Environment="HTTPS_ONLY=1"
Environment="FREE_QUOTA=3"
Environment="PRICE=100000"
Environment="BANK_CODE=agribank"
Environment="BANK_ACC=7614215002756"
Environment="BANK_NAME=Agribank"
# Bo dau # va dan key neu dung dang nhap Google:
#Environment="GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com"
#Environment="GOOGLE_CLIENT_SECRET=GOCSPX-xxx"
ExecStart=$APP_DIR/venv/bin/gunicorn "app:create_app()" --bind 127.0.0.1:8080 --workers 3 --threads 4 --timeout 120
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

chown -R www-data:www-data "$APP_DIR" /var/lib/eduassist
systemctl daemon-reload
systemctl enable --now $SERVICE

echo "==> [5/7] Cấu hình Nginx cho $DOMAIN"
cat > /etc/nginx/sites-available/$SERVICE <<EOF
server {
    listen 80;
    server_name $DOMAIN;
    client_max_body_size 20M;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
EOF
ln -sf /etc/nginx/sites-available/$SERVICE /etc/nginx/sites-enabled/$SERVICE
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> [6/7] Cài chứng chỉ HTTPS miễn phí (Let's Encrypt)"
if [ -n "$EMAIL" ]; then
  certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos -m "$EMAIL" --redirect || \
    echo "!! Cấp HTTPS thất bại — kiểm tra tên miền đã trỏ đúng IP chưa, rồi chạy: certbot --nginx -d $DOMAIN"
fi

echo "==> [7/7] Đặt lịch sao lưu tự động hằng ngày (2 giờ sáng, giữ 30 ngày)"
mkdir -p /var/backups/eduassist
cat > /usr/local/bin/eduassist-backup <<'BK'
#!/usr/bin/env bash
# Sao luu CSDL EduAssist, giu 30 ban gan nhat
D=$(date +%Y%m%d-%H%M)
sqlite3 /var/lib/eduassist/edu.db ".backup /var/backups/eduassist/edu-$D.db" 2>/dev/null   || cp /var/lib/eduassist/edu.db "/var/backups/eduassist/edu-$D.db"
find /var/backups/eduassist -name 'edu-*.db' -mtime +30 -delete
BK
chmod +x /usr/local/bin/eduassist-backup
apt install -y sqlite3 >/dev/null 2>&1 || true
( crontab -l 2>/dev/null | grep -v eduassist-backup ; echo "0 2 * * * /usr/local/bin/eduassist-backup" ) | crontab -
/usr/local/bin/eduassist-backup && echo "   Đã tạo bản sao lưu đầu tiên."

echo ""
echo "=========================================="
echo " HOÀN TẤT! Truy cập: https://$DOMAIN"
echo " Tài khoản mặc định: gv / 123456  (ĐỔI NGAY!)"
echo ""
echo " Lệnh hữu ích:"
echo "   systemctl status $SERVICE      # xem trạng thái"
echo "   systemctl restart $SERVICE     # khởi động lại"
echo "   journalctl -u $SERVICE -f      # xem log"
echo "   Dữ liệu nằm tại:  /var/lib/eduassist/edu.db"
echo "   Bản sao lưu tại:  /var/backups/eduassist/"
echo "   Sao lưu ngay:     eduassist-backup"
echo "=========================================="

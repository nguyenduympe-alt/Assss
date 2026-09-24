import os
import logging
from flask import Flask
from .db import init_db, close_db


def _ngay_vn(gia_tri):
    """Định dạng ngày kiểu Việt Nam: 2026-09-24 / 2026-09-24T06:43 -> 24/09/2026 [06:43]."""
    if gia_tri in (None, '', '—'):
        return gia_tri or ''
    s = str(gia_tri).strip()
    if len(s) >= 10 and s[4] == '-' and s[7] == '-':
        d, m, y = s[8:10], s[5:7], s[:4]
        if d.isdigit() and m.isdigit() and y.isdigit():
            kq = '%s/%s/%s' % (d, m, y)
            if len(s) >= 16 and s[10] in ' T' and s[11:13].isdigit() and s[14:16].isdigit():
                kq += ' ' + s[11:16]
            return kq
    return s


def create_app():
    app = Flask(__name__)
    # Ngày tháng hiển thị kiểu Việt Nam (dd/mm/yyyy) trên mọi template
    app.add_template_filter(_ngay_vn, 'ngay_vn')
    # Khi deploy: đặt biến môi trường SECRET_KEY (chuỗi ngẫu nhiên dài)
    app.secret_key = os.environ.get("SECRET_KEY", "edu-dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 60 * 1024 * 1024  # cho phép tải lên tài liệu 50MB
    # (LOGO-B) tệp nhận diện (logo, favicon) cho trình duyệt nhớ 7 ngày — đổi logo thì đổi số ?v= trong template
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 60 * 60 * 24 * 7
    if os.environ.get("HTTPS_ONLY", "").lower() in ("1", "true", "yes"):
        app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True,
                          SESSION_COOKIE_SAMESITE="Lax")
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    from werkzeug.middleware.proxy_fix import ProxyFix
    # Gunicorn listens on loopback; Nginx overwrites forwarded headers.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    from .security import install
    install(app)
    app.teardown_appcontext(close_db)
    init_db()
    # nạp cấu hình admin đã lưu trong CSDL (ưu tiên hơn biến môi trường)
    with app.app_context():
        import sqlite3
        from .db import DB_PATH
        from .modules import config as CFG
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        CFG.nap(con)
        con.close()
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    from .auth import bp as auth_bp
    from .core import bp as core_bp
    from .webhook import bp as webhook_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(core_bp)
    app.register_blueprint(webhook_bp)
    # ---- ĐIỂM MỞ RỘNG: thêm blueprint mới của bạn ở đây ----
    try:
        from .plugins import register_plugins
        register_plugins(app)
    except Exception as e:
        app.logger.info("plugins: %s", e)
    return app

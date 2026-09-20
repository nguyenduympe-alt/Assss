import os
import logging
from flask import Flask
from .db import init_db, close_db


def create_app():
    app = Flask(__name__)
    # Khi deploy: đặt biến môi trường SECRET_KEY (chuỗi ngẫu nhiên dài)
    app.secret_key = os.environ.get("SECRET_KEY", "edu-dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
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

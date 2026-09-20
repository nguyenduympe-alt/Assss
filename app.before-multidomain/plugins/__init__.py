"""Cơ chế mở rộng: mỗi file .py trong thư mục này định nghĩa biến `bp` (Blueprint)
và tuỳ chọn `MENU = {"label": "Tên menu", "endpoint": "ten_bp.index", "icon": "🧩"}`.
Hệ thống tự động nạp khi khởi động — không cần sửa code lõi.
"""
import importlib, pkgutil, os

MENUS = []


def register_plugins(app):
    MENUS.clear()
    for m in pkgutil.iter_modules([os.path.dirname(__file__)]):
        if m.name.startswith("_"):
            continue
        mod = importlib.import_module(f".{m.name}", __package__)
        if hasattr(mod, "bp"):
            app.register_blueprint(mod.bp)
        if hasattr(mod, "MENU"):
            MENUS.append(mod.MENU)
    app.jinja_env.globals["PLUGIN_MENUS"] = MENUS

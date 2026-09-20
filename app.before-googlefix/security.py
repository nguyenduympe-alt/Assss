import hashlib
import secrets
import time
from flask import request, session, jsonify
from .db import get_db


def csrf_token():
    if 'csrf' not in session:
        session['csrf'] = secrets.token_urlsafe(32)
    return session['csrf']


def install(app):
    app.context_processor(lambda: {'csrf_token': csrf_token})

    @app.before_request
    def protect_forms():
        protected = {'auth.login', 'auth.register', 'auth.doi_mk', 'core.qt_caidat',
                     'core.chinh_ta', 'core.chinh_ta_sua', 'core.chinh_ta_xem'}
        if request.method == 'POST' and (request.endpoint in protected or (request.endpoint or '').startswith('digital.')):
            supplied = request.form.get('csrf_token') or request.headers.get('X-CSRF-Token', '')
            if not supplied or not secrets.compare_digest(supplied, session.get('csrf', '')):
                if request.is_json:
                    return jsonify(ok=False, msg='Phiên đã hết hạn. Vui lòng tải lại trang.'), 400
                return 'Phiên đã hết hạn. Vui lòng tải lại trang rồi thử lại.', 400


def allow_request(scope, identity, limit, window):
    db = get_db()
    db.execute('CREATE TABLE IF NOT EXISTS request_limit (key TEXT PRIMARY KEY, count INTEGER, expires INTEGER)')
    now = int(time.time())
    key = hashlib.sha256(f'{scope}:{identity}:{now // window}'.encode()).hexdigest()
    db.execute('DELETE FROM request_limit WHERE expires < ?', (now,))
    db.execute('INSERT INTO request_limit VALUES (?,1,?) ON CONFLICT(key) DO UPDATE SET count=count+1',
               (key, (now // window + 1) * window))
    count = db.execute('SELECT count FROM request_limit WHERE key=?', (key,)).fetchone()[0]
    db.commit()
    return count <= limit

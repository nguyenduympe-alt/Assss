import datetime
import ipaddress
import re
import sqlite3
from functools import wraps
from urllib.parse import urlsplit
from flask import session, redirect, url_for, Blueprint, render_template, request, flash, current_app, abort
from werkzeug.security import check_password_hash, generate_password_hash
from .db import get_db
from .modules import config as CFG
from .security import allow_request

bp = Blueprint('auth', __name__)


def google_callback_url():
    base = CFG.get('PUBLIC_BASE_URL', '').strip().rstrip('/')
    try:
        u = urlsplit(base)
        if u.scheme != 'https' or not u.hostname or u.username or u.password or u.query or u.fragment or u.path:
            return ''
        if u.port not in (None, 443) or '.' not in u.hostname:
            return ''
        try:
            ipaddress.ip_address(u.hostname)
            return ''
        except ValueError:
            pass
    except ValueError:
        return ''
    return base + '/login/google/callback'


def google_bat():
    return bool(CFG.get('GOOGLE_CLIENT_ID') and CFG.get('GOOGLE_CLIENT_SECRET') and google_callback_url())


def get_oauth():
    cid, secret = CFG.get('GOOGLE_CLIENT_ID', ''), CFG.get('GOOGLE_CLIENT_SECRET', '')
    key = (cid, secret)
    cached = current_app.extensions.get('edu_google')
    if cached and cached[0] == key:
        return cached[1]
    from authlib.integrations.flask_client import OAuth
    oauth = OAuth()
    oauth.init_app(current_app)
    oauth.register(name='google', client_id=cid, client_secret=secret,
                   server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
                   client_kwargs={'scope': 'openid email profile', 'timeout': 20})
    current_app.extensions['edu_google'] = (key, oauth)
    return oauth


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not current_user():
            session.clear()
            return redirect(url_for('auth.login', next=request.path))
        return f(*a, **k)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        u = current_user()
        if not u:
            return redirect(url_for('auth.login', next=request.path))
        if u['role'] != 'admin':
            abort(403)
        return f(*a, **k)
    return w


def current_user():
    if session.get('uid'):
        return get_db().execute('SELECT * FROM teacher WHERE id=?', (session['uid'],)).fetchone()


def safe_next(value):
    if value and value.startswith('/') and not value.startswith('//') and '\\' not in value and not any(ord(c) < 32 for c in value):
        return value
    return url_for('core.dashboard')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user():
        return redirect(url_for('core.dashboard'))
    status = 200
    if request.method == 'POST':
        u, p = request.form.get('username', '').strip(), request.form.get('password', '')
        if not allow_request('login', request.remote_addr, 30, 900):
            flash('Bạn đã thử đăng nhập quá nhiều lần. Vui lòng thử lại sau 15 phút.', 'err')
            status = 429
        elif not u or not p or len(u) > 254 or len(p) > 128:
            flash('Vui lòng nhập tài khoản và mật khẩu hợp lệ.', 'err')
            status = 400
        else:
            rows = get_db().execute('SELECT * FROM teacher WHERE lower(username)=lower(?) OR lower(email)=lower(?)', (u, u)).fetchall()
            row = rows[0] if len(rows) == 1 else None
            if row and row['password'] and check_password_hash(row['password'], p):
                session.clear()
                session['uid'] = row['id']
                return redirect(safe_next(request.args.get('next')))
            flash('Tài khoản hoặc mật khẩu không đúng. Nếu đăng ký bằng Google, hãy chọn đăng nhập bằng Google.', 'err')
            status = 401
    return render_template('login.html', google_enabled=google_bat()), status


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))


@bp.route('/dangky', methods=['GET', 'POST'])
def register():
    if current_user():
        return redirect(url_for('core.dashboard'))
    errors, values, status = {}, {}, 200
    if request.method == 'POST':
        values = {k: request.form.get(k, '').strip() for k in ('username', 'email', 'fullname', 'school', 'subject')}
        values['email'] = values['email'].lower()
        password = request.form.get('password', '')
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{2,31}', values['username']):
            errors['username'] = 'Tên đăng nhập phải có 3–32 ký tự: chữ không dấu, số, dấu chấm, gạch dưới hoặc gạch ngang.'
        if len(values['email']) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', values['email']):
            errors['email'] = 'Vui lòng nhập địa chỉ email hợp lệ.'
        if not 2 <= len(values['fullname']) <= 100:
            errors['fullname'] = 'Họ và tên phải có từ 2 đến 100 ký tự.'
        for k in ('school', 'subject'):
            if len(values[k]) > 150:
                errors[k] = 'Nội dung không được quá 150 ký tự.'
        if not 8 <= len(password) <= 128 or not re.search(r'[^\W\d_]', password, re.UNICODE) or not re.search(r'\d', password):
            errors['password'] = 'Mật khẩu cần 8–128 ký tự, gồm cả chữ và số.'
        if password != request.form.get('password_confirm', ''):
            errors['password_confirm'] = 'Mật khẩu nhập lại không khớp.'
        db = get_db()
        if not allow_request('register', request.remote_addr, 15, 900):
            errors['form'] = 'Bạn đã thử đăng ký quá nhiều lần. Vui lòng thử lại sau 15 phút.'
            status = 429
        if not errors:
            try:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT 1 FROM teacher WHERE lower(username)=lower(?)', (values['username'],)).fetchone():
                    errors['username'] = 'Tên đăng nhập đã được sử dụng. Vui lòng chọn tên khác.'
                if db.execute('SELECT 1 FROM teacher WHERE lower(email)=?', (values['email'],)).fetchone():
                    errors['email'] = 'Email đã được đăng ký. Vui lòng đăng nhập tài khoản hiện có.'
                if errors:
                    db.rollback()
                else:
                    db.execute('INSERT INTO teacher(username,password,fullname,school,subject,email,created) VALUES(?,?,?,?,?,?,?)',
                               (values['username'], generate_password_hash(password), values['fullname'], values['school'], values['subject'], values['email'], datetime.date.today().isoformat()))
                    db.commit()
                    flash('Đăng ký thành công! Bạn có thể đăng nhập bằng tên tài khoản hoặc email.', 'ok')
                    return redirect(url_for('auth.login'))
            except sqlite3.IntegrityError:
                db.rollback()
                errors['form'] = 'Tài khoản vừa được đăng ký. Vui lòng dùng tên tài khoản hoặc email khác.'
            except sqlite3.OperationalError:
                db.rollback()
                errors['form'] = 'Hệ thống đang bận. Vui lòng thử lại sau.'
                status = 503
        if errors and status == 200:
            status = 400
    return render_template('register.html', google_enabled=google_bat(), errors=errors, values=values), status


@bp.route('/login/google')
def google_login():
    if not google_bat():
        flash('Đăng nhập Google chưa được kích hoạt. Vui lòng dùng tài khoản và mật khẩu.', 'err')
        return redirect(url_for('auth.login'))
    callback = google_callback_url()
    canonical = callback.removesuffix('/login/google/callback')
    if request.url_root.rstrip('/') != canonical:
        return redirect(canonical + '/login/google')
    session['google_link_uid'] = session.get('uid')
    try:
        return get_oauth().google.authorize_redirect(callback, prompt='select_account')
    except Exception:
        flash('Chưa kết nối được Google. Vui lòng thử lại sau.', 'err')
        return redirect(url_for('auth.login'))


@bp.route('/login/google/callback')
def google_callback():
    if not google_bat():
        return redirect(url_for('auth.login'))
    link_uid = session.pop('google_link_uid', None)
    try:
        token = get_oauth().google.authorize_access_token()
        info = token.get('userinfo') or {}
    except Exception:
        flash('Đăng nhập Google bị hủy hoặc phiên đã hết hạn. Vui lòng thử lại.', 'err')
        return redirect(url_for('auth.login'))
    sub, email = info.get('sub'), (info.get('email') or '').lower()
    if not sub or not email or info.get('email_verified') is not True:
        flash('Google chưa xác minh địa chỉ email của tài khoản này.', 'err')
        return redirect(url_for('auth.login'))
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM teacher WHERE google_sub=?', (sub,)).fetchone()
        matches = db.execute('SELECT * FROM teacher WHERE lower(email)=?', (email,)).fetchall()
        if link_uid:
            user = current_user()
            if not user or user['id'] != link_uid or (row and row['id'] != link_uid) or any(r['id'] != link_uid for r in matches) or (user['google_sub'] and user['google_sub'] != sub):
                db.rollback()
                flash('Không thể liên kết: tài khoản Google hoặc email đã thuộc tài khoản khác.', 'err')
                return redirect(url_for('core.cai_dat'))
            db.execute('UPDATE teacher SET google_sub=?,email=?,avatar=? WHERE id=?', (sub, email, info.get('picture'), link_uid))
            uid = link_uid
        elif row:
            uid = row['id']
        elif matches:
            db.rollback()
            flash('Email đã có tài khoản. Hãy đăng nhập bằng mật khẩu, vào Cài đặt và chọn Liên kết Google.', 'err')
            return redirect(url_for('auth.login'))
        else:
            base = re.sub(r'[^a-zA-Z0-9_]', '', email.split('@')[0])[:20] or 'giaovien'
            uname, i = base, 1
            while db.execute('SELECT 1 FROM teacher WHERE lower(username)=lower(?)', (uname,)).fetchone():
                i += 1
                uname = f'{base}{i}'
            cur = db.execute('INSERT INTO teacher(username,password,fullname,email,google_sub,avatar,created) VALUES(?,?,?,?,?,?,?)',
                             (uname, '', (info.get('name') or base)[:100], email, sub, info.get('picture'), datetime.date.today().isoformat()))
            uid = cur.lastrowid
        db.commit()
    except sqlite3.Error:
        db.rollback()
        flash('Chưa thể hoàn tất đăng nhập. Vui lòng thử lại.', 'err')
        return redirect(url_for('auth.login'))
    session.clear()
    session['uid'] = uid
    flash('Liên kết Google thành công.' if link_uid else 'Đăng nhập Google thành công.', 'ok')
    return redirect(url_for('core.cai_dat' if link_uid else 'core.dashboard'))


@bp.route('/doi-mat-khau', methods=['POST'])
@login_required
def doi_mk():
    db, user = get_db(), current_user()
    old, new = request.form.get('old', ''), request.form.get('new', '')
    if user['password'] and not check_password_hash(user['password'], old):
        flash('Mật khẩu hiện tại không đúng.', 'err')
    elif not 8 <= len(new) <= 128 or not re.search(r'[^\W\d_]', new, re.UNICODE) or not re.search(r'\d', new):
        flash('Mật khẩu mới cần 8–128 ký tự, gồm cả chữ và số.', 'err')
    elif new != request.form.get('confirm', ''):
        flash('Mật khẩu nhập lại không khớp.', 'err')
    else:
        db.execute('UPDATE teacher SET password=? WHERE id=?', (generate_password_hash(new), user['id']))
        db.commit()
        flash('Đã đổi mật khẩu thành công.', 'ok')
    return redirect(url_for('core.cai_dat'))

import datetime
import ipaddress
import logging
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


LOG = logging.getLogger('eduassist.google')


def _chuan_hoa_base(gia_tri):
    """Nhận 'https://ten-mien' và trả về dạng chuẩn, hoặc '' nếu không hợp lệ.

    Google chỉ chấp nhận địa chỉ chuyển hướng dùng HTTPS + tên miền thật,
    không chấp nhận http:// và cũng không chấp nhận địa chỉ IP.
    """
    gia_tri = (gia_tri or '').strip().rstrip('/')
    if not gia_tri:
        return ''
    try:
        u = urlsplit(gia_tri)
        if u.scheme != 'https' or not u.hostname or u.username or u.password:
            return ''
        if u.query or u.fragment or u.path:
            return ''
        if '.' not in u.hostname:
            return ''
        try:
            ipaddress.ip_address(u.hostname)
            return ''          # Google không nhận địa chỉ IP
        except ValueError:
            pass
        ten = u.hostname.lower()
        if u.port and u.port not in (443, 80):
            ten = '%s:%d' % (ten, u.port)
    except ValueError:
        return ''
    return 'https://' + ten


def base_tu_request():
    """Tự suy ra địa chỉ công khai từ chính request đang xử lý.

    Dùng khi quản trị viên chưa khai 'Địa chỉ website HTTPS' trong Cài đặt.
    Nhờ vậy chỉ cần tên miền đã trỏ về máy chủ và đã bật HTTPS là đăng nhập
    Google chạy được ngay, không phải nhập lại địa chỉ ở hai nơi.
    """
    try:
        if request.scheme != 'https':
            return ''
        return _chuan_hoa_base('https://' + request.host)
    except Exception:
        return ''


def google_base_url():
    """Địa chỉ gốc dùng để dựng redirect URI: ưu tiên giá trị admin đã khai."""
    return _chuan_hoa_base(CFG.get('PUBLIC_BASE_URL', '')) or base_tu_request()


def google_callback_url():
    base = google_base_url()
    return base + '/login/google/callback' if base else ''


def google_bat():
    """Đăng nhập Google đã đủ điều kiện chưa (khoá + tên miền HTTPS)."""
    return bool(CFG.get('GOOGLE_CLIENT_ID') and CFG.get('GOOGLE_CLIENT_SECRET') and google_callback_url())


def google_tinh_trang():
    """Bảng chẩn đoán để hiện trong trang Cài đặt hệ thống."""
    cid, csec = CFG.get('GOOGLE_CLIENT_ID', ''), CFG.get('GOOGLE_CLIENT_SECRET', '')
    base_khai = CFG.get('PUBLIC_BASE_URL', '')
    base = google_base_url()
    return {
        'bat': google_bat(),
        'co_client_id': bool(cid),
        'co_client_secret': bool(csec),
        'co_dia_chi': bool(base),
        'dia_chi_khai_bao': base_khai,
        'dia_chi_dang_dung': base,
        'tu_dong_nhan_dien': bool(base) and not _chuan_hoa_base(base_khai),
        'callback': google_callback_url(),
        'client_id_rut_gon': (cid[:24] + '…') if len(cid) > 24 else cid,
    }


def kiem_tra_google():
    """Thử gọi thẳng tới Google xem máy chủ có kết nối được không.

    Giúp phân biệt lỗi do máy chủ bị chặn mạng với lỗi do khai sai địa chỉ
    chuyển hướng trên Google Cloud.
    """
    tt = google_tinh_trang()
    thieu = []
    if not tt['co_client_id']:
        thieu.append('Google Client ID')
    if not tt['co_client_secret']:
        thieu.append('Google Client Secret')
    if not tt['co_dia_chi']:
        thieu.append('địa chỉ website HTTPS')
    if thieu:
        return False, 'Còn thiếu: ' + ', '.join(thieu) + '.'
    import requests
    try:
        r = requests.get('https://accounts.google.com/.well-known/openid-configuration', timeout=10)
        r.raise_for_status()
        if 'authorization_endpoint' not in r.json():
            return False, 'Google trả về dữ liệu lạ. Vui lòng thử lại.'
    except Exception as e:
        LOG.exception('Không gọi được tới Google')
        return False, 'Máy chủ chưa kết nối được tới Google (%s). Kiểm tra tường lửa/DNS.' % type(e).__name__
    return True, ('Máy chủ kết nối Google tốt. Hãy chắc chắn trên Google Cloud Console đã khai báo '
                  'đúng Authorized redirect URI: %s' % tt['callback'])


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
        if not _chuan_hoa_base(CFG.get('PUBLIC_BASE_URL', '')) and not base_tu_request():
            flash('Đăng nhập Google cần tên miền HTTPS. Google không cho phép dùng địa chỉ IP. '
                  'Hãy trỏ tên miền về máy chủ rồi bật HTTPS, hoặc khai địa chỉ ở Cài đặt hệ thống.', 'err')
        else:
            flash('Đăng nhập Google chưa được bật. Quản trị viên cần nhập Google Client ID và Client Secret '
                  'trong Cài đặt hệ thống.', 'err')
        return redirect(url_for('auth.login'))
    callback = google_callback_url()
    canonical = callback.removesuffix('/login/google/callback')
    if request.url_root.rstrip('/') != canonical:
        return redirect(canonical + '/login/google')
    session['google_link_uid'] = session.get('uid')
    try:
        return get_oauth().google.authorize_redirect(callback, prompt='select_account')
    except Exception:
        LOG.exception('Không tạo được yêu cầu uỷ quyền Google')
        flash('Chưa kết nối được Google. Vui lòng thử lại sau.', 'err')
        return redirect(url_for('auth.login'))


@bp.route('/login/google/callback')
def google_callback():
    if not google_bat():
        return redirect(url_for('auth.login'))
    link_uid = session.pop('google_link_uid', None)
    loi = request.args.get('error')
    if loi:
        LOG.warning('Google trả về lỗi: %s — %s', loi, request.args.get('error_description'))
        flash('Đăng nhập Google bị hủy. Vui lòng thử lại.', 'err')
        return redirect(url_for('auth.login'))
    try:
        token = get_oauth().google.authorize_access_token()
        info = token.get('userinfo') or {}
    except Exception:
        LOG.exception('Đổi mã uỷ quyền Google thất bại (callback=%s)', google_callback_url())
        flash('Không đổi được mã uỷ quyền với Google. Nhờ quản trị viên xem nhật ký máy chủ. '
              'Thường gặp khi địa chỉ chuyển hướng khai báo trên Google Cloud chưa khớp.', 'err')
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
        LOG.exception('Lỗi CSDL khi đăng nhập Google')
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

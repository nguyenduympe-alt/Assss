import os, datetime, secrets
from functools import wraps
from flask import (session, redirect, url_for, g, Blueprint, render_template, request,
                   flash, current_app, abort)
from werkzeug.security import check_password_hash, generate_password_hash
from .db import get_db
from .modules import config as CFG

bp = Blueprint("auth", __name__)


def __getattr__(name):
    """Khoá Google admin sửa được trên web nên phải đọc động."""
    if name == "GOOGLE_CLIENT_ID":
        return CFG.get("GOOGLE_CLIENT_ID", "")
    if name == "GOOGLE_CLIENT_SECRET":
        return CFG.get("GOOGLE_CLIENT_SECRET", "")
    if name == "GOOGLE_ENABLED":
        return bool(CFG.get("GOOGLE_CLIENT_ID") and CFG.get("GOOGLE_CLIENT_SECRET"))
    raise AttributeError(name)


def google_bat():
    """Đăng nhập Google đã cấu hình đủ khoá chưa."""
    return bool(CFG.get("GOOGLE_CLIENT_ID") and CFG.get("GOOGLE_CLIENT_SECRET"))


_oauth = None
_oauth_key = None


def get_oauth():
    """Khởi tạo Authlib OAuth khi cần. Dựng lại nếu admin đổi khoá."""
    global _oauth, _oauth_key
    cid = CFG.get("GOOGLE_CLIENT_ID", "")
    csec = CFG.get("GOOGLE_CLIENT_SECRET", "")
    if not (cid and csec):
        return None
    if _oauth is None or _oauth_key != cid:
        from authlib.integrations.flask_client import OAuth
        o = OAuth(current_app)
        o.register(
            name="google",
            client_id=cid,
            client_secret=csec,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
        _oauth = o
        _oauth_key = cid
    return _oauth


def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get("uid"):
            return redirect(url_for("auth.login", next=request.path))
        return f(*a, **k)
    return w


def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        u = current_user()
        if not u:
            return redirect(url_for("auth.login", next=request.path))
        if u["role"] != "admin":
            abort(403)
        return f(*a, **k)
    return w


def current_user():
    if not session.get("uid"):
        return None
    return get_db().execute("SELECT * FROM teacher WHERE id=?", (session["uid"],)).fetchone()


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("uid"):
        return redirect(url_for("core.dashboard"))
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "")
        row = get_db().execute("SELECT * FROM teacher WHERE username=? OR email=?", (u, u)).fetchone()
        if row and row["password"] and check_password_hash(row["password"], p):
            session["uid"] = row["id"]
            return redirect(request.args.get("next") or url_for("core.dashboard"))
        flash("Sai tài khoản hoặc mật khẩu", "err")
    return render_template("login.html", google_enabled=google_bat())


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/dangky", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        db = get_db()
        u = request.form["username"].strip()
        if db.execute("SELECT 1 FROM teacher WHERE username=?", (u,)).fetchone():
            flash("Tài khoản đã tồn tại", "err")
        else:
            db.execute("""INSERT INTO teacher(username,password,fullname,school,subject,created)
                          VALUES(?,?,?,?,?,?)""",
                       (u, generate_password_hash(request.form["password"]),
                        request.form.get("fullname", ""), request.form.get("school", ""),
                        request.form.get("subject", ""), datetime.date.today().isoformat()))
            db.commit()
            flash("Đăng ký thành công, mời đăng nhập", "ok")
            return redirect(url_for("auth.login"))
    return render_template("register.html", google_enabled=google_bat())


# ---------------- Google OAuth ----------------
@bp.route("/login/google")
def google_login():
    if not google_bat():
        flash("Quản trị viên chưa cấu hình đăng nhập Google.", "err")
        return redirect(url_for("auth.login"))
    o = get_oauth()
    redirect_uri = url_for("auth.google_callback", _external=True)
    if request.headers.get("X-Forwarded-Proto") == "https":
        redirect_uri = redirect_uri.replace("http://", "https://", 1)
    return o.google.authorize_redirect(redirect_uri)


@bp.route("/login/google/callback")
def google_callback():
    if not google_bat():
        return redirect(url_for("auth.login"))
    o = get_oauth()
    try:
        token = o.google.authorize_access_token()
    except Exception as e:
        flash(f"Đăng nhập Google thất bại: {e}", "err")
        return redirect(url_for("auth.login"))
    info = token.get("userinfo") or {}
    sub, email = info.get("sub"), (info.get("email") or "").lower()
    if not email:
        flash("Không lấy được email từ Google.", "err")
        return redirect(url_for("auth.login"))

    db = get_db()
    row = db.execute("SELECT * FROM teacher WHERE google_sub=?", (sub,)).fetchone() \
          or db.execute("SELECT * FROM teacher WHERE email=?", (email,)).fetchone()
    if row:
        db.execute("UPDATE teacher SET google_sub=?, avatar=COALESCE(?,avatar), email=? WHERE id=?",
                   (sub, info.get("picture"), email, row["id"]))
        db.commit()
        session["uid"] = row["id"]
    else:
        base = email.split("@")[0][:20] or "gv"
        uname = base
        i = 1
        while db.execute("SELECT 1 FROM teacher WHERE username=?", (uname,)).fetchone():
            i += 1
            uname = f"{base}{i}"
        cur = db.execute("""INSERT INTO teacher(username,password,fullname,email,google_sub,avatar,created)
                            VALUES(?,?,?,?,?,?,?)""",
                         (uname, "", info.get("name") or base, email, sub,
                          info.get("picture"), datetime.date.today().isoformat()))
        db.commit()
        session["uid"] = cur.lastrowid
        flash("Chào mừng bạn đến với EduAssist! Bạn có 3 lượt tải dùng thử miễn phí.", "ok")
    return redirect(url_for("core.dashboard"))


@bp.route("/doi-mat-khau", methods=["POST"])
@login_required
def doi_mk():
    db = get_db()
    u = current_user()
    old, new = request.form.get("old", ""), request.form.get("new", "")
    if u["password"] and not check_password_hash(u["password"], old):
        flash("Mật khẩu hiện tại không đúng.", "err")
    elif len(new) < 6:
        flash("Mật khẩu mới phải từ 6 ký tự.", "err")
    else:
        db.execute("UPDATE teacher SET password=? WHERE id=?", (generate_password_hash(new), u["id"]))
        db.commit()
        flash("Đã đổi mật khẩu thành công.", "ok")
    return redirect(url_for("core.cai_dat"))

"""Chia sẻ tài liệu giữa các giáo viên.

· GV tải lên Word/PPT/PDF/Excel/file nén ≤ 50MB; trang đầu PDF được render làm
  ảnh đại diện (PyMuPDF), loại khác vẽ bìa mặc định (không có LibreOffice server).
· Người khác tải: 10.000đ/lượt (chuyển khoản SePay tự đối soát) HOẶC dùng 1
  lượt thưởng. Gói VIP 1 năm KHÔNG bao gồm tải tài liệu.
· Mỗi lượt tải của người khác → người chia sẻ được CỘNG 1 lượt tải miễn phí.
· Tải tài liệu của chính mình: miễn phí, không cộng/l trừ gì.
"""
import datetime
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from flask import Blueprint, abort, current_app, flash, redirect, render_template, \
    request, send_file, url_for
from werkzeug.utils import secure_filename

from ..auth import login_required, current_user
from ..db import get_db
from ..modules import billing as BL
from ..modules import sepay as SP
from ..modules import vietqr as VQ

bp = Blueprint("tai_lieu", __name__)

MENU = {"label": "Tài liệu", "endpoint": "tai_lieu.index", "icon": "📁"}

GIA_TAI = 10000                    # giá 1 lượt tải tài liệu (đồng bộ webhook)
MAX_BYTES = 50 * 1024 * 1024       # 50 MB
DUOI_CHO_PHEP = {
    "doc": "Word", "docx": "Word",
    "ppt": "PowerPoint", "pptx": "PowerPoint",
    "xls": "Excel", "xlsx": "Excel",
    "pdf": "PDF",
    "zip": "File nén", "rar": "File nén", "7z": "File nén",
}
NHAN_BIA = {"doc": "WORD", "docx": "WORD", "ppt": "POWERPOINT", "pptx": "POWERPOINT",
            "xls": "EXCEL", "xlsx": "EXCEL", "pdf": "PDF",
            "zip": "FILE NÉN", "rar": "FILE NÉN", "7z": "FILE NÉN"}
MAU_BIA = {"doc": "#2b579a", "docx": "#2b579a", "ppt": "#d24726", "pptx": "#d24726",
           "xls": "#217346", "xlsx": "#217346", "pdf": "#b30b00",
           "zip": "#6d28d9", "rar": "#6d28d9", "7z": "#6d28d9"}


def _thu_muc():
    root = Path(os.environ.get("DB_DIR", "data")) / "tailieu"
    (root / "anh").mkdir(mode=0o755, parents=True, exist_ok=True)
    return root


def ensure_tl(db):
    db.execute("""CREATE TABLE IF NOT EXISTS tai_lieu(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER NOT NULL,
        tieu_de TEXT NOT NULL,
        mo_ta TEXT DEFAULT '',
        mon TEXT DEFAULT '',
        ten_goc TEXT NOT NULL,
        duoi TEXT NOT NULL,
        kich_thuoc INTEGER NOT NULL,
        anh INTEGER DEFAULT 0,
        luot_tai INTEGER DEFAULT 0,
        created TEXT)""")
    db.execute("""CREATE TABLE IF NOT EXISTS tl_quyen(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teacher_id INTEGER NOT NULL,
        tai_lieu_id INTEGER NOT NULL,
        nguon TEXT DEFAULT 'mua',
        created TEXT,
        UNIQUE(teacher_id, tai_lieu_id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS tl_luot(
        teacher_id INTEGER PRIMARY KEY,
        so_luot INTEGER DEFAULT 0)""")
    try:
        db.execute("ALTER TABLE don_hang ADD COLUMN tailieu_id INTEGER")
        db.commit()
    except Exception:  # noqa: BLE001 — cột đã có
        pass


def _luot_thuong(db, uid):
    r = db.execute("SELECT so_luot FROM tl_luot WHERE teacher_id=?", (uid,)).fetchone()
    return int(r["so_luot"] or 0) if r else 0


def _cong_thuong(db, uid, n=1):
    db.execute("""INSERT INTO tl_luot(teacher_id, so_luot) VALUES(?,?)
                  ON CONFLICT(teacher_id) DO UPDATE SET so_luot = so_luot + ?""",
               (uid, n, n))


def _tao_bia_mac_dinh(out, duoi, ten_goc):
    """Vẽ bìa mặc định cho loại không render được (Word/PPT/Excel/nén)."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = 640, 880
    mau = MAU_BIA.get(duoi, "#475569")
    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 210], fill=mau)
    for i, w in ((0, 14), (14, 10), (24, 6)):
        d.rectangle([0, 210, W, 210 + w], fill=mau)
    try:
        f_lon = ImageFont.load_default(size=56)
        f_nho = ImageFont.load_default(size=26)
        f_ten = ImageFont.load_default(size=30)
    except TypeError:  # Pillow cũ
        f_lon = f_nho = f_ten = ImageFont.load_default()
    nhan = NHAN_BIA.get(duoi, duoi.upper())
    w = d.textlength(nhan, font=f_lon)
    d.text(((W - w) / 2, 70), nhan, font=f_lon, fill="#ffffff")
    sub = {"doc": "Tài liệu Word", "docx": "Tài liệu Word", "ppt": "Bài trình chiếu",
           "pptx": "Bài trình chiếu", "xls": "Bảng tính", "xlsx": "Bảng tính",
           "pdf": "Tài liệu PDF", "zip": "Tệp nén", "rar": "Tệp nén", "7z": "Tệp nén"}
    sub_n = sub.get(duoi, "")
    if sub_n:
        w = d.textlength(sub_n, font=f_nho)
        d.text(((W - w) / 2, 146), sub_n, font=f_nho, fill="#ffffff")
    ten = secure_filename(ten_goc or "") or ("tai-lieu." + duoi)
    # bọc tên file tối đa 2 dòng
    line1, line2 = ten, ""
    while d.textlength(line1, font=f_ten) > W - 90 and len(line1) > 12:
        if " " in line1[int(len(line1) * 0.6):]:
            line1, cuoi = line1.rsplit(" ", 1)
            line2 = (cuoi + " " + line2).strip()
        else:
            line1, line2 = line1[:len(line1) - 8] + "…", line2
    d.text((45, 330), line1, font=f_ten, fill="#1e293b")
    if line2:
        d.text((45, 378), line2, font=f_ten, fill="#1e293b")
    d.text((45, H - 120), "Ảnh bìa mặc định — tải về để xem", font=f_nho, fill="#94a3b8")
    d.text((45, H - 82), "nội dung đầy đủ.", font=f_nho, fill="#94a3b8")
    img.save(out, "PNG")


_KHOA_SOFFICE = threading.Lock()   # 1 lượt chuyển đổi cùng lúc — tránh ngốn RAM
SOFFICE = shutil.which("soffice") or shutil.which("libreoffice") or ""


def _pdf_sang_anh(pdf_path, out_path):
    """Render trang đầu của file PDF ra PNG ~700px ngang."""
    import pymupdf
    with pymupdf.open(str(pdf_path)) as doc:
        trang = doc[0]
        pix = trang.get_pixmap(matrix=pymupdf.Matrix(0.9, 0.9), alpha=False)
        if pix.width > 700:
            pix = trang.get_pixmap(matrix=pymupdf.Matrix(700 / pix.width,
                                                         700 / pix.width), alpha=False)
        pix.save(str(out_path))
    return True


def _soffice_sang_pdf(blob, duoi, tmp):
    """Dùng LibreOffice headless chuyển Word/PPT/Excel → PDF (bất đồng bộ, có hạn thời gian).

    Trả đường dẫn PDF trong thư mục tạm `tmp`, hoặc None nếu thất bại.
    """
    if not SOFFICE:
        return None
    src = Path(tmp) / ("tai-lieu." + duoi)
    src.write_bytes(blob)
    env = dict(os.environ, HOME="/tmp", SAL_USE_VCLPLUGIN="svp")
    try:
        with _KHOA_SOFFICE:
            subprocess.run(
                [SOFFICE, "--headless", "--norestore", "--nolockcheck",
                 "-env:UserInstallation=file:///tmp/lo_profile_ea",
                 "--convert-to", "pdf", "--outdir", tmp, str(src)],
                timeout=90, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except subprocess.TimeoutExpired:
        subprocess.run(["pkill", "-f", "soffice"], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return None
    pdf = src.with_suffix(".pdf")
    if pdf.exists() and pdf.stat().st_size > 200:
        return pdf
    return None


def _tao_anh(blob, duoi, out_path, ten_goc):
    """Ảnh đại diện = TRANG ĐẦU TÀI LIỆU: PDF render trực tiếp; Word/PPT/Excel
    chuyển PDF bằng LibreOffice headless trước. Loại khác / lỗi → bìa mặc định.
    Trả 1 nếu render được nội dung, 0 nếu dùng bìa mặc định."""
    try:
        if duoi == "pdf":
            import pymupdf
            with pymupdf.open(stream=blob, filetype="pdf") as doc:
                trang = doc[0]
                pix = trang.get_pixmap(matrix=pymupdf.Matrix(0.9, 0.9), alpha=False)
                if pix.width > 700:
                    pix = trang.get_pixmap(matrix=pymupdf.Matrix(700 / pix.width,
                                                                 700 / pix.width), alpha=False)
                pix.save(str(out_path))
                return 1
        if duoi in ("doc", "docx", "ppt", "pptx", "xls", "xlsx"):
            with tempfile.TemporaryDirectory() as tmp:
                pdf = _soffice_sang_pdf(blob, duoi, tmp)
                if pdf:
                    return 1 if _pdf_sang_anh(pdf, out_path) else 0
    except Exception:  # noqa: BLE001
        current_app.logger.warning("Render trang đầu thất bại: %s", ten_goc)
    _tao_bia_mac_dinh(out_path, duoi, ten_goc)
    return 0


def _tl(id_tl):
    db = get_db()
    r = db.execute("SELECT * FROM tai_lieu WHERE id=?", (id_tl,)).fetchone()
    return db, (dict(r) if r else None)


@bp.route("/tai-lieu")
@login_required
def index():
    db = get_db()
    ensure_tl(db)
    u = current_user()
    q = (request.args.get("q") or "").strip()
    sql = ("SELECT t.*, teacher.fullname, teacher.school, "
           "(SELECT 1 FROM tl_quyen k WHERE k.teacher_id=? AND k.tai_lieu_id=t.id) da_mua "
           "FROM tai_lieu t JOIN teacher ON teacher.id = t.teacher_id ")
    p = [u["id"]]
    if q:
        sql += "WHERE t.tieu_de LIKE ? OR t.mon LIKE ? OR t.mo_ta LIKE ? "
        p += ["%" + q + "%"] * 3
    sql += "ORDER BY t.id DESC LIMIT 200"
    ds = [dict(r) for r in db.execute(sql, p).fetchall()]
    return render_template("tailieu.html", ds=ds, q=q, luot=_luot_thuong(db, u["id"]),
                           gia=GIA_TAI, uid=u["id"])


@bp.route("/tai-lieu/tai-len", methods=["GET", "POST"])
@login_required
def tai_len():
    db = get_db()
    ensure_tl(db)
    u = current_user()
    if request.method == "POST":
        f = request.files.get("file")
        tieu_de = (request.form.get("tieu_de") or "").strip()[:150]
        mo_ta = (request.form.get("mo_ta") or "").strip()[:1000]
        mon = (request.form.get("mon") or "").strip()[:80]
        ten = (f.filename or "") if f else ""
        duoi = ten.rsplit(".", 1)[-1].lower() if "." in ten else ""
        if not tieu_de:
            flash("Hãy nhập tiêu đề tài liệu.", "err")
        elif not ten:
            flash("Hãy chọn tệp để tải lên.", "err")
        elif duoi not in DUOI_CHO_PHEP:
            flash("Chỉ nhận Word (.doc/.docx), PowerPoint (.ppt/.pptx), PDF, "
                  "Excel (.xls/.xlsx) hoặc file nén (.zip/.rar/.7z).", "err")
        else:
            blob = f.read(MAX_BYTES + 1)
            if len(blob) > MAX_BYTES:
                flash("Tệp vượt quá 50 MB.", "err")
            elif len(blob) < 64:
                flash("Tệp rỗng hoặc hỏng.", "err")
            else:
                now = datetime.datetime.now().isoformat(timespec="seconds")
                cur = db.execute(
                    "INSERT INTO tai_lieu(teacher_id,tieu_de,mo_ta,mon,ten_goc,duoi,"
                    "kich_thuoc,anh,created) VALUES(?,?,?,?,?,?,?,?,?)",
                    (u["id"], tieu_de, mo_ta, mon, ten, duoi, len(blob), 0, now))
                db.commit()
                id_tl = cur.lastrowid
                duoi_file = "".join(ch for ch in duoi if ch.isalnum())[:6] or "dat"
                path = _thu_muc() / ("%d.%s" % (id_tl, duoi_file))
                path.write_bytes(blob)
                anh = _tao_anh(blob, duoi, _thu_muc() / "anh" / ("%d.png" % id_tl), ten)
                db.execute("UPDATE tai_lieu SET anh=? WHERE id=?", (anh, id_tl))
                db.commit()
                flash("Đã chia sẻ tài liệu! Mỗi lượt tải của người khác sẽ cộng 1 lượt "
                      "tải miễn phí cho bạn.", "ok")
                return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))
    return render_template("tailieu_len.html")


@bp.route("/tai-lieu/<int:id_tl>")
@login_required
def chi_tiet(id_tl):
    db, tl = _tl(id_tl)
    if not tl:
        abort(404)
    ensure_tl(db)
    u = current_user()
    la_chu = tl["teacher_id"] == u["id"]
    quyen = bool(db.execute("SELECT 1 FROM tl_quyen WHERE teacher_id=? AND tai_lieu_id=?",
                            (u["id"], id_tl)).fetchone())
    don = db.execute(
        "SELECT * FROM don_hang WHERE teacher_id=? AND goi='tailieu' AND tailieu_id=? "
        "AND trang_thai='cho' AND het_han>=? ORDER BY id DESC LIMIT 1",
        (u["id"], id_tl, datetime.datetime.now().isoformat(timespec="seconds"))).fetchone()
    don = dict(don) if don else None
    qr_svg = noi_dung = tk_nhan = None
    if don:
        tk_nhan = SP.so_tk_nhan() or BL.BANK_ACC
        qr_svg = VQ.build_qr(SP.ma_nh() or BL.BANK_CODE, tk_nhan, int(don["so_tien"]),
                             don["ma"], SP.chu_tk())
        noi_dung = don["ma"]
    chu = db.execute("SELECT fullname FROM teacher WHERE id=?", (tl["teacher_id"],)).fetchone()
    return render_template("tailieu_ct.html", tl=tl, la_chu=la_chu, quyen=quyen,
                           luot=_luot_thuong(db, u["id"]), don=don, qr_svg=qr_svg,
                           noi_dung=noi_dung, tk_nhan=tk_nhan, gia=GIA_TAI,
                           chu=(dict(chu) if chu else {}))


@bp.route("/tai-lieu/<int:id_tl>/anh")
@login_required
def anh(id_tl):
    p = _thu_muc() / "anh" / ("%d.png" % id_tl)
    if not p.exists():
        abort(404)
    return send_file(p, mimetype="image/png", max_age=3600)


@bp.route("/tai-lieu/<int:id_tl>/mua")
@login_required
def mua(id_tl):
    db, tl = _tl(id_tl)
    if not tl:
        abort(404)
    ensure_tl(db)
    u = current_user()
    if tl["teacher_id"] == u["id"]:
        return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))
    if db.execute("SELECT 1 FROM tl_quyen WHERE teacher_id=? AND tai_lieu_id=?",
                  (u["id"], id_tl)).fetchone():
        return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))
    now = datetime.datetime.now()
    now_s = now.isoformat(timespec="seconds")
    don = db.execute(
        "SELECT * FROM don_hang WHERE teacher_id=? AND goi='tailieu' AND tailieu_id=? "
        "AND trang_thai='cho' AND het_han>=?", (u["id"], id_tl, now_s)).fetchone()
    if not don:
        from ..modules.sepay import _tao_ma
        ma = _tao_ma(db)
        het = (now + datetime.timedelta(hours=24)).isoformat(timespec="seconds")
        db.execute("INSERT INTO don_hang(ma,teacher_id,goi,so_tien,trang_thai,het_han,created,tailieu_id) "
                   "VALUES(?,?,?,?,?,?,?,?)",
                   (ma, u["id"], "tailieu", GIA_TAI, "cho", het, now_s, id_tl))
        db.commit()
    return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))


@bp.route("/tai-lieu/<int:id_tl>/trang-thai")
@login_required
def trang_thai(id_tl):
    db, tl = _tl(id_tl)
    if not tl:
        abort(404)
    u = current_user()
    don = db.execute(
        "SELECT ma, trang_thai FROM don_hang WHERE teacher_id=? AND goi='tailieu' AND "
        "tailieu_id=? ORDER BY id DESC LIMIT 1", (u["id"], id_tl)).fetchone()
    quyen = bool(db.execute("SELECT 1 FROM tl_quyen WHERE teacher_id=? AND tai_lieu_id=?",
                            (u["id"], id_tl)).fetchone())
    return {"quyen": quyen, "don": (dict(don) if don else None)}


@bp.route("/tai-lieu/<int:id_tl>/dung-luot", methods=["POST"])
@login_required
def dung_luot(id_tl):
    db, tl = _tl(id_tl)
    if not tl:
        abort(404)
    u = current_user()
    if tl["teacher_id"] == u["id"] or db.execute(
            "SELECT 1 FROM tl_quyen WHERE teacher_id=? AND tai_lieu_id=?",
            (u["id"], id_tl)).fetchone():
        return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))
    if _luot_thuong(db, u["id"]) <= 0:
        flash("Bạn chưa có lượt tải miễn phí nào — hãy chia sẻ tài liệu để nhận lượt, "
              "hoặc thanh toán 10.000₫ để tải tài liệu này.", "err")
        return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))
    db.execute("UPDATE tl_luot SET so_luot = so_luot - 1 WHERE teacher_id=? AND so_luot>0",
               (u["id"],))
    if db.execute("SELECT changes()").fetchone()[0] != 1:
        db.rollback()
        flash("Không dùng được lượt — thử lại.", "err")
        return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))
    db.execute("INSERT OR IGNORE INTO tl_quyen(teacher_id,tai_lieu_id,nguon,created) "
               "VALUES(?,?,?,?)",
               (u["id"], id_tl, "thuong",
                datetime.datetime.now().isoformat(timespec="seconds")))
    db.commit()
    flash("Đã dùng 1 lượt miễn phí — tài liệu được mở khoá vĩnh viễn.", "ok")
    return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))


@bp.route("/tai-lieu/<int:id_tl>/tai")
@login_required
def tai_ve(id_tl):
    db, tl = _tl(id_tl)
    if not tl:
        abort(404)
    u = current_user()
    la_chu = tl["teacher_id"] == u["id"]
    quyen = db.execute("SELECT nguon FROM tl_quyen WHERE teacher_id=? AND tai_lieu_id=?",
                       (u["id"], id_tl)).fetchone()
    if not la_chu and not quyen:
        flash("Tài liệu này chưa mở khoá — thanh toán 10.000₫ hoặc dùng 1 lượt miễn phí.",
              "err")
        return redirect(url_for("tai_lieu.chi_tiet", id_tl=id_tl))
    duoi_an_toan = re.sub(r"[^A-Za-z0-9]", "", str(tl["duoi"]))[:6] or "dat"
    path = _thu_muc() / ("%d.%s" % (id_tl, duoi_an_toan))
    if not path.exists():
        abort(404)
    if not la_chu:
        nguon = quyen["nguon"] or "mua"
        db.execute("UPDATE tai_lieu SET luot_tai = COALESCE(luot_tai,0) + 1 WHERE id=?",
                   (id_tl,))
        _cong_thuong(db, tl["teacher_id"], 1)   # người chia sẻ +1 lượt tải miễn phí
        db.execute("INSERT INTO usage_log(teacher_id,kind,detail,created) VALUES(?,?,?,?)",
                   (u["id"], "tailieu",
                    ("Tải #%d bằng lượt %s" % (id_tl, nguon))[:280],
                    datetime.datetime.now().isoformat(timespec="seconds")))
        db.commit()
    ten = secure_filename(tl["ten_goc"]) or ("tai-lieu." + tl["duoi"])
    return send_file(path, as_attachment=True, download_name=ten)

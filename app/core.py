import io, json, datetime, csv, re, os, time, uuid
from flask import (Blueprint, render_template, request, redirect, url_for, session,
                   send_file, send_from_directory, jsonify, flash, Response, make_response)
from .db import get_db, setting, set_setting
from .auth import (login_required, current_user, admin_required, google_bat,
                    google_callback_url, google_tinh_trang, kiem_tra_google)
from .modules import ai_nhanxet as AI
from .modules import excel_io as XL
from .modules import khdh_kho as KHO
from .modules.pdf_bao_giang import build_pdf, THU_NAME
from .modules.word_bao_giang import build_docx
from .modules import billing as BL
from .modules import mon_day as MD
from .modules import ppct_tach as PT
from .modules import mon_hoc as MH
from .modules import tkb_phien as TP
from .modules import vietqr as VQ
from .modules import lichnghi as LN
from .modules import sms as SMS
from .modules import hoa_don as HD
from .modules import bank_webhook as BW
from .modules import config as CFG

bp = Blueprint("core", __name__)

def _cong_cu():
    """Danh sách công cụ hiển thị ở mục “Công cụ” trên trang chủ.

    Chỉ hiện công cụ nào thật sự có endpoint — plugin có thể không được cài, khi đó
    trang chủ vẫn chạy bình thường chứ không lỗi.
    """
    ds = [
        {"icon": "📝", "ten": "Giáo án & năng lực số", "endpoint": "giao_an_nls.index", "mau": "#0d9488",
         "mo_ta": "Tải giáo án Word → tích chọn nội dung cần chèn → duyệt → tải bản .docx",
         "the": [], "moi": False},
        {"icon": "🤖", "ten": "Nhận xét AI", "endpoint": "core.nhan_xet", "mau": "#059669",
         "mo_ta": "Nhập điểm cho lớp → tạo nhận xét → xuất file Excel",
         "the": [], "moi": False},
        {"icon": "🔤", "ten": "Kiểm tra chính tả", "endpoint": "chinh_ta.index", "mau": "#06b6d4",
         "mo_ta": "Tải .docx hoặc dán văn bản → duyệt từng chỗ sửa → tải bản .docx",
         "the": [], "moi": False},
        {"icon": "🧩", "ten": "KHDH + NLS + AI + STEM", "endpoint": "digital.index", "mau": "#8b5cf6",
         "mo_ta": "Tải KHDH (kế hoạch dạy học) / giáo án Word → đọc tựa bài → chọn bài cần tích hợp "
                  "năng lực số, AI, STEM → tải bản .docx",
         "the": [], "moi": False},
        {"icon": "🖨️", "ten": "Lịch báo giảng", "endpoint": "core.bao_giang", "mau": "#f59e0b",
         "mo_ta": "Xuất lịch báo giảng ra PDF hoặc Word",
         "the": [], "moi": False},
        {"icon": "📚", "ten": "Quản lý môn học", "endpoint": "core.mon_hoc", "mau": "#0d9488",
         "mo_ta": "Gom mọi môn + khối về một chỗ: nhập / xem / sửa phân phối chương trình ngay trong từng môn",
         "the": [], "moi": False},
        {"icon": "🗓️", "ten": "Thời khoá biểu", "endpoint": "core.tkb", "mau": "#6366f1",
         "mo_ta": "Xếp thời khoá biểu theo buổi, tiết, phòng học",
         "the": [], "moi": False},
        {"icon": "🎋", "ten": "Lịch nghỉ", "endpoint": "core.lich_nghi", "mau": "#ec4899",
         "mo_ta": "Nhập ngày nghỉ để tính đúng số tuần thực dạy",
         "the": [], "moi": False},
    ]
    # Công cụ do plugin đăng ký: chỉ kèm đúng một câu hướng dẫn dùng.
    HUONG_DAN = {"check_ai.index": "Tải .docx/.pdf hoặc dán văn bản → xem điểm dấu hiệu và lý do",
                 "trung_lap.index": ("Dán/tải bài → đối chiếu kho của thầy/cô, đối chiếu nguồn "
                                     "Internet và so nhiều bài nộp với nhau")}
    from flask import current_app
    co = set(current_app.view_functions)
    for m in (current_app.jinja_env.globals.get("PLUGIN_MENUS") or []):
        ep = m.get("endpoint")
        if ep and ep not in {x["endpoint"] for x in ds}:
            ds.append({"icon": m.get("icon") or "🧩", "ten": m.get("label") or "Tính năng",
                       "endpoint": ep, "mau": "#64748b", "mo_ta": HUONG_DAN.get(ep, ""),
                       "the": [], "moi": False})
    return [x for x in ds if x["endpoint"] in co]


def _trang_thai_ai():
    """Trạng thái trợ lý AI: mô hình đang chạy + việc học từ quyết định của giáo viên.

    Bọc kỹ trong try/except: thiếu tệp mô hình hay thiếu bảng cũng không được làm
    trang chủ lỗi — khi đó trả về None và giao diện tự ẩn phần này.
    """
    out = {}
    try:
        from .modules import ml_noi_bo as ML
        out["mo_hinh"] = ML.thong_tin()
    except Exception:
        out["mo_hinh"] = {}
    try:
        from .modules import hoc_tu_nguoi_dung as HOC
        out["hoc"] = HOC.thong_ke()
    except Exception:
        out["hoc"] = None
    from flask import current_app
    # Nút bật/tắt việc học: nay nằm ở công cụ CHÍNH TẢ (đã tách riêng khỏi giáo án).
    # Vẫn nhận tên cũ để không vỡ nếu bản triển khai nào chưa cập nhật.
    out["co_toggle"] = any(ep in current_app.view_functions
                           for ep in ("chinh_ta.bat_tat_hoc", "giao_an_nls.bat_tat_hoc"))
    return out if (out["mo_hinh"] or out["hoc"]) else None




@bp.app_context_processor
def inject():
    u = current_user()
    return {"user": u, "THU_NAME": THU_NAME, "PROVIDERS": AI.PROVIDERS,
            "timedelta": datetime.timedelta,
            "now": datetime.date.today(), "BL": BL,
            "is_pro": BL.is_pro(u), "remaining": BL.remaining(u),
            "days_left": BL.days_left(u), "FREE_QUOTA": BL.FREE_QUOTA,
            "CFG": CFG, "google_enabled": google_bat(), "google_callback_url": google_callback_url(),
            "SITE_NAME": CFG.get("SITE_NAME", "EduAssist"),
            "SITE_TAGLINE": CFG.get("SITE_TAGLINE", "Trợ lý giáo viên"),
            "SITE_LOGO": CFG.get("SITE_LOGO", "🎓"),
            "so_viec_admin": _viec_admin(u),
            "canh_bao_mk": _mk_mac_dinh(u),
            # (M17) danh sách môn dạy của giáo viên + gợi ý môn phổ thông
            "mon_day": MD.danh_sach(u), "GOI_Y_MON": MD.GOI_Y}


def _mk_mac_dinh(u):
    """Cảnh báo nếu admin vẫn dùng mật khẩu demo 123456."""
    try:
        from werkzeug.security import check_password_hash
        return bool(u and u["role"] == "admin" and u["username"] == "gv"
                    and check_password_hash(u["password"], "123456"))
    except Exception:
        return False


def _viec_admin(u):
    """Đếm việc tồn đọng để chấm badge đỏ cạnh menu Quản trị."""
    try:
        if not u or u["role"] != "admin":
            return 0
        db = get_db()
        n = db.execute("SELECT COUNT(*) c FROM bank_tx WHERE trang_thai='cho_doi_soat'").fetchone()["c"]
        n += db.execute("SELECT COUNT(*) c FROM sms_log WHERE ok=0").fetchone()["c"]
        return n
    except Exception:
        return 0


@bp.route("/")
@login_required
def dashboard():
    db, uid = get_db(), session["uid"]
    n = lambda q: db.execute(q, (uid,)).fetchone()[0]
    stats = {
        "ppct": n("SELECT COUNT(*) FROM ppct WHERE teacher_id=?"),
        "tkb": n("SELECT COUNT(*) FROM tkb WHERE teacher_id=?"),
        "dg": n("SELECT COUNT(*) FROM danhgia WHERE teacher_id=?"),
        "lop": n("SELECT COUNT(DISTINCT lop) FROM tkb WHERE teacher_id=?"),
        "hs": n("SELECT COUNT(DISTINCT ho_ten) FROM danhgia WHERE teacher_id=?"),
        "tuan": n("SELECT COUNT(DISTINCT tuan) FROM ppct WHERE teacher_id=?"),
    }
    rows = db.execute("SELECT * FROM danhgia WHERE teacher_id=?", (uid,)).fetchall()
    # phan bo muc do
    dist = {"HTT": 0, "HT": 0, "CHT": 0}
    diems = []
    for r in rows:
        if r["muc_do"] in dist:
            dist[r["muc_do"]] += 1
        if r["diem"] is not None:
            diems.append(r["diem"])
    tong = sum(dist.values()) or 1
    donut = []
    colors = {"HTT": "#059669", "HT": "#06b6d4", "CHT": "#f43f5e"}
    labels = {"HTT": "Hoàn thành tốt", "HT": "Hoàn thành", "CHT": "Chưa hoàn thành"}
    off = 0.0
    for k in ("HTT", "HT", "CHT"):
        pct = dist[k] * 100.0 / tong
        donut.append({"k": k, "n": dist[k], "pct": round(pct, 1), "off": round(off, 2),
                      "color": colors[k], "label": labels[k]})
        off += pct

    # pho diem (histogram theo khoang 1 diem)
    bins = [0] * 10
    for d in diems:
        i = min(9, max(0, int(d)))
        if d == 10: i = 9
        bins[i] += 1
    mx = max(bins) or 1
    hist = [{"lab": f"{i}-{i+1}", "n": c, "h": round(c * 100.0 / mx, 1)} for i, c in enumerate(bins)]
    avg = round(sum(diems) / len(diems), 2) if diems else 0

    # theo lop
    per = {}
    for r in rows:
        d = per.setdefault(r["lop"] or "(chưa rõ)", {"lop": r["lop"] or "(chưa rõ)", "total": 0,
                                                     "HTT": 0, "HT": 0, "CHT": 0, "sum": 0, "n": 0})
        d["total"] += 1
        if r["muc_do"] in d: d[r["muc_do"]] += 1
        if r["diem"] is not None:
            d["sum"] += r["diem"]; d["n"] += 1
    per_lop = []
    for d in per.values():
        d["avg"] = round(d["sum"] / d["n"], 2) if d["n"] else None
        d["rate"] = round((d["HTT"] + d["HT"]) * 100.0 / d["total"], 1) if d["total"] else 0
        for k in ("HTT", "HT", "CHT"):
            d[k + "p"] = round(d[k] * 100.0 / d["total"], 1) if d["total"] else 0
        per_lop.append(d)
    per_lop.sort(key=lambda x: -x["total"])

    # tien do PPCT theo tuan (sparkline)
    tw = db.execute("SELECT tuan, COUNT(*) c FROM ppct WHERE teacher_id=? GROUP BY tuan ORDER BY tuan", (uid,)).fetchall()
    spark = [{"x": r["tuan"], "y": r["c"]} for r in tw]
    smax = max([p["y"] for p in spark] or [1])
    pts = ""
    if len(spark) > 1:
        step = 100.0 / (len(spark) - 1)
        pts = " ".join(f"{round(i*step,2)},{round(40 - p['y']*36.0/smax,2)}" for i, p in enumerate(spark))
    elif spark:
        # (M31) sửa lỗi cũ: PPCT chỉ có MỘT tuần làm trang tổng quan báo lỗi (thiếu tham số định dạng)
        y1 = round(40 - spark[0]["y"] * 36.0 / smax, 2)
        pts = "0,%s 100,%s" % (y1, y1)

    # TKB hom nay
    today = datetime.date.today()
    thu = today.weekday() + 2
    hom_nay = db.execute("SELECT * FROM tkb WHERE teacher_id=? AND thu=? ORDER BY buoi DESC, tiet", (uid, thu)).fetchall()
    tiet_tuan = db.execute("SELECT thu, COUNT(*) c FROM tkb WHERE teacher_id=? GROUP BY thu", (uid,)).fetchall()
    load = {r["thu"]: r["c"] for r in tiet_tuan}
    lmax = max(list(load.values()) or [1])
    recent = db.execute("SELECT * FROM danhgia WHERE teacher_id=? ORDER BY id DESC LIMIT 6", (uid,)).fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent, donut=donut, tong=sum(dist.values()),
                           cong_cu=_cong_cu(), ai=_trang_thai_ai(),
                           hist=hist, avg=avg, per_lop=per_lop, spark=spark, pts=pts, smax=smax,
                           hom_nay=hom_nay, load=load, lmax=lmax, today=today, thu=thu, dist=dist)


# ---------------- PPCT ----------------
# ---------------- (M31) Quản lý môn học ----------------
@bp.route("/mon-hoc", methods=["GET", "POST"])
@login_required
def mon_hoc():
    """Gom mọi môn + khối về một trang: nhập / xem / sửa PPCT ngay trong từng môn."""
    db, uid, u = get_db(), session["uid"], current_user()
    ket_qua_nhap = None
    if request.method == "POST":
        act = request.form.get("act")
        mon = (request.form.get("mon") or "").strip()
        khoi = (request.form.get("khoi") or "").strip()
        if act == "them":
            ok, tb = MH.them_mon(db, uid, request.form.get("mon_moi") or "", request.form.get("khoi_moi") or "")
            flash(tb, "ok" if ok else "err")
        elif act == "sua":
            ok, tb = MH.doi_ten(db, uid, mon, khoi, request.form.get("mon_moi") or "",
                                request.form.get("khoi_moi") or "")
            flash(tb, "ok" if ok else "err")
        elif act == "xoa":
            ok, tb = MH.xoa_mon(db, uid, mon, khoi,
                                xoa_ppct=bool(request.form.get("xoa_ppct")),
                                xoa_tkb=bool(request.form.get("xoa_tkb")),
                                xoa_kho=bool(request.form.get("xoa_kho")),
                                bo_danh_sach=bool(request.form.get("bo_danh_sach")))
            flash(tb, "ok" if ok else "err")
        elif act == "chinh":
            ok, tb = MH.dat_chinh(db, uid, mon)
            flash(tb, "ok" if ok else "err")
        elif act == "them_dong":
            ok, tb = MH.them_dong(db, uid, mon, khoi or (request.form.get("khoi_moi") or ""),
                                  request.form.get("tuan"), request.form.get("tiet_pp"),
                                  request.form.get("ten_bai"), request.form.get("ghi_chu"))
            flash(_tb_lbg_ppct(tb, ok, request.form.get("tuan")), "ok" if ok else "err")
        elif act == "sua_dong":
            ok, tb = MH.sua_dong(db, uid, request.form.get("id"),
                                 request.form.get("tuan"), request.form.get("tiet_pp"),
                                 request.form.get("ten_bai"), request.form.get("ghi_chu"))
            flash(_tb_lbg_ppct(tb, ok, request.form.get("tuan")), "ok" if ok else "err")
        elif act == "xoa_dong":
            ok, tb = MH.xoa_dong(db, uid, request.form.get("id"))
            flash(_tb_lbg_ppct(tb, ok), "ok" if ok else "err")
        elif act == "xoa_ppct":
            ok, tb, _n = MH.xoa_ppct(db, uid, mon, khoi)
            flash(_tb_lbg_ppct(tb, ok), "ok" if ok else "err")
        elif act == "tiet_tuan":
            khoi = khoi or (request.form.get("khoi_moi") or "").strip()
            ok, tb = KHO.dat_tiet_tuan_mon(db, uid, mon, khoi, request.form.get("so_tiet_tuan"))
            flash(tb, "ok" if ok else "err")
        elif act == "ppct":
            ds_tep = [f for f in (request.files.getlist("files") + request.files.getlist("file"))
                      if (getattr(f, "filename", "") or "").strip()]
            khoi = khoi or (request.form.get("khoi_moi") or "").strip()
            if not mon or khoi not in KHO.KHOI:
                flash("Nhập PPCT cho một môn cần có MÔN và KHỐI — thầy/cô chọn khối rồi thử lại.", "err")
            elif not ds_tep:
                flash("Vui lòng chọn tệp phân phối chương trình (.docx, .xlsx hoặc .csv).", "err")
            elif len(ds_tep) > MH.TOI_DA_TEP:
                flash("Mỗi lượt nhập tối đa %d tệp." % MH.TOI_DA_TEP, "err")
            else:
                thay_cu = (request.form.get("thay_cu") or "").lower() in ("1", "on", "true", "yes")
                n_cu = MH.dem_ppct(db, uid, mon, khoi)
                if n_cu and not thay_cu:
                    flash("Môn %s khối %s đã có %d dòng PPCT. Xác nhận xoá cái cũ rồi nhập bản mới "
                          "(hệ thống sẽ hỏi trước khi xoá)." % (mon, khoi, n_cu), "err")
                else:
                    ds_mon = MD.danh_sach(u)
                    ket_qua, so_dong, so_loi = MH.nhap_ppct(db, uid, ds_tep, mon, khoi, thay_cu=thay_cu,
                                                            ds_mon=ds_mon)
                    MD.them(db, uid, mon)
                    if so_dong:
                        flash("Đã nhập %d dòng PPCT cho môn %s khối %s%s — xem nội dung ngay dưới đây."
                              " Lịch báo giảng tự làm mới theo PPCT vừa lưu."
                              % (so_dong, mon, khoi,
                                 " (đã xoá PPCT cũ rồi nhập bản mới)" if (thay_cu and n_cu) else ""),
                              "err" if so_loi else "ok")
                    elif so_loi:
                        flash("Chưa nhập được dòng nào — xem lý do ngay dưới đây. Dữ liệu PPCT cũ vẫn còn.", "err")
                        ket_qua_nhap = ket_qua
                    else:
                        flash("Tệp không có dòng bài học nào — dữ liệu PPCT cũ vẫn còn.", "err")
                        ket_qua_nhap = ket_qua
        if ket_qua_nhap is None:
            slug = (request.form.get("slug") or "").strip()
            return redirect(url_for("core.mon_hoc") + (("#" + slug) if slug else ""))

    ds = MH.liet_ke(db, uid, u)
    for d in ds:
        d["ppct"] = MH.dong_ppct(db, uid, d["mon"], d["khoi"])
    return render_template("monhoc.html", ds=ds, tk=MH.thong_ke(ds), KHOI=KHO.KHOI,
                           mon_chinh=MD.mon_chinh(u), TOI_DA_MON=MD.TOI_DA_MON,
                           ket_qua_nhap=ket_qua_nhap,
                           mon_loc=(request.args.get("mon") or "").strip(),
                           khoi_loc=(request.args.get("khoi") or "").strip())


@bp.route("/ppct", methods=["GET", "POST"])
@login_required
def ppct():
    """Liên kết cũ: GET đưa về Quản lý môn; POST (thêm/xoá/nhập) vẫn nhận rồi đưa về đó."""
    db, uid = get_db(), session["uid"]
    if request.method != "POST":
        kw = {}
        if request.args.get("mon"):
            kw["mon"] = request.args.get("mon")
        if request.args.get("khoi"):
            kw["khoi"] = request.args.get("khoi")
        return redirect(url_for("core.mon_hoc", **kw))
    if request.method == "POST":
        act = request.form.get("act")
        if act == "add":
            db.execute("INSERT INTO ppct(teacher_id,khoi,mon,tuan,tiet_pp,ten_bai,ghi_chu) VALUES(?,?,?,?,?,?,?)",
                       (uid, request.form.get("khoi"), request.form.get("mon"),
                        request.form.get("tuan") or 1, request.form.get("tiet_pp") or 0,
                        request.form.get("ten_bai"), request.form.get("ghi_chu")))
        elif act == "del":
            db.execute("DELETE FROM ppct WHERE id=? AND teacher_id=?", (request.form["id"], uid))
        elif act == "import":
            # (M29) nhập PPCT cho NHIỀU MÔN + NHIỀU KHỐI: nhiều tệp một lần, hoặc một tệp có nhiều phần
            ds_tep = [f for f in (request.files.getlist("file") + request.files.getlist("files"))
                      if (getattr(f, "filename", "") or "").strip()]
            mon_o = (request.form.get("mon") or "").strip()
            khoi_o = (request.form.get("khoi") or "").strip()
            xoa_cu = (request.form.get("xoa_cu") or "").lower() in ("1", "on", "true", "yes")
            if not ds_tep:
                flash("Vui lòng chọn tệp PPCT (.docx, .xlsx hoặc .csv).", "err")
                return redirect(url_for("core.ppct"))
            if len(ds_tep) > 25:
                flash("Mỗi lượt nhập tối đa 25 tệp. Thầy/cô chia thành các lượt nhỏ hơn.", "err")
                return redirect(url_for("core.ppct"))
            if khoi_o and khoi_o not in KHO.KHOI:
                flash("Khối phải từ 1 đến 12.", "err")
                return redirect(url_for("core.ppct"))
            if len(mon_o) > 100:
                flash("Tên môn quá dài.", "err")
                return redirect(url_for("core.ppct"))
            ds_mon = MD.danh_sach(current_user())
            ket_qua, so_dong, so_loi, da_xoa, phan_ok = [], 0, 0, set(), []
            for f in ds_tep:
                ten_tep = (f.filename or "")[:200]
                dong_tep = {"ten": ten_tep, "phan": [], "loi": "", "so_dong": 0}
                try:
                    data = f.read(8 * 1024 * 1024 + 1)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError("Tệp lớn hơn 8 MB — hãy lưu gọn lại rồi thử lại.")
                    ds_phan = PT.tach(data, ten_tep, ds_mon, mon_o, khoi_o)
                except ValueError as exc:
                    dong_tep["loi"] = str(exc)
                except Exception:
                    dong_tep["loi"] = "Không đọc được tệp này (hãy lưu lại .docx / .xlsx rồi thử lại)."
                else:
                    if not ds_phan:
                        dong_tep["loi"] = ("Không thấy bảng phân phối chương trình. Tệp cần có bảng với cột"
                                           " “Tên bài dạy” (hoặc các dòng bắt đầu bằng “Bài 1…”).")
                    for ph in ds_phan:
                        if not ph["mon"]:
                            ph["loi"] = ("chưa rõ MÔN — ghi tên môn vào tệp (vd “MÔN: TOÁN — LỚP 6”), hoặc"
                                         " điền ô Môn ở trên, hoặc đặt tên tệp có tên môn")
                        elif ph["khoi"] not in KHO.KHOI:
                            ph["loi"] = ("chưa rõ KHỐI — ghi khối vào tệp (vd “LỚP 6”), hoặc chọn ô Khối,"
                                         " hoặc đặt tên tệp có khối")
                        else:
                            m, k = ph["mon"], ph["khoi"]
                            if xoa_cu and (MD.bo_dau(m), k) not in da_xoa:
                                db.execute("DELETE FROM ppct WHERE teacher_id=? AND khoi=? AND lower(mon)=lower(?)",
                                           (uid, k, m))
                                da_xoa.add((MD.bo_dau(m), k))
                            for d in ph["rows"]:
                                db.execute("INSERT INTO ppct(teacher_id,khoi,mon,tuan,tiet_pp,ten_bai,ghi_chu)"
                                           " VALUES(?,?,?,?,?,?,?)",
                                           (uid, k, m, d.get("tuan") or 1, d.get("tiet_pp"),
                                            d.get("ten_bai"), PT.ghi_chu_ppct(d) or None))
                            ph["loi"] = ""
                            phan_ok.append(ph)
                            dong_tep["so_dong"] += len(ph["rows"])
                            so_dong += len(ph["rows"])
                            if len(ph["rows"]) == 0:
                                ph["loi"] = "phần này không có dòng bài học nào"
                        dong_tep["phan"].append(ph)
                        if ph.get("loi"):
                            so_loi += 1
                if dong_tep["loi"]:
                    so_loi += 1
                ket_qua.append(dong_tep)
                if len(ds_tep) == 1 and not dong_tep["loi"] and len(dong_tep["phan"]) == 1:
                    ph = dong_tep["phan"][0]
                    if not ph.get("loi"):
                        flash("Đã nhập %d dòng PPCT — môn %s khối %s."
                              % (dong_tep["so_dong"], ph["mon"], ph["khoi"]), "ok")
                        db.commit()
                        return redirect(url_for("core.ppct"))
            db.commit()
            if so_dong:
                flash("Đã nhập %d dòng PPCT — %s%s."
                      % (so_dong, PT.tom_tat(phan_ok) or ("%d phần" % len(phan_ok)),
                         " · một số phần chưa nhập được, xem bảng bên dưới" if so_loi else ""),
                      "err" if so_loi and not so_dong else "ok")
            elif so_loi:
                flash("Chưa nhập được dòng nào — xem lý do ở bảng bên dưới.", "err")
            return render_template("ppct_import_kq.html", ket_qua=ket_qua, so_dong=so_dong,
                                   so_loi=so_loi, xoa_cu=xoa_cu, mon_day=ds_mon)
        db.commit()
        return redirect(url_for("core.mon_hoc"))
    tuan = request.args.get("tuan", "")
    mon_loc = (request.args.get("mon") or "").strip()
    khoi_loc = (request.args.get("khoi") or "").strip()
    q = "SELECT * FROM ppct WHERE teacher_id=?"
    p = [uid]
    if tuan:
        q += " AND tuan=?"; p.append(tuan)
    if mon_loc:
        q += " AND lower(mon)=lower(?)"; p.append(mon_loc)
    if khoi_loc:
        q += " AND COALESCE(khoi,'')=?"; p.append(khoi_loc)
    rows = db.execute(q + " ORDER BY tuan, mon, tiet_pp", p).fetchall()
    tuans = [r[0] for r in db.execute("SELECT DISTINCT tuan FROM ppct WHERE teacher_id=? ORDER BY tuan", (uid,))]
    ds_mon_hoc = MH.liet_ke(db, uid, current_user())
    return render_template("ppct.html", rows=rows, tuan=tuan, tuans=tuans, mon_hoc=ds_mon_hoc,
                           mon_loc=mon_loc, khoi_loc=khoi_loc)


# ---------------- TKB ----------------
def _tkb_mon_khoi():
    """(M30) Đọc môn + khối từ ô chọn — dùng chung cho thêm mới và SỬA tiết dạy."""
    db, uid = get_db(), session["uid"]
    mon = (request.form.get("mon") or "").strip()
    khoi = (request.form.get("khoi") or "").strip()
    if mon == "__khac":
        mon = (request.form.get("mon_moi") or "").strip()
        khoi = (request.form.get("khoi_moi") or "").strip()
        if mon and khoi in KHO.KHOI:
            KHO.tao_mon(db, uid, mon, khoi)      # ghi nhận môn mới (chưa có KHDH)
            MD.them(db, uid, mon)                # (M30) vào luôn danh sách MÔN DẠY
        else:
            return "", "", "Vui lòng chọn môn đã tạo, hoặc nhập tên môn mới kèm khối (1–12)."
    elif "|" in mon:
        mon, _, khoi = mon.partition("|")
        mon, khoi = mon.strip(), khoi.strip()
    if not mon:
        return "", "", "Vui lòng chọn môn đã tạo trong kho KHDH, hoặc nhập môn mới kèm khối."
    return mon, khoi, ""


def _tkb_doc_form():
    """(M30) Đọc + kiểm tra các ô của một tiết dạy. Trả về (dt, loi)."""
    dt = {"thu": (request.form.get("thu") or "").strip(),
          "buoi": (request.form.get("buoi") or "").strip(),
          "tiet": (request.form.get("tiet") or "").strip(),
          "lop": (request.form.get("lop") or "").strip()[:60],
          "phong": (request.form.get("phong") or "").strip()[:120]}
    if not (dt["thu"].isdigit() and 2 <= int(dt["thu"]) <= 8):
        return dt, "Thứ phải từ Thứ Hai đến Chủ nhật."
    if dt["buoi"] not in ("Sáng", "Chiều"):
        return dt, "Buổi phải là Sáng hoặc Chiều."
    if not (dt["tiet"].isdigit() and 1 <= int(dt["tiet"]) <= 10):
        return dt, "Tiết phải là số từ 1 đến 10."
    if not dt["lop"]:
        return dt, "Vui lòng nhập lớp dạy (ví dụ 5A)."
    return dt, ""


def _tkb_nho_tkb(dt):
    """(M30) Nhớ THỨ + BUỔI vừa dùng để lần thêm sau không phải chọn lại."""
    session["tkb_thu"], session["tkb_buoi"] = dt["thu"], dt["buoi"]


def _nam_hoc_gv(u):
    s = setting("tuan1_%s" % u["id"], "")
    try:
        d = datetime.date.fromisoformat(s) if s else datetime.date.today()
    except Exception:
        d = datetime.date.today()
    return TP.nam_hoc_tu_ngay(d)


def _tuan_xem():
    try:
        return max(1, int(request.values.get("tuan") or 1))
    except Exception:
        return 1


def _tkb_tb_moc(v, moc0):
    """Câu thêm vào thông báo khi thêm/sửa TKB — nói rõ bản cũ được giữ."""
    if v not in moc0 and v > 1:
        return (" Bản cũ giữ đến hết tuần %d; bản này áp dụng từ tuần %d đến lần đổi tiếp theo."
                % (v - 1, v))
    return " Áp dụng từ tuần %d." % v


def _tuan1_gv(u, db):
    s = setting("tuan1_%s" % u["id"], "")
    if s:
        try:
            return datetime.date.fromisoformat(s), True
        except Exception:
            pass
    t = datetime.date.today()
    return t - datetime.timedelta(days=t.weekday()), False


def _tkb_dong_phien(db, uid, r, nam, tuan):
    """Tìm đúng dòng của phiên bản hiệu lực tại `tuan` (sao chép nếu đang đứng giữa hai mốc)."""
    v = TP.dam_bao_phien(db, uid, nam, tuan)
    if r and int(r["tuan_bd"] or 1) == v and (r["nam_hoc"] or nam) == nam:
        return r, v
    r2 = db.execute("SELECT * FROM tkb WHERE teacher_id=? AND COALESCE(nam_hoc,'')=?"
                    " AND COALESCE(tuan_bd,1)=? AND thu=? AND buoi=? AND tiet=?",
                    (uid, nam, v, r["thu"], r["buoi"], r["tiet"])).fetchone() if r else None
    return r2, v


@bp.route("/tkb", methods=["GET", "POST"])
@login_required
def tkb():
    db, uid, u = get_db(), session["uid"], current_user()
    tuan = _tuan_xem()
    nam = _nam_hoc_gv(u)
    if request.method == "POST":
        act = request.form.get("act")
        tuan = _tuan_xem()
        nam = _nam_hoc_gv(u)
        if act in ("add", "edit"):
            dt, loi = _tkb_doc_form()
            mon, khoi, loi_mon = _tkb_mon_khoi()
            loi = loi_mon or loi
            if loi:
                flash(loi, "err")
            elif act == "edit":
                r = db.execute("SELECT * FROM tkb WHERE id=? AND teacher_id=?",
                               (request.form.get("id"), uid)).fetchone()
                if not r:
                    flash("Không tìm thấy tiết cần sửa (có thể đã bị xoá).", "err")
                else:
                    moc0 = set(TP.moc(db, uid, nam))
                    r, v = _tkb_dong_phien(db, uid, r, nam, tuan)
                    if not r:
                        flash("Không tìm thấy tiết cần sửa (có thể đã bị xoá).", "err")
                    else:
                        db.execute("UPDATE tkb SET thu=?,buoi=?,tiet=?,lop=?,mon=?,khoi=?,phong=?"
                                   " WHERE id=? AND teacher_id=?",
                                   (dt["thu"], dt["buoi"], dt["tiet"], dt["lop"], mon, khoi, dt["phong"],
                                    r["id"], uid))
                        _tkb_nho_tkb(dt)
                        flash("Đã sửa tiết dạy: %s · %s tiết %s · lớp %s · %s.%s"
                              % (THU_NAME[int(dt["thu"])], dt["buoi"], dt["tiet"], dt["lop"], mon,
                                 _tkb_tb_moc(v, moc0)), "ok")
            else:
                moc0 = set(TP.moc(db, uid, nam))
                v = TP.dam_bao_phien(db, uid, nam, tuan)
                db.execute("INSERT INTO tkb(teacher_id,thu,buoi,tiet,lop,mon,khoi,phong,tuan_bd,nam_hoc)"
                           " VALUES(?,?,?,?,?,?,?,?,?,?)",
                           (uid, dt["thu"], dt["buoi"], dt["tiet"], dt["lop"], mon, khoi, dt["phong"], v, nam))
                _tkb_nho_tkb(dt)
                flash("Đã thêm tiết dạy: %s · %s tiết %s · lớp %s · %s.%s"
                      % (THU_NAME[int(dt["thu"])], dt["buoi"], dt["tiet"], dt["lop"], mon,
                         _tkb_tb_moc(v, moc0)), "ok")
        elif act == "del":
            r = db.execute("SELECT * FROM tkb WHERE id=? AND teacher_id=?",
                           (request.form.get("id"), uid)).fetchone()
            r, v = _tkb_dong_phien(db, uid, r, nam, tuan) if r else (None, tuan)
            if r:
                db.execute("DELETE FROM tkb WHERE id=? AND teacher_id=?", (r["id"], uid))
                flash("Đã xoá tiết dạy: %s · %s tiết %s · lớp %s."
                      % (THU_NAME[int(r["thu"])] if str(r["thu"]).isdigit() else r["thu"],
                         r["buoi"], r["tiet"], r["lop"]), "ok")
        elif act == "clear":
            v = TP.phien_cho_tuan(db, uid, nam, tuan) or tuan
            n = db.execute("SELECT COUNT(*) FROM tkb WHERE teacher_id=? AND COALESCE(nam_hoc,'')=?"
                           " AND COALESCE(tuan_bd,1)=?", (uid, nam, v)).fetchone()[0]
            db.execute("DELETE FROM tkb WHERE teacher_id=? AND COALESCE(nam_hoc,'')=? AND COALESCE(tuan_bd,1)=?",
                       (uid, nam, v))
            flash("Đã xoá thời khoá biểu phiên bản áp dụng từ tuần %d (%d tiết)." % (v, n), "ok")
        db.commit()
        return redirect(url_for("core.tkb", tuan=tuan if tuan != 1 else None))
    rows = TP.dong(db, uid, nam, tuan)
    grid = {}
    for r in rows:
        grid.setdefault((r["buoi"], r["tiet"]), {})[r["thu"]] = r
    tiets = sorted({r["tiet"] for r in rows}) or [1, 2, 3, 4, 5]
    kho = [k for k in KHO.danh_sach(db, uid) if k["luu"]]
    doi_chieu = KHO.doi_chieu(db, uid, rows)
    dem = {"du": 0, "thieu": 0, "thua": 0, "chua_co_khdh": 0, "chua_ro": 0}
    for d in doi_chieu:
        dem[d["ket_luan"]] = dem.get(d["ket_luan"], 0) + 1
    ds_kho_khoi = KHO.danh_sach(db, uid)
    thu_chon = session.get("tkb_thu") or "2"
    buoi_chon = session.get("tkb_buoi") or "Sáng"
    ap_dung = TP.phien_cho_tuan(db, uid, nam, tuan)
    tuan1, da_chon_ngay = _tuan1_gv(u, db)
    breaks = LN.get_breaks(db, uid)
    tuans_pp = [r[0] for r in db.execute(
        "SELECT DISTINCT tuan FROM ppct WHERE teacher_id=? ORDER BY tuan", (uid,))]
    moc = TP.moc(db, uid, nam)
    max_tuan = max((tuans_pp or [1]) + moc + [tuan, 18])
    mp_tuan, _cal = LN.build_calendar(tuan1, breaks, max_hoc=max_tuan)
    lich_tuan = [{"tuan": t, "tu": mp_tuan[t].strftime("%d/%m/%Y"),
                  "den": (mp_tuan[t] + datetime.timedelta(days=6)).strftime("%d/%m/%Y"),
                  "co_ppct": t in tuans_pp} for t in sorted(mp_tuan)]
    ngay = {x["tuan"]: (x["tu"], x["den"]) for x in lich_tuan}
    return render_template("tkb.html", rows=rows, grid=grid, tiets=tiets, kho=kho,
                           doi_chieu=doi_chieu, dem=dem,
                           kho_khoi=ds_kho_khoi,
                           KHOI=KHO.KHOI, mon_kho={("%s|%s" % (k["mon"], k["khoi"])): True
                                                  for k in ds_kho_khoi},
                           thu_chon=str(thu_chon), buoi_chon=buoi_chon,
                           tuan=tuan, nam_hoc=nam, ap_dung_tu=ap_dung or 1,
                           ds_moc=moc, lich_tuan=lich_tuan,
                           lich_su=TP.lich_su(db, uid, nam, ngay),
                           tuan1=tuan1, tuan1_txt=tuan1.strftime("%d/%m/%Y"),
                           da_chon_ngay=da_chon_ngay, max_tuan=max_tuan)


# ---------------- Lịch báo giảng ----------------
def _tb_lbg_ppct(tb, ok, tuan=None):
    """Thêm câu: lịch báo giảng tự làm mới khi PPCT đổi."""
    if not ok:
        return tb
    extra = " Lịch báo giảng tự làm mới theo PPCT vừa lưu"
    try:
        t = int(tuan or 0)
    except Exception:
        t = 0
    if t >= 1:
        extra += " (tuần %d)" % t
    return tb + extra + "."



def _gan_canh_bao_tiet(rows, doi_chieu):
    """Gắn cảnh báo thiếu tiết vào cột ghi chú lịch báo giảng. Trả về danh sách môn thiếu."""
    mp, thieu = {}, []
    for d in doi_chieu or []:
        can = d.get("can")
        try:
            can_i = int(can) if can is not None else 0
        except Exception:
            can_i = 0
        if d.get("ket_luan") != "thieu" or can_i < 2:
            continue
        so = int(d.get("so_tiet") or 0)
        tb = "Thiếu %d tiết/tuần (chuẩn %d, lịch có %d)" % (can_i - so, can_i, so)
        mp[(KHO.chuan(d.get("mon") or ""), (d.get("lop") or "").strip())] = tb
        thieu.append(d)
    for r in rows or []:
        if r.get("nghi"):
            continue
        tb = mp.get((KHO.chuan(r.get("mon") or ""), (r.get("lop") or "").strip()))
        if not tb:
            continue
        r["canh_bao_tiet"] = tb
        cu = (r.get("ghi_chu") or "").strip()
        r["ghi_chu"] = (cu + " · " if cu else "") + "⚠ " + tb
    return thieu



def _rows_for_week(uid, tuan, monday, offday=None, nam_hoc=""):
    db = get_db()
    offday = offday or {}
    tkb = TP.dong(db, uid, nam_hoc, tuan) if nam_hoc else \
        db.execute("SELECT * FROM tkb WHERE teacher_id=? ORDER BY thu, buoi DESC, tiet", (uid,)).fetchall()
    pp = db.execute("SELECT * FROM ppct WHERE teacher_id=? AND tuan=? ORDER BY mon, tiet_pp", (uid, tuan)).fetchall()
    pool = {}
    for p in pp:
        pool.setdefault((p["mon"] or "").strip().lower(), []).append(p)
    out = []
    for t in tkb:
        mon = (t["mon"] or "").strip().lower()
        lst = pool.get(mon) or pool.get("") or []
        bai = lst.pop(0) if lst else None
        ngay, nghi = "", None
        if monday:
            d = monday + datetime.timedelta(days=int(t["thu"]) - 2)
            ngay = d.strftime("%d/%m/%Y")
            nghi = offday.get(d)
        khoa = "%s|%s|%s" % (t["thu"], t["buoi"], t["tiet"])
        if nghi:
            if bai:
                lst.insert(0, bai)
            out.append({"thu": t["thu"], "buoi": t["buoi"], "tiet": t["tiet"], "lop": t["lop"],
                        "mon": t["mon"], "ngay": ngay, "tiet_pp": "", "ten_bai": nghi,
                        "ghi_chu": "", "nghi": True, "khoa": khoa})
            continue
        out.append({"thu": t["thu"], "buoi": t["buoi"], "tiet": t["tiet"], "lop": t["lop"],
                    "mon": t["mon"], "ngay": ngay, "khoa": khoa,
                    "tiet_pp": bai["tiet_pp"] if bai else "", "ten_bai": bai["ten_bai"] if bai else "",
                    "ghi_chu": (bai["ghi_chu"] if bai else "") or (t["phong"] or ""), "nghi": False})
    return out


@bp.route("/bao-giang", methods=["GET", "POST"])
@login_required
def bao_giang():
    db, u = get_db(), current_user()
    tuan = max(1, int(request.values.get("tuan") or 1))

    # (M30) Ngày bắt đầu năm học = thứ Hai của TUẦN HỌC ĐẦU TIÊN; các tuần sau tự tính từ đó
    if request.values.get("tuan_1"):
        try:
            d0 = datetime.date.fromisoformat(request.values["tuan_1"].strip())
            d0 -= datetime.timedelta(days=d0.weekday())      # ép về thứ Hai
            set_setting(f"tuan1_{u['id']}", d0.isoformat())
            flash("Đã lưu ngày bắt đầu năm học: %s là thứ Hai của tuần học đầu tiên — tuần 1 từ %s đến %s."
                  % (d0.strftime("%d/%m/%Y"), d0.strftime("%d/%m/%Y"),
                     (d0 + datetime.timedelta(days=6)).strftime("%d/%m/%Y")), "ok")
        except Exception:
            flash("Ngày bắt đầu năm học chưa hợp lệ — thầy/cô chọn lại theo dạng ngày/tháng/năm.", "err")
    s_t1 = setting(f"tuan1_{u['id']}", "")
    if s_t1:
        tuan1 = datetime.date.fromisoformat(s_t1)
    else:
        t = datetime.date.today()
        tuan1 = t - datetime.timedelta(days=t.weekday())

    breaks = LN.get_breaks(db, u["id"])
    offday = LN.off_days(breaks)

    d = request.values.get("tu_ngay")
    if d:
        monday = datetime.date.fromisoformat(d)
    else:
        monday = LN.monday_for_week(tuan1, breaks, tuan)

    nam = TP.nam_hoc_tu_ngay(tuan1)
    act = request.form.get("act") if request.method == "POST" else None
    if act == "luu_lop":
        khoa = request.form.getlist("khoa")
        lop = request.form.getlist("lop")
        ds_doi = [{"khoa": k, "lop": v} for k, v in zip(khoa, lop)]
        ok, tb, _n = TP.luu_lop(db, u["id"], nam, tuan, ds_doi)
        flash(tb, "ok" if ok else "err")
        return redirect(url_for("core.bao_giang", tuan=tuan))
    if act == "tiet_tuan":
        ok, tb = KHO.dat_tiet_tuan_mon(db, u["id"], request.form.get("mon") or "",
                                       request.form.get("khoi") or "", request.form.get("so_tiet_tuan"))
        flash(tb, "ok" if ok else "err")
        return redirect(url_for("core.bao_giang", tuan=tuan))

    rows = _rows_for_week(session["uid"], tuan, monday, offday, nam_hoc=nam)
    tkb_tuan = TP.dong(db, u["id"], nam, tuan)
    canh_bao_tiet = _gan_canh_bao_tiet(rows, KHO.doi_chieu(db, u["id"], tkb_tuan))
    ap_dung = TP.phien_cho_tuan(db, u["id"], nam, tuan) or 1
    meta = {"truong": request.values.get("truong") or u["school"] or "",
            "to": request.values.get("to", ""), "giao_vien": u["fullname"] or u["username"],
            "mon": request.values.get("mon") or u["subject"] or "",
            "tuan": tuan, "tu_ngay": monday.strftime("%d/%m/%Y"),
            "den_ngay": (monday + datetime.timedelta(days=6)).strftime("%d/%m/%Y"),
            "noi_dung_khac": request.values.get("noi_dung_khac", ""),
            "dia_danh": request.values.get("dia_danh", "Sóc Trăng"),
            "ngay_ky": monday.day, "thang_ky": monday.month, "nam_ky": monday.year,
            "ap_dung_tu_tuan": ap_dung}

    if act in ("pdf", "word"):
        # (M14) PDF mở xem trực tuyến: KHÔNG tính lượt. Tải file Word về: tính 1 lượt.
        if act == "word":
            if not BL.tra_luot_tai(db, u, "baogiang", f"baogiang-{u['id']}-tuan{tuan}",
                                   f"Lịch báo giảng tuần {tuan} (tải file Word)"):
                flash(BL.thong_bao_het(), "err")
                return redirect(url_for("core.nang_cap", need="word"))
            return send_file(build_docx(meta, rows), as_attachment=True,
                             download_name=f"lich-bao-giang-tuan-{tuan}.docx",
                             mimetype="application/vnd.openxmlformats-officedocument."
                                      "wordprocessingml.document")
        return send_file(build_pdf(meta, rows), mimetype="application/pdf", as_attachment=False,
                         download_name=f"lich-bao-giang-tuan-{tuan}.pdf")

    tuans_pp = [r[0] for r in db.execute(
        "SELECT DISTINCT tuan FROM ppct WHERE teacher_id=? ORDER BY tuan", (u["id"],))]
    max_tuan = max(tuans_pp or [1])
    tuan_now = LN.current_week(tuan1, breaks)
    mp_tuan, cal = LN.build_calendar(tuan1, breaks, max_hoc=max(max_tuan, tuan, 1))
    lich_tuan = [{"tuan": t, "tu": mp_tuan[t].strftime("%d/%m/%Y"),
                  "den": (mp_tuan[t] + datetime.timedelta(days=6)).strftime("%d/%m/%Y"),
                  "co_ppct": t in tuans_pp} for t in sorted(mp_tuan) if t <= max(max_tuan, tuan)]
    da_xuat = {int(m.group(1)) for m in (re.match(r"Lịch báo giảng tuần (\d+)", r["detail"] or "")
               for r in db.execute("SELECT detail FROM usage_log WHERE teacher_id=? AND kind IN ('pdf','word')",
                                   (u["id"],))) if m}
    nghi_tuan_nay = LN.week_label(monday, breaks)
    meta["nghi"] = nghi_tuan_nay
    ds_lop = TP.ds_lop(db, u["id"], nam)
    for r in rows:
        if r.get("lop") and r["lop"] not in ds_lop:
            ds_lop.append(r["lop"])
    html = render_template("baogiang.html", rows=rows, meta=meta, monday=monday, tuan=tuan,
                           tuans_pp=tuans_pp, max_tuan=max_tuan, tuan_now=tuan_now,
                           tuan1=tuan1, da_xuat=da_xuat, cal=cal, breaks=breaks,
                           nghi_tuan_nay=nghi_tuan_nay, lich_tuan=lich_tuan,
                           da_chon_ngay=bool(s_t1),
                           tuan1_txt=tuan1.strftime("%d/%m/%Y"),
                           sua=request.values.get("sua") in ("1", "on", "true"),
                           ds_lop=ds_lop, ap_dung_tu=ap_dung, ds_moc=TP.moc(db, u["id"], nam),
                           nam_hoc=nam, dau_ppct=MH.dau_ppct(db, u["id"]),
                           canh_bao_tiet=canh_bao_tiet)
    resp = make_response(html)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@bp.route("/bao-giang/ppct-rev")
@login_required
def bao_giang_ppct_rev():
    """Dấu PPCT hiện tại — trang lịch báo giảng hỏi định kỳ để tự làm mới khi PPCT đổi."""
    db, uid = get_db(), session["uid"]
    resp = jsonify(ok=True, dau=MH.dau_ppct(db, uid))
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------- Nhận xét AI ----------------
@bp.route("/nhan-xet", methods=["GET", "POST"])
@login_required
def nhan_xet():
    db, uid = get_db(), session["uid"]
    result, cols = None, None
    if request.method == "POST":
        # (M14) sinh nhận xét và xem trực tuyến KHÔNG tính lượt — lượt chỉ tính khi xuất Excel
        u = current_user()
        provider = request.form.get("provider", "rule")
        thang = float(request.form.get("thang") or 10)
        mon = request.form.get("mon", "")
        lop = request.form.get("lop", "")
        hocky = request.form.get("hocky", "HK1")
        hien_diem = bool(request.form.get("hien_diem"))
        records = []
        f = request.files.get("file")
        if f and f.filename:
            df = XL.read_table(f)
            m = XL.map_columns(df.columns)
            cols = m
            for _, r in df.iterrows():
                rec = {"ho_ten": "", "diem": None, "muc_do": None, "nhan_xet_goc": "",
                       "lop": lop, "mon": mon}
                for c, key in m.items():
                    v = r[c]
                    if str(v) == "nan":
                        v = None
                    if key == "diem":
                        try: rec["diem"] = float(v)
                        except Exception: rec["diem"] = None
                    elif key == "muc_do":
                        rec["muc_do"] = XL.chuan_muc_do(v)
                    elif key in ("ho_ten", "nhan_xet_goc", "lop", "mon"):
                        if v: rec[key] = str(v).strip()
                if rec["ho_ten"]:
                    records.append(rec)
        else:  # nhập tay
            names = request.form.getlist("ten[]")
            diems = request.form.getlist("diem[]")
            mds = request.form.getlist("md[]")
            for i, nm in enumerate(names):
                if not nm.strip():
                    continue
                try: d = float(diems[i])
                except Exception: d = None
                records.append({"ho_ten": nm.strip(), "diem": d,
                                "muc_do": (mds[i] or None), "nhan_xet_goc": "", "lop": lop, "mon": mon})
        for rec in records:
            rec["thang"] = thang
            rec["hien_diem"] = hien_diem
            if not rec["muc_do"]:
                rec["muc_do"] = AI.diem_to_mucdo(rec["diem"], thang)
            rec["xep_loai"] = AI.diem_to_xeploai(rec["diem"], thang) if rec["diem"] is not None else (rec["muc_do"] or "")
            rec["nhan_xet"] = AI.sinh_nhan_xet(rec, provider)
            db.execute("""INSERT INTO danhgia(teacher_id,lop,mon,hocky,ho_ten,diem,muc_do,nhan_xet_goc,nhan_xet,created)
                          VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (uid, rec["lop"], rec["mon"], hocky, rec["ho_ten"], rec["diem"], rec["muc_do"],
                        rec["nhan_xet_goc"], rec["nhan_xet"], datetime.datetime.now().isoformat(timespec="seconds")))
        db.commit()
        result = records
        session["last_meta"] = {"lop": lop, "mon": mon, "hocky": hocky}
    return render_template("nhanxet.html", result=result, cols=cols)


@bp.route("/nhan-xet/lich-su")
@login_required
def lich_su():
    rows = get_db().execute("SELECT * FROM danhgia WHERE teacher_id=? ORDER BY id DESC LIMIT 500",
                            (session["uid"],)).fetchall()
    return render_template("lichsu.html", rows=rows)


@bp.route("/nhan-xet/sua", methods=["POST"])
@login_required
def sua_nx():
    db = get_db()
    db.execute("UPDATE danhgia SET nhan_xet=? WHERE id=? AND teacher_id=?",
               (request.form["nhan_xet"], request.form["id"], session["uid"]))
    db.commit()
    return jsonify(ok=True)


@bp.route("/nhan-xet/tao-lai", methods=["POST"])
@login_required
def tao_lai():
    d = request.get_json(force=True)
    txt = AI.sinh_nhan_xet(d, d.get("provider", "rule"))
    return jsonify(nhan_xet=txt)


@bp.route("/xuat-excel")
@login_required
def xuat_excel():
    u = current_user()
    ids = request.args.get("ids")
    q = "SELECT * FROM danhgia WHERE teacher_id=?"
    p = [session["uid"]]
    if ids:
        q += " AND id IN (%s)" % ",".join("?" * len(ids.split(",")))
        p += ids.split(",")
    rows = get_db().execute(q + " ORDER BY id DESC", p).fetchall()
    data = [{"ho_ten": r["ho_ten"], "lop": r["lop"], "mon": r["mon"], "diem": r["diem"],
             "muc_do": r["muc_do"], "xep_loai": AI.diem_to_xeploai(r["diem"]) if r["diem"] is not None else "",
             "nhan_xet": r["nhan_xet"]} for r in rows]
    # (M14) lượt tính khi TẢI TỆP VỀ — tải lại đúng bảng nhận xét này không trừ thêm
    if not BL.tra_luot_tai(get_db(), u, "excel",
                           "excel-%s-%s-%d" % (u["id"], ids or "all", len(data)),
                           f"Xuất {len(data)} nhận xét"):
        flash(BL.thong_bao_het(), "err")
        return redirect(url_for("core.nang_cap", need="excel"))
    bio = XL.export_xlsx(data, {"tieu_de": "BẢNG NHẬN XÉT HỌC SINH"})
    return send_file(bio, as_attachment=True, download_name="nhan-xet-hoc-sinh.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/mau-excel/<kind>")
def mau_excel(kind):
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    if kind == "diem":
        ws.append(["Họ và tên", "Lớp", "Môn", "Điểm", "Mức độ", "Nhận xét của GV"])
        ws.append(["Nguyễn Văn An", "5A", "Toán", 9.5, "", ""])
        ws.append(["Trần Thị Bình", "5A", "Toán", 6, "", "hay quên vở bài tập"])
        ws.append(["Lê Minh Cường", "5A", "Toán", "", "CHT", ""])
    else:
        ws.append(["Tuần", "Tiết PPCT", "Tên bài", "Ghi chú"])
        ws.append([1, 1, "Ôn tập số tự nhiên", "Bảng phụ"])
        ws.append([1, 2, "Ôn tập phân số", ""])
    widths = [26, 10, 14, 10, 12, 40] if kind == "diem" else [10, 12, 40, 22]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w
    bio = io.BytesIO(); wb.save(bio); bio.seek(0)
    return send_file(bio, as_attachment=True, download_name=f"mau-{kind}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/cai-dat", methods=["GET", "POST"])
@login_required
def cai_dat():
    db = get_db()
    if request.method == "POST":
        raw = request.form.get("phone", "").strip()
        phone = SMS.normalize(raw)
        if raw and not phone:
            flash("Số điện thoại không hợp lệ. Ví dụ đúng: 0912345678", "err")
            return redirect(url_for("core.cai_dat"))
        db.execute("UPDATE teacher SET fullname=?,school=?,phone=? WHERE id=?",
                   (request.form["fullname"], request.form["school"], phone, session["uid"]))
        # (M17) lưu DANH SÁCH môn dạy; môn đầu tiên là môn chính (ghi vào cột subject cũ)
        ds_mon = MD.luu(db, session["uid"], MD.tach_mon(request.form.get("mon_day") or ""))
        flash("Đã lưu thông tin · %s" % MD.tom_tat({"subjects": "\n".join(ds_mon)})
              + (" · Mã kích hoạt sẽ được nhắn tới " + SMS.mask(phone) if phone else ""), "ok")
        return redirect(url_for("core.cai_dat"))
    return render_template("caidat.html")


# ---------------- Nâng cấp / Thanh toán ----------------
@bp.route("/nang-cap", methods=["GET", "POST"])
@login_required
def nang_cap():
    db, u = get_db(), current_user()
    if request.method == "POST":
        ok, msg = BL.redeem(db, u, request.form.get("code", ""))
        flash(msg, "ok" if ok else "err")
        return redirect(url_for("core.nang_cap"))
    goi = request.args.get("goi", "vip")
    content = BL.transfer_content(u, goi)
    gia = BL.PRICE if goi == "vip" else BL.PRICE_LUOT
    qr = VQ.build_qr(BL.BANK_CODE, BL.BANK_ACC, gia, content, BL.BANK_OWNER)
    logs = db.execute("SELECT * FROM usage_log WHERE teacher_id=? ORDER BY id DESC LIMIT 20",
                      (u["id"],)).fetchall()
    return render_template("nangcap.html", qr_svg=qr, noi_dung=content, logs=logs,
                           need=request.args.get("need", ""), goi=goi, gia=gia,
                           tudong=bool(BW.WEBHOOK_TOKEN) and BW.AUTO_ACTIVATE)


@bp.route("/nang-cap/hoa-don")
@login_required
def hoa_don():
    """(M28) Danh sách hoá đơn / biên lai của giáo viên (giao dịch ngân hàng + mã kích hoạt)."""
    db = get_db()
    ds = HD.danh_sach(db, session["uid"])
    return render_template("hoadon.html", ds=ds, tong=HD.tien_chu(ds))


@bp.route("/nang-cap/hoa-don/<loai>/<int:iid>")
@login_required
def hoa_don_ct(loai, iid):
    """(M28) Biên lai in được — có logo EduAssist, số tiền bằng chữ, mã giao dịch."""
    if loai not in ("bank", "ma"):
        return redirect(url_for("core.hoa_don"))
    r = HD.tim(HD.danh_sach(get_db(), session["uid"]), loai, iid)
    if not r:
        flash("Không tìm thấy biên lai này trong tài khoản của thầy/cô.", "err")
        return redirect(url_for("core.hoa_don"))
    return render_template("hoadon_ct.html", r=r, tien_chu=HD.doc_tien(r.get("so_tien") or 0))


@bp.route("/nang-cap/sdt", methods=["POST"])
@login_required
def luu_sdt():
    """Lưu nhanh số điện thoại ngay tại trang thanh toán."""
    db = get_db()
    raw = request.form.get("phone", "").strip()
    phone = SMS.normalize(raw)
    if raw and not phone:
        flash("Số điện thoại không hợp lệ. Ví dụ đúng: 0912345678", "err")
    else:
        db.execute("UPDATE teacher SET phone=? WHERE id=?", (phone, session["uid"]))
        db.commit()
        flash(f"Đã lưu số {phone} — hệ thống sẽ nhắn tin ngay khi nhận được chuyển khoản."
              if phone else "Đã xoá số điện thoại.", "ok")
    return redirect(url_for("core.nang_cap", goi=request.form.get("goi", "vip")))


# ---------------- Quản trị (chỉ admin) ----------------
@bp.route("/quan-tri", methods=["GET", "POST"])
@admin_required
def quan_tri():
    db = get_db()
    if request.method == "POST":
        act = request.form.get("act")
        if act == "gen":
            n = max(1, min(50, int(request.form.get("n") or 1)))
            loai = request.form.get("loai", "vip")
            codes = BL.create_codes(db, n, int(request.form.get("months") or 12),
                                    request.form.get("note", ""), loai,
                                    int(request.form.get("luot") or BL.LUOT_MOI_GOI))
            flash(f"Đã tạo {len(codes)} mã {'VIP 1 năm' if loai=='vip' else 'gói lẻ'}: "
                  + ", ".join(codes), "ok")
        elif act == "addluot":
            db.execute("UPDATE teacher SET bought = COALESCE(bought,0) + ? WHERE id=?",
                       (int(request.form.get("n") or 3), request.form.get("tid")))
            db.commit()
            flash("Đã cộng thêm lượt cho tài khoản.", "ok")
        elif act == "grant":
            tid = request.form.get("tid")
            days = int(request.form.get("days") or 365)
            row = db.execute("SELECT expires FROM teacher WHERE id=?", (tid,)).fetchone()
            base = datetime.date.today()
            if row and row["expires"]:
                try:
                    e = datetime.date.fromisoformat(row["expires"])
                    if e > base:
                        base = e
                except Exception:
                    pass
            db.execute("UPDATE teacher SET expires=? WHERE id=?",
                       ((base + datetime.timedelta(days=days)).isoformat(), tid))
            db.commit()
            flash("Đã gia hạn cho tài khoản.", "ok")
        elif act == "reset":
            db.execute("UPDATE teacher SET used=0 WHERE id=?", (request.form.get("tid"),))
            db.commit()
            flash("Đã reset lượt dùng thử.", "ok")
        elif act == "phone":
            ph = SMS.normalize(request.form.get("phone"))
            db.execute("UPDATE teacher SET phone=? WHERE id=?", (ph, request.form.get("tid")))
            db.commit()
            flash("Đã cập nhật số điện thoại." if ph else "Đã xoá số điện thoại (số không hợp lệ).",
                  "ok" if ph else "err")
        elif act == "resend":
            tx = db.execute("SELECT * FROM bank_tx WHERE id=?", (request.form.get("id"),)).fetchone()
            u2 = db.execute("SELECT * FROM teacher WHERE id=?",
                            (tx["teacher_id"] if tx else None,)).fetchone()
            if not tx or not u2 or not u2["phone"]:
                flash("Không gửi lại được: thiếu giao dịch hoặc tài khoản chưa có số điện thoại.", "err")
            else:
                het = ""
                if u2["expires"]:
                    het = datetime.date.fromisoformat(u2["expires"]).strftime("%d/%m/%Y")
                txt = (SMS.mau_da_kich_hoat(tx["goi"] or "luot", BL.LUOT_MOI_GOI, het)
                       if tx["trang_thai"] == "da_kich_hoat"
                       else SMS.mau_ma_kich_hoat(tx["code"] or "", tx["goi"] or "luot",
                                                 BL.LUOT_MOI_GOI, het))
                ok, msg = SMS.send(u2["phone"], txt, db=db, teacher_id=u2["id"], loai="gui_lai")
                flash(("✅ " if ok else "❌ ") + msg, "ok" if ok else "err")
        elif act == "duyet":
            # đối soát tay: gán giao dịch treo cho 1 tài khoản rồi kích hoạt
            tx = db.execute("SELECT * FROM bank_tx WHERE id=?", (request.form.get("id"),)).fetchone()
            u2 = db.execute("SELECT * FROM teacher WHERE id=?", (request.form.get("tid"),)).fetchone()
            if not tx or not u2:
                flash("Thiếu giao dịch hoặc tài khoản.", "err")
            else:
                goi = request.form.get("goi") or BW.doan_goi_theo_tien(tx["so_tien"]) or "luot"
                luot = BL.LUOT_MOI_GOI * BW.so_goi_le(tx["so_tien"]) if goi == "luot" else 0
                code = BL.create_codes(db, 1, 12 if goi == "vip" else 0,
                                       f"Đối soát tay — {tx['ref']}", goi, luot)[0]
                ok, msg = BL.redeem(db, u2, code)
                db.execute("UPDATE bank_tx SET teacher_id=?,goi=?,code=?,trang_thai=?,ghi_chu=? WHERE id=?",
                           (u2["id"], goi, code, "da_kich_hoat" if ok else "cho_doi_soat",
                            "Đối soát tay: " + msg, tx["id"]))
                db.commit()
                if ok and u2["phone"]:
                    het = (datetime.date.fromisoformat(u2["expires"]).strftime("%d/%m/%Y")
                           if u2["expires"] else "")
                    SMS.send(u2["phone"], SMS.mau_da_kich_hoat(goi, luot, het),
                             db=db, teacher_id=u2["id"], loai="doi_soat")
                flash(msg, "ok" if ok else "err")
        elif act == "delcode":
            db.execute("DELETE FROM license WHERE id=? AND used_by IS NULL", (request.form.get("id"),))
            db.commit()
        return redirect(url_for("core.quan_tri"))

    users = db.execute("SELECT * FROM teacher ORDER BY id DESC").fetchall()
    codes = db.execute("""SELECT l.*, t.fullname, t.username FROM license l
                          LEFT JOIN teacher t ON t.id=l.used_by ORDER BY l.id DESC LIMIT 200""").fetchall()
    stats = {
        "users": len(users),
        "pro": sum(1 for x in users if BL.is_pro(x)),
        "codes_free": sum(1 for c in codes if not c["used_by"]),
        "revenue": sum((BL.PRICE if (c["loai"] or "vip") == "vip" else BL.PRICE_LUOT)
                       for c in codes if c["used_by"]),
    }
    txs = db.execute("""SELECT b.*, t.fullname, t.username, t.phone FROM bank_tx b
                        LEFT JOIN teacher t ON t.id=b.teacher_id
                        ORDER BY b.id DESC LIMIT 100""").fetchall()
    smss = db.execute("""SELECT s.*, t.fullname FROM sms_log s
                         LEFT JOIN teacher t ON t.id=s.teacher_id
                         ORDER BY s.id DESC LIMIT 50""").fetchall()
    stats["treo"] = sum(1 for x in txs if x["trang_thai"] == "cho_doi_soat")
    stats["tudong"] = sum(1 for x in txs if x["trang_thai"] == "da_kich_hoat")
    return render_template("quantri.html", users=users, codes=codes, stats=stats,
                           txs=txs, smss=smss, SMS=SMS, BW=BW)


# ---------------- Lịch nghỉ ----------------
@bp.route("/lich-nghi", methods=["GET", "POST"])
@login_required
def lich_nghi():
    db, u = get_db(), current_user()
    if request.method == "POST":
        act = request.form.get("act")
        if act == "add":
            tu = LN.parse_date(request.form.get("tu_ngay"))
            den = LN.parse_date(request.form.get("den_ngay")) or tu
            if tu and den >= tu:
                db.execute("""INSERT INTO nghi(teacher_id,ten,kieu,tu_ngay,den_ngay,created)
                              VALUES(?,?,?,?,?,?)""",
                           (u["id"], request.form.get("ten") or "Nghỉ",
                            request.form.get("kieu", "tuan"), tu.isoformat(), den.isoformat(),
                            datetime.datetime.now().isoformat(timespec="seconds")))
                db.commit()
                flash("Đã thêm kỳ nghỉ.", "ok")
            else:
                flash("Ngày không hợp lệ (ngày kết thúc phải sau ngày bắt đầu).", "err")
        elif act == "del":
            db.execute("DELETE FROM nghi WHERE id=? AND teacher_id=?", (request.form["id"], u["id"]))
            db.commit()
        elif act == "tet":
            # thêm nhanh 2 tuần nghỉ Tết
            y = int(request.form.get("nam") or datetime.date.today().year)
            start = LN.monday_of(LN.tet_suggest(y)) - datetime.timedelta(days=7)
            den = start + datetime.timedelta(days=13)
            db.execute("""INSERT INTO nghi(teacher_id,ten,kieu,tu_ngay,den_ngay,created)
                          VALUES(?,?,?,?,?,?)""",
                       (u["id"], f"Nghỉ Tết Nguyên đán {y}", "tuan",
                        start.isoformat(), den.isoformat(),
                        datetime.datetime.now().isoformat(timespec="seconds")))
            db.commit()
            flash("Đã thêm 2 tuần nghỉ Tết — bạn có thể sửa lại ngày cho khớp thông báo của trường.", "ok")
        return redirect(url_for("core.lich_nghi"))

    s_t1 = setting(f"tuan1_{u['id']}", "")
    tuan1 = datetime.date.fromisoformat(s_t1) if s_t1 else LN.monday_of(datetime.date.today())
    breaks = LN.get_breaks(db, u["id"])
    max_tuan = max([r[0] for r in db.execute(
        "SELECT DISTINCT tuan FROM ppct WHERE teacher_id=?", (u["id"],))] or [35])
    _, cal = LN.build_calendar(tuan1, breaks, max_hoc=max_tuan)
    n_tuan_nghi = sum(1 for c in cal if c["nghi"])
    ket_thuc = cal[-1]["monday"] + datetime.timedelta(days=6) if cal else None
    return render_template("lichnghi.html", breaks=breaks, cal=cal, tuan1=tuan1,
                           max_tuan=max_tuan, n_tuan_nghi=n_tuan_nghi, ket_thuc=ket_thuc,
                           nam_nay=datetime.date.today().year)


# ---------------- Bảng điều khiển quản trị ----------------
@bp.route("/quan-tri/tong-quan")
@admin_required
def qt_dashboard():
    """Bảng điều khiển: số liệu kinh doanh và tình trạng hệ thống."""
    db = get_db()
    hom_nay = datetime.date.today()
    d30 = (hom_nay - datetime.timedelta(days=29)).isoformat()
    d7 = (hom_nay - datetime.timedelta(days=6)).isoformat()

    users = db.execute("SELECT * FROM teacher").fetchall()
    pro = [u for u in users if BL.is_pro(u)]

    # --- doanh thu theo giao dịch thật đã đối soát ---
    dt_tong = db.execute(
        "SELECT COALESCE(SUM(so_tien),0) s FROM bank_tx WHERE trang_thai IN ('da_kich_hoat','da_tao_ma')"
    ).fetchone()["s"]
    dt_30 = db.execute(
        "SELECT COALESCE(SUM(so_tien),0) s FROM bank_tx"
        " WHERE trang_thai IN ('da_kich_hoat','da_tao_ma') AND created >= ?", (d30,)).fetchone()["s"]
    dt_hnay = db.execute(
        "SELECT COALESCE(SUM(so_tien),0) s FROM bank_tx"
        " WHERE trang_thai IN ('da_kich_hoat','da_tao_ma') AND created >= ?",
        (hom_nay.isoformat(),)).fetchone()["s"]

    # --- biểu đồ 30 ngày: người dùng mới + doanh thu ---
    bd = []
    for i in range(29, -1, -1):
        ng = (hom_nay - datetime.timedelta(days=i)).isoformat()
        bd.append({
            "ngay": ng,
            "nhan": f"{ng[8:10]}/{ng[5:7]}",
            "moi": db.execute("SELECT COUNT(*) c FROM teacher WHERE created LIKE ?",
                              (ng + "%",)).fetchone()["c"],
            "tien": db.execute(
                "SELECT COALESCE(SUM(so_tien),0) s FROM bank_tx WHERE created LIKE ?"
                " AND trang_thai IN ('da_kich_hoat','da_tao_ma')", (ng + "%",)).fetchone()["s"],
            "luot": db.execute("SELECT COUNT(*) c FROM usage_log WHERE created LIKE ?",
                               (ng + "%",)).fetchone()["c"],
        })

    # --- chức năng nào được dùng nhiều nhất ---
    NHAN = {"pdf": ("📄 Báo giảng PDF", "#06b6d4"), "word": ("📝 Báo giảng Word", "#1d4ed8"),
            "excel": ("📊 Nhận xét Excel", "#059669"), "chinhta": ("🔤 Sửa chính tả", "#8b5cf6")}
    rows = db.execute("SELECT kind, COUNT(*) c FROM usage_log GROUP BY kind ORDER BY c DESC").fetchall()
    tong_luot = sum(r["c"] for r in rows) or 1
    chuc_nang = [{"ten": NHAN.get(r["kind"], (r["kind"], "#64748b"))[0],
                  "mau": NHAN.get(r["kind"], (r["kind"], "#64748b"))[1],
                  "so": r["c"], "pt": round(r["c"] * 100 / tong_luot)} for r in rows]

    # --- giáo viên hoạt động tích cực nhất ---
    top = db.execute("""SELECT t.id, t.fullname, t.username, t.school, COUNT(l.id) n
                        FROM teacher t JOIN usage_log l ON l.teacher_id=t.id
                        GROUP BY t.id ORDER BY n DESC LIMIT 8""").fetchall()

    # --- việc cần làm ---
    viec = []
    treo = db.execute("SELECT COUNT(*) c FROM bank_tx WHERE trang_thai='cho_doi_soat'").fetchone()["c"]
    if treo:
        viec.append({"muc": "warn", "icon": "⏳",
                     "text": f"{treo} giao dịch chuyển khoản chờ đối soát tay",
                     "link": url_for("core.quan_tri"), "nut": "Xem ngay"})
    smsloi = db.execute("SELECT COUNT(*) c FROM sms_log WHERE ok=0").fetchone()["c"]
    if smsloi:
        viec.append({"muc": "warn", "icon": "📩",
                     "text": f"{smsloi} tin nhắn gửi thất bại",
                     "link": url_for("core.quan_tri"), "nut": "Kiểm tra"})
    for k in CFG.suc_khoe():
        if not k["ok"]:
            viec.append({"muc": "info", "icon": "⚙️", "text": k["thong_diep"],
                         "link": url_for("core.qt_caidat") + "#" + k["muc"], "nut": "Cài đặt"})

    stats = {
        "users": len(users), "pro": len(pro),
        "moi_7": sum(1 for u in users if (u["created"] or "") >= d7),
        "co_sdt": sum(1 for u in users if u["phone"]),
        "dt_tong": dt_tong, "dt_30": dt_30, "dt_hnay": dt_hnay,
        "tong_luot": db.execute("SELECT COUNT(*) c FROM usage_log").fetchone()["c"],
        "gd_tudong": db.execute(
            "SELECT COUNT(*) c FROM bank_tx WHERE trang_thai='da_kich_hoat'").fetchone()["c"],
        "gd_treo": treo,
        "sms_gui": db.execute("SELECT COUNT(*) c FROM sms_log WHERE ok=1").fetchone()["c"],
        "ma_chua_dung": db.execute(
            "SELECT COUNT(*) c FROM license WHERE used_by IS NULL").fetchone()["c"],
    }
    return render_template("qt_dashboard.html", stats=stats, bd=bd, chuc_nang=chuc_nang,
                           top=top, viec=viec, suc_khoe=CFG.suc_khoe(),
                           gd_moi=db.execute("""SELECT b.*, t.fullname FROM bank_tx b
                               LEFT JOIN teacher t ON t.id=b.teacher_id
                               ORDER BY b.id DESC LIMIT 8""").fetchall())


@bp.route("/quan-tri/cai-dat", methods=["GET", "POST"])
@admin_required
def qt_caidat():
    """Cài đặt hệ thống — sửa mọi tham số ngay trên web."""
    db = get_db()
    if request.method == "POST":
        act = request.form.get("act", "luu")
        if act == "sinh_khoa":
            import secrets as _s
            CFG.set_many(db, {"BANK_WEBHOOK_TOKEN": _s.token_urlsafe(32)})
            flash("Đã sinh khoá bí mật mới. Nhớ dán khoá này sang SePay / Casso.", "ok")
        elif act == "mac_dinh":
            CFG.xoa(db, request.form.get("key", ""))
            flash("Đã trả tham số về giá trị mặc định.", "ok")
        elif act == "thu_google":
            ok, msg = kiem_tra_google()
            flash(msg, "ok" if ok else "err")
        elif act == "thu_sms":
            u = current_user()
            phone = SMS.normalize(request.form.get("phone")) or (u["phone"] if u else None)
            if not phone:
                flash("Nhập số điện thoại để gửi thử.", "err")
            else:
                ok, msg = SMS.send(phone, "EduAssist: Tin nhan thu nghiem. Neu nhan duoc tin nay "
                                          "nghia la cau hinh nhan tin da hoat dong.",
                                   db=db, teacher_id=u["id"] if u else None, loai="thu_nghiem")
                flash(msg, "ok" if ok else "err")
        else:
            data = {k: v for k, v in request.form.items() if k in CFG.BANG}
            # ô bí mật để trống nghĩa là giữ nguyên, không phải xoá
            for m in CFG.DINH_NGHIA:
                if m.bimat and data.get(m.key, "") == "" and CFG.get(m.key):
                    data.pop(m.key, None)
            # checkbox không tick thì trình duyệt không gửi -> tự điền "0"
            for m in CFG.DINH_NGHIA:
                if m.kieu == "bool" and m.key in request.form.getlist("_bool"):
                    data[m.key] = "1" if request.form.get(m.key) else "0"
            n = CFG.set_many(db, data)
            flash(f"Đã lưu {n} tham số. Thay đổi có hiệu lực ngay, không cần khởi động lại.", "ok")
        return redirect(url_for("core.qt_caidat") + "#" + request.form.get("nhom", ""))

    muc_theo_nhom = {}
    for m in CFG.DINH_NGHIA:
        muc_theo_nhom.setdefault(m.nhom, []).append(
            {"m": m, "gia_tri": CFG.get(m.key), "nguon": CFG.nguon(m.key)})
    return render_template("qt_caidat.html", NHOM=CFG.NHOM, muc=muc_theo_nhom,
                           CFG=CFG, suc_khoe=CFG.suc_khoe(),
                           google_tt=google_tinh_trang(),
                           webhook_url=request.url_root.rstrip("/") + "/webhook/bank")


@bp.route("/favicon.ico")
def favicon():
    """(LOGO-B) favicon cho trình duyệt cũ và các yêu cầu /favicon.ico mặc định."""
    return send_from_directory(os.path.join(os.path.dirname(__file__), "static"), "favicon.ico",
                               mimetype="image/vnd.microsoft.icon")


@bp.route("/suc-khoe")
def suc_khoe():
    """Trang kiểm tra máy chủ còn sống — dùng cho UptimeRobot chống ngủ."""
    try:
        get_db().execute("SELECT 1").fetchone()
        return jsonify(ok=True, ten=CFG.get("SITE_NAME", "EduAssist"),
                       gio=datetime.datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        return jsonify(ok=False, loi=str(e)), 500

import io, json, datetime, csv, re, os, time, uuid
from flask import (Blueprint, render_template, request, redirect, url_for, session,
                   send_file, jsonify, flash, Response)
from .db import get_db, setting, set_setting
from .auth import (login_required, current_user, admin_required, google_bat,
                    google_callback_url, google_tinh_trang, kiem_tra_google)
from .modules import ai_nhanxet as AI
from .modules import excel_io as XL
from .modules.pdf_bao_giang import build_pdf, THU_NAME
from .modules.word_bao_giang import build_docx
from .modules import billing as BL
from .modules import vietqr as VQ
from .modules import lichnghi as LN
from .modules import chinhta as CT
from .modules import docx_text as DT
from .modules import sms as SMS
from .modules import bank_webhook as BW
from .modules import config as CFG

bp = Blueprint("core", __name__)


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
            "canh_bao_mk": _mk_mac_dinh(u)}


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
        pts = "0,%s 100,%s" % (round(40 - spark[0]["y"] * 36.0 / smax, 2),) * 2

    # TKB hom nay
    today = datetime.date.today()
    thu = today.weekday() + 2
    hom_nay = db.execute("SELECT * FROM tkb WHERE teacher_id=? AND thu=? ORDER BY buoi DESC, tiet", (uid, thu)).fetchall()
    tiet_tuan = db.execute("SELECT thu, COUNT(*) c FROM tkb WHERE teacher_id=? GROUP BY thu", (uid,)).fetchall()
    load = {r["thu"]: r["c"] for r in tiet_tuan}
    lmax = max(list(load.values()) or [1])
    recent = db.execute("SELECT * FROM danhgia WHERE teacher_id=? ORDER BY id DESC LIMIT 6", (uid,)).fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent, donut=donut, tong=sum(dist.values()),
                           hist=hist, avg=avg, per_lop=per_lop, spark=spark, pts=pts, smax=smax,
                           hom_nay=hom_nay, load=load, lmax=lmax, today=today, thu=thu, dist=dist)


# ---------------- PPCT ----------------
@bp.route("/ppct", methods=["GET", "POST"])
@login_required
def ppct():
    db, uid = get_db(), session["uid"]
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
            f = request.files.get("file")
            if f and f.filename:
                df = XL.read_table(f)
                cmap = {c: XL._norm(c) for c in df.columns}
                def pick(row, *names):
                    for c, n in cmap.items():
                        if n in names:
                            v = row[c]
                            return None if str(v) == "nan" else v
                    return None
                cnt = 0
                for _, row in df.iterrows():
                    tb = pick(row, "tenbai", "tenbaiday", "bai", "noidung")
                    if not tb:
                        continue
                    db.execute("INSERT INTO ppct(teacher_id,khoi,mon,tuan,tiet_pp,ten_bai,ghi_chu) VALUES(?,?,?,?,?,?,?)",
                               (uid, pick(row, "khoi", "lop"), pick(row, "mon", "monhoc"),
                                pick(row, "tuan") or 1, pick(row, "tietppct", "tiet", "tietpp", "sotiet"),
                                tb, pick(row, "ghichu", "note")))
                    cnt += 1
                flash(f"Đã nhập {cnt} dòng PPCT", "ok")
        db.commit()
        return redirect(url_for("core.ppct", tuan=request.args.get("tuan", "")))
    tuan = request.args.get("tuan", "")
    q = "SELECT * FROM ppct WHERE teacher_id=?"
    p = [uid]
    if tuan:
        q += " AND tuan=?"; p.append(tuan)
    rows = db.execute(q + " ORDER BY tuan, mon, tiet_pp", p).fetchall()
    tuans = [r[0] for r in db.execute("SELECT DISTINCT tuan FROM ppct WHERE teacher_id=? ORDER BY tuan", (uid,))]
    return render_template("ppct.html", rows=rows, tuan=tuan, tuans=tuans)


# ---------------- TKB ----------------
@bp.route("/tkb", methods=["GET", "POST"])
@login_required
def tkb():
    db, uid = get_db(), session["uid"]
    if request.method == "POST":
        act = request.form.get("act")
        if act == "add":
            db.execute("INSERT INTO tkb(teacher_id,thu,buoi,tiet,lop,mon,phong) VALUES(?,?,?,?,?,?,?)",
                       (uid, request.form["thu"], request.form["buoi"], request.form["tiet"],
                        request.form["lop"], request.form["mon"], request.form.get("phong")))
        elif act == "del":
            db.execute("DELETE FROM tkb WHERE id=? AND teacher_id=?", (request.form["id"], uid))
        elif act == "clear":
            db.execute("DELETE FROM tkb WHERE teacher_id=?", (uid,))
        db.commit()
        return redirect(url_for("core.tkb"))
    rows = db.execute("SELECT * FROM tkb WHERE teacher_id=? ORDER BY thu, buoi DESC, tiet", (uid,)).fetchall()
    grid = {}
    for r in rows:
        grid.setdefault((r["buoi"], r["tiet"]), {})[r["thu"]] = r
    tiets = sorted({r["tiet"] for r in rows}) or [1, 2, 3, 4, 5]
    return render_template("tkb.html", rows=rows, grid=grid, tiets=tiets)


# ---------------- Lịch báo giảng ----------------
def _rows_for_week(uid, tuan, monday, offday=None):
    db = get_db()
    offday = offday or {}
    tkb = db.execute("SELECT * FROM tkb WHERE teacher_id=? ORDER BY thu, buoi DESC, tiet", (uid,)).fetchall()
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
        if nghi:
            # ngày nghỉ lễ: trả bài về lại kho để tuần/tiết sau dùng tiếp
            if bai:
                lst.insert(0, bai)
            out.append({"thu": t["thu"], "buoi": t["buoi"], "tiet": t["tiet"], "lop": t["lop"],
                        "mon": t["mon"], "ngay": ngay, "tiet_pp": "", "ten_bai": nghi,
                        "ghi_chu": "", "nghi": True})
            continue
        out.append({"thu": t["thu"], "buoi": t["buoi"], "tiet": t["tiet"], "lop": t["lop"],
                    "mon": t["mon"], "ngay": ngay,
                    "tiet_pp": bai["tiet_pp"] if bai else "", "ten_bai": bai["ten_bai"] if bai else "",
                    "ghi_chu": (bai["ghi_chu"] if bai else "") or (t["phong"] or ""), "nghi": False})
    return out


@bp.route("/bao-giang", methods=["GET", "POST"])
@login_required
def bao_giang():
    db, u = get_db(), current_user()
    tuan = max(1, int(request.values.get("tuan") or 1))

    # Ngày khai giảng (thứ Hai tuần 1) - lưu 1 lần, các tuần sau tự tính
    if request.values.get("tuan_1"):
        try:
            d0 = datetime.date.fromisoformat(request.values["tuan_1"])
            d0 -= datetime.timedelta(days=d0.weekday())      # ép về thứ Hai
            set_setting(f"tuan1_{u['id']}", d0.isoformat())
        except Exception:
            pass
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

    rows = _rows_for_week(session["uid"], tuan, monday, offday)
    meta = {"truong": request.values.get("truong") or u["school"] or "",
            "to": request.values.get("to", ""), "giao_vien": u["fullname"] or u["username"],
            "mon": request.values.get("mon") or u["subject"] or "",
            "tuan": tuan, "tu_ngay": monday.strftime("%d/%m/%Y"),
            "den_ngay": (monday + datetime.timedelta(days=6)).strftime("%d/%m/%Y"),
            "noi_dung_khac": request.values.get("noi_dung_khac", ""),
            "dia_danh": request.values.get("dia_danh", "Sóc Trăng"),
            "ngay_ky": monday.day, "thang_ky": monday.month, "nam_ky": monday.year}

    act = request.form.get("act") if request.method == "POST" else None
    if act in ("pdf", "word"):
        if not BL.can_use(u):
            return redirect(url_for("core.nang_cap", need=act))
        BL.consume(db, u, act, f"Lịch báo giảng tuần {tuan}")
        if act == "word":
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
    _, cal = LN.build_calendar(tuan1, breaks, max_hoc=max_tuan)
    da_xuat = {int(m.group(1)) for m in (re.match(r"Lịch báo giảng tuần (\d+)", r["detail"] or "")
               for r in db.execute("SELECT detail FROM usage_log WHERE teacher_id=? AND kind IN ('pdf','word')",
                                   (u["id"],))) if m}
    nghi_tuan_nay = LN.week_label(monday, breaks)
    meta["nghi"] = nghi_tuan_nay
    return render_template("baogiang.html", rows=rows, meta=meta, monday=monday, tuan=tuan,
                           tuans_pp=tuans_pp, max_tuan=max_tuan, tuan_now=tuan_now,
                           tuan1=tuan1, da_xuat=da_xuat, cal=cal, breaks=breaks,
                           nghi_tuan_nay=nghi_tuan_nay)


# ---------------- Nhận xét AI ----------------
@bp.route("/nhan-xet", methods=["GET", "POST"])
@login_required
def nhan_xet():
    db, uid = get_db(), session["uid"]
    result, cols = None, None
    if request.method == "POST":
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
    if not BL.can_use(u):
        return redirect(url_for("core.nang_cap", need="excel"))
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
    BL.consume(get_db(), u, "excel", f"Xuất {len(data)} nhận xét")
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
        ws.append(["Tuần", "Khối", "Môn", "Tiết PPCT", "Tên bài", "Ghi chú"])
        ws.append([1, "5", "Toán", 1, "Ôn tập số tự nhiên", "Bảng phụ"])
        ws.append([1, "5", "Toán", 2, "Ôn tập phân số", ""])
    for i, w in enumerate([26, 10, 14, 10, 12, 40], 1):
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
        db.execute("UPDATE teacher SET fullname=?,school=?,subject=?,phone=? WHERE id=?",
                   (request.form["fullname"], request.form["school"],
                    request.form["subject"], phone, session["uid"]))
        db.commit()
        flash("Đã lưu thông tin" + (" · Mã kích hoạt sẽ được nhắn tới " + SMS.mask(phone)
                                    if phone else ""), "ok")
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


# ---------------- Kiểm tra lỗi chính tả ----------------
_CT_DIR = os.path.join(os.environ.get("DB_DIR", "data"), "tmp")


def _ct_save(payload, data):
    """Lưu ngữ cảnh phiên chính tả ra đĩa (cookie chỉ giữ 1 token ngắn)."""
    os.makedirs(_CT_DIR, exist_ok=True)
    now = time.time()
    for fn in os.listdir(_CT_DIR):          # dọn file cũ > 2 giờ
        fp = os.path.join(_CT_DIR, fn)
        try:
            if now - os.path.getmtime(fp) > 7200:
                os.remove(fp)
        except OSError:
            pass
    tok = uuid.uuid4().hex
    with open(os.path.join(_CT_DIR, tok + ".json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    if data:
        with open(os.path.join(_CT_DIR, tok + ".docx"), "wb") as fh:
            fh.write(data)
    session["ct"] = tok
    return tok


def _ct_load():
    tok = session.get("ct")
    if not tok or not re.fullmatch(r"[0-9a-f]{32}", tok or ""):
        return None, None
    fj = os.path.join(_CT_DIR, tok + ".json")
    if not os.path.exists(fj):
        return None, None
    with open(fj, encoding="utf-8") as fh:
        ctx = json.load(fh)
    fd = os.path.join(_CT_DIR, tok + ".docx")
    return ctx, (fd if os.path.exists(fd) else None)

@bp.route("/chinh-ta", methods=["GET", "POST"])
@login_required
def chinh_ta():
    db, u = get_db(), current_user()
    if request.method == "POST":
        f = request.files.get("file")
        raw = request.form.get("noi_dung", "")
        opts = {"mat_dau": bool(request.form.get("mat_dau")),
                "lap_tu": bool(request.form.get("lap_tu"))}
        data, paras, name, src = None, [], "", "text"
        if f and f.filename:
            name = f.filename
            data = f.read()
            if name.lower().endswith(".docx"):
                try:
                    _, _, paras = DT.read_docx(data)
                    src = "docx"
                except Exception as e:
                    flash(f"Không đọc được file Word: {e}", "err")
                    return redirect(url_for("core.chinh_ta"))
            elif name.lower().endswith(".txt"):
                paras = data.decode("utf-8", "ignore").splitlines()
            else:
                flash("Chỉ hỗ trợ file .docx hoặc .txt", "err")
                return redirect(url_for("core.chinh_ta"))
        elif raw.strip():
            paras = raw.splitlines()
            name = "Văn bản nhập tay"
        else:
            flash("Vui lòng chọn file hoặc dán nội dung cần kiểm tra.", "err")
            return redirect(url_for("core.chinh_ta"))

        issues, stats = CT.check_text(paras, opts)
        _ct_save({"paras": paras, "issues": issues, "name": name, "src": src},
                 data if src == "docx" else None)
        return render_template("chinhta.html", issues=issues, stats=stats, paras=paras,
                               name=name, KIND=CT.KIND_LABEL, done=False)

    return render_template("chinhta.html", issues=None, KIND=CT.KIND_LABEL)


@bp.route("/chinh-ta/sua", methods=["POST"])
@login_required
def chinh_ta_sua():
    db, u = get_db(), current_user()
    ctx, fdocx = _ct_load()
    if not ctx:
        flash("Phiên làm việc đã hết hạn, vui lòng tải file lại.", "err")
        return redirect(url_for("core.chinh_ta"))
    chosen = request.form.getlist("fix")
    if not chosen:
        flash("Bạn chưa chọn lỗi nào để sửa.", "err")
        return redirect(url_for("core.chinh_ta"))
    if not BL.can_use(u):
        return redirect(url_for("core.nang_cap", need="chinhta"))

    BL.consume(db, u, "chinhta", f"Sửa {len(chosen)} lỗi — {ctx['name']}")
    issues = ctx["issues"]
    if ctx["src"] == "docx" and fdocx:
        with open(fdocx, "rb") as fh:
            bio, n = DT.apply_to_docx(fh.read(), issues, chosen)
        fname = (ctx["name"].rsplit(".", 1)[0] + "-da-sua.docx")
    else:
        newp = CT.apply_fixes(ctx["paras"], issues, chosen)
        bio = DT.make_docx_from_text(newp)
        fname = "van-ban-da-sua.docx"
    return send_file(bio, as_attachment=True, download_name=fname,
                     mimetype="application/vnd.openxmlformats-officedocument."
                              "wordprocessingml.document")


@bp.route("/chinh-ta/xem-truoc", methods=["POST"])
@login_required
def chinh_ta_xem():
    """Xem trước kết quả sau khi sửa (không tốn lượt)."""
    ctx, _ = _ct_load()
    if not ctx:
        return jsonify(ok=False, msg="Phiên đã hết hạn")
    chosen = request.get_json(force=True).get("ids", [])
    newp = CT.apply_fixes(ctx["paras"], ctx["issues"], chosen)
    return jsonify(ok=True, paras=newp)


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


@bp.route("/suc-khoe")
def suc_khoe():
    """Trang kiểm tra máy chủ còn sống — dùng cho UptimeRobot chống ngủ."""
    try:
        get_db().execute("SELECT 1").fetchone()
        return jsonify(ok=True, ten=CFG.get("SITE_NAME", "EduAssist"),
                       gio=datetime.datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        return jsonify(ok=False, loi=str(e)), 500

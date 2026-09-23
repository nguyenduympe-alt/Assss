"""Gửi lịch dạy hôm nay qua email — mỗi GV tối đa 1 lần/ngày lúc 6h sáng.

Mặc định tắt. Giáo viên bật ở Cài đặt. Cần email. Không gửi nếu đã gửi thành công trong ngày.
"""
import datetime
import logging
import os
import sqlite3
import sys

from . import lichnghi as LN
from . import mailer as MAIL
from . import tkb_phien as TP
from .pdf_bao_giang import THU_NAME
from ..db import DB_PATH

log = logging.getLogger("mail_lich")

LOAI = "mail_lich"
GIO_GUI = 6


def _int(v, mac=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return mac


def tuan1_gv(db, uid, today=None):
    today = today or datetime.date.today()
    r = db.execute("SELECT v FROM setting WHERE k=?", ("tuan1_%s" % uid,)).fetchone()
    s = r["v"] if r else ""
    if s:
        try:
            return datetime.date.fromisoformat(str(s)[:10])
        except Exception:
            pass
    return today - datetime.timedelta(days=today.weekday())


def tiet_hom_nay(db, uid, ngay=None):
    ngay = ngay or datetime.date.today()
    tuan1 = tuan1_gv(db, uid, ngay)
    nam = TP.nam_hoc_tu_ngay(tuan1)
    breaks = LN.get_breaks(db, uid)
    tuan = LN.current_week(tuan1, breaks, ngay)
    monday = LN.monday_of(ngay)
    nghi_tuan = LN.week_label(monday, breaks)
    nghi_ngay = LN.off_days(breaks).get(ngay)
    thu = ngay.weekday() + 2
    if nghi_tuan:
        return {"nghi": nghi_tuan, "tuan": 0, "thu": thu, "tiet": []}
    if nghi_ngay:
        return {"nghi": nghi_ngay, "tuan": tuan, "thu": thu, "tiet": []}
    if not tuan:
        tuan = 1
    rows = TP.dong(db, uid, nam, tuan) or []
    tiet = [r for r in rows if _int(r["thu"]) == thu]
    tiet.sort(key=lambda r: (0 if (r["buoi"] or "") == "Sáng" else 1, _int(r["tiet"]), r["lop"] or ""))
    return {"nghi": None, "tuan": tuan, "thu": thu, "tiet": tiet}


def _dong_tiet(r):
    tiet = _int(r["tiet"])
    lop = (r["lop"] or "").strip()
    mon = (r["mon"] or "").strip()
    phong = (r["phong"] or "").strip()
    p = "T%d" % tiet if tiet else "T?"
    if lop:
        p += " " + lop
    if mon:
        p += " " + mon
    if phong:
        p += " (P.%s)" % phong if not phong.lower().startswith("p") else " (%s)" % phong
    return p


def soan_tin(ngay, thong, ten=""):
    thu = THU_NAME.get(_int(thong.get("thu")), "")
    ngay_h = ngay.strftime("%d/%m/%Y")
    dau = "Lịch dạy %s" % ngay_h
    if thu:
        dau += " (%s" % thu
        if thong.get("tuan"):
            dau += ", tuần %s" % thong["tuan"]
        dau += ")"
    loi = ("Kính gửi thầy/cô%s." % ((" " + ten) if ten else ""))
    if thong.get("nghi"):
        return dau, "%s\nHôm nay nghỉ «%s». Không có tiết dạy.\n\nEduAssist" % (loi, thong["nghi"])
    tiet = list(thong.get("tiet") or [])
    if not tiet:
        return dau, "%s\nChưa có tiết trên thời khoá biểu hôm nay.\n\nEduAssist" % loi
    nhom, buoi_cu = [], None
    for r in tiet:
        b = (r["buoi"] or "Sáng").strip() or "Sáng"
        if b != buoi_cu:
            nhom.append((b, []))
            buoi_cu = b
        nhom[-1][1].append(_dong_tiet(r))
    dong = []
    for b, ds in nhom:
        dong.append("%s:\n  • %s" % (b, "\n  • ".join(ds)))
    than = "\n".join(dong)
    return dau, "%s\n\n%s\n\nTổng %d tiết. Chúc thầy/cô dạy tốt.\n\nEduAssist" % (loi, than, len(tiet))


def khoa_ngay(ngay):
    return "%s:%s" % (LOAI, ngay.isoformat())


def da_gui_hom_nay(db, uid, ngay):
    r = db.execute(
        "SELECT id FROM sms_log WHERE teacher_id=? AND loai=? AND ok=1",
        (uid, khoa_ngay(ngay))).fetchone()
    return bool(r)


def ds_gv_bat(db):
    try:
        return db.execute(
            "SELECT id, fullname, username, email, COALESCE(mail_lich,0) mail_lich "
            "FROM teacher WHERE COALESCE(mail_lich,0)=1").fetchall()
    except sqlite3.OperationalError:
        return []


def _cot(gv, ten, mac=None):
    try:
        v = gv[ten]
        return mac if v is None else v
    except (KeyError, IndexError, TypeError):
        return mac


def gui_mot(db, gv, ngay=None, bat_buoc=False, loai=None):
    ngay = ngay or datetime.date.today()
    loai = loai or LOAI
    uid = gv["id"]
    if not bat_buoc and not _int(_cot(gv, "mail_lich", 0)):
        return "bo_qua", "Chưa bật nhận lịch email"
    email = MAIL.chuan(_cot(gv, "email"))
    if not email:
        return "bo_qua", "Chưa có email"
    if loai == LOAI:
        loai = khoa_ngay(ngay)
    if not bat_buoc and str(loai).startswith(LOAI + ":") and da_gui_hom_nay(db, uid, ngay):
        return "bo_qua", "Đã gửi hôm nay"
    thong = tiet_hom_nay(db, uid, ngay)
    tieu, text = soan_tin(ngay, thong, _cot(gv, "fullname") or "")
    html = "<p>%s</p>" % text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>\n")
    ok, msg = MAIL.send(email, tieu, text, html=html, db=db, teacher_id=uid, loai=loai)
    return ("gui" if ok else "loi"), msg


def chay(db=None, ngay=None, bat_buoc=False):
    ngay = ngay or datetime.date.today()
    tu_dong = db is None
    if tu_dong:
        db = sqlite3.connect(DB_PATH, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=30000")
        try:
            from . import config as CFG
            CFG.nap(db)
        except Exception:
            pass
    tk = {"gui": 0, "bo_qua": 0, "loi": 0, "chi_tiet": []}
    try:
        for gv in ds_gv_bat(db):
            st, msg = gui_mot(db, gv, ngay, bat_buoc=bat_buoc)
            tk[st] = tk.get(st, 0) + 1
            tk["chi_tiet"].append({"id": gv["id"], "st": st, "msg": msg})
            log.info("mail_lich gv=%s %s %s", gv["id"], st, msg)
        if tu_dong:
            db.commit()
    finally:
        if tu_dong:
            db.close()
    return tk


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    bat_buoc = "--lai" in argv
    goc = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    if goc not in sys.path:
        sys.path.insert(0, goc)
    os.chdir(goc)
    from app import create_app
    app = create_app()
    with app.app_context():
        from ..db import get_db
        tk = chay(get_db(), bat_buoc=bat_buoc)
        get_db().commit()
    print("mail_lich %s gui=%s bo_qua=%s loi=%s" % (
        datetime.date.today().isoformat(), tk["gui"], tk["bo_qua"], tk["loi"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

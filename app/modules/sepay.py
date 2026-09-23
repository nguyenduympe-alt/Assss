"""Thanh toán chuyển khoản SePay: đơn duy nhất + khớp đúng số tiền + webhook.

Số tiền QR lấy billing.gia_hien (gốc hoặc KM còn hạn). Không đổi quyền lợi gói (LUOT_MOI_GOI, redeem).
Khoá xác thực CHỈ đọc từ biến môi trường — không ghi CSDL, không đưa ra giao diện.
Khi chưa đặt SEPAY_API_KEY, endpoint từ chối (chưa bật nhận giao dịch thật).
Tiền tố mã đơn mặc định EGV (2–5 chữ, cấu hình được trên trang admin).
Không gửi SMS.
"""
import datetime
import hmac
import os
import re
import sqlite3
import secrets
import logging
from decimal import Decimal, InvalidOperation

from . import billing as BL
from . import config as CFG

log = logging.getLogger("sepay")

TIEN_TO = "EGV"  # mặc định; runtime dùng tien_to() (admin có thể đổi 2–5 chữ).

# Bí danh khớp CHÍNH XÁC với trường gateway SePay — không dùng substring.
NH_BI_DANH = {
    "agribank": {"agribank"},
    "vietcombank": {"vietcombank", "vcb"},
    "vietinbank": {"vietinbank", "ctg"},
    "bidv": {"bidv"},
    "mbbank": {"mbbank"},
    "techcombank": {"techcombank", "tcb"},
    "acb": {"acb"},
    "vpbank": {"vpbank"},
    "tpbank": {"tpbank"},
    "sacombank": {"sacombank", "stb"},
}


def api_key():
    return (os.environ.get("SEPAY_API_KEY") or "").strip()


def da_bat():
    return bool(api_key())


def tien_to():
    """Tiền tố mã đơn: 2–5 chữ in hoa. Mặc định EGV."""
    raw = str(CFG.get("SEPAY_TIEN_TO", TIEN_TO) or TIEN_TO).strip().upper()
    raw = re.sub(r"[^A-Z]", "", raw)
    if 2 <= len(raw) <= 5:
        return raw
    return TIEN_TO


def re_ma():
    """Đúng {tiền tố} + 8 chữ số; ranh giới hai đầu không phải chữ/số."""
    p = re.escape(tien_to())
    return re.compile(r"(?<![A-Z0-9])%s\s*(\d{8})(?![A-Z0-9])" % p, re.I)


def ttl_phut():
    try:
        n = int(CFG.get("SEPAY_ORDER_TTL_MIN") or "1440")
    except Exception:
        n = 1440
    return max(5, min(n, 60 * 24 * 14))


def tinh_trang():
    """Thông tin hiện lên trang admin — không gồm khoá."""
    tt = tien_to()
    return {
        "bat": da_bat(),
        "tien_to": tt,
        "mau": tt + "12345678",
        "tk": so_tk_nhan(),
        "nh": ten_nh(),
        "ma_nh": ma_nh(),
        "chu": chu_tk(),
        "ttl": ttl_phut(),
        "gateway": (CFG.get("SEPAY_GATEWAY") or "").strip(),
    }


def _chi_so(s):
    return re.sub(r"\D+", "", str(s or ""))


def so_tk_nhan():
    override = _chi_so(CFG.get("SEPAY_ACCOUNT") or "")
    return override or _chi_so(CFG.get("BANK_ACC", BL.BANK_ACC))


def ten_nh():
    return (CFG.get("BANK_NAME", BL.BANK_NAME) or "").strip()


def ma_nh():
    return (CFG.get("BANK_CODE", BL.BANK_CODE) or "").strip()


def chu_tk():
    return (CFG.get("BANK_OWNER", BL.BANK_OWNER) or "").strip()


def _gon_nh(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def khop_ngan_hang(gateway):
    """Khớp gateway SePay với ngân hàng cấu hình: bí danh chính xác, không substring.

    Nếu đặt SEPAY_GATEWAY thì chỉ nhận đúng giá trị đó. Không nhận tên một chữ.
    """
    g = _gon_nh(gateway)
    if len(g) < 2:
        return False
    env = _gon_nh(CFG.get("SEPAY_GATEWAY") or "")
    if env:
        return g == env
    tap = set()
    ma, ten = _gon_nh(ma_nh()), _gon_nh(ten_nh())
    for khoa in (ma, ten):
        if not khoa or len(khoa) < 2:
            continue
        tap.add(khoa)
        tap |= NH_BI_DANH.get(khoa, set())
        for goc, ds in NH_BI_DANH.items():
            if khoa == goc or khoa in ds:
                tap.add(goc)
                tap |= ds
    tap = {x for x in tap if len(x) >= 2}
    return g in tap


def check_auth(headers):
    if not da_bat():
        return False, 503, "Chưa bật nhận giao dịch SePay"
    auth = ""
    try:
        auth = headers.get("Authorization") or ""
    except Exception:
        auth = ""
    got = ""
    low = auth[:16].lower()
    if low.startswith("apikey "):
        got = auth.split(" ", 1)[1].strip()
    elif low.startswith("bearer "):
        got = auth.split(" ", 1)[1].strip()
    if not got:
        return False, 401, "Thiếu Authorization"
    if not hmac.compare_digest(got, api_key()):
        return False, 401, "Sai Authorization"
    return True, 200, ""


def gia_goi(goi):
    goi = "luot" if goi == "luot" else "vip"
    return int(BL.gia_hien(goi)["gia"]), goi


def _tao_ma(db):
    for _ in range(40):
        ma = tien_to() + "%08d" % secrets.randbelow(100000000)
        if ma.endswith("00000000"):
            continue
        if not db.execute("SELECT 1 FROM don_hang WHERE ma=?", (ma,)).fetchone():
            return ma
    raise RuntimeError("Không sinh được mã đơn duy nhất")


def tao_hoac_lay(db, teacher_id, goi="vip"):
    so_tien, goi = gia_goi(goi)
    now = datetime.datetime.now()
    now_s = now.isoformat(timespec="seconds")
    hang = db.execute(
        "SELECT * FROM don_hang WHERE teacher_id=? AND goi=? AND trang_thai='cho' "
        "AND het_han>=? AND so_tien=? ORDER BY id DESC LIMIT 1",
        (teacher_id, goi, now_s, so_tien)).fetchone()
    if hang:
        return dict(hang)
    ma = _tao_ma(db)
    het = (now + datetime.timedelta(minutes=ttl_phut())).isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO don_hang(ma,teacher_id,goi,so_tien,trang_thai,het_han,created) "
        "VALUES(?,?,?,?,?,?,?)",
        (ma, teacher_id, goi, so_tien, "cho", het, now_s))
    db.commit()
    return dict(db.execute("SELECT * FROM don_hang WHERE ma=?", (ma,)).fetchone())


def don_cua_toi(db, teacher_id, goi=None, ma=None):
    """Chỉ đơn của teacher_id. Nếu có ma: đúng mã đó, không trả đơn cũ khác."""
    if ma:
        ma = str(ma).strip().upper()
        r = db.execute("SELECT * FROM don_hang WHERE teacher_id=? AND ma=?",
                       (teacher_id, ma)).fetchone()
        return dict(r) if r else None
    q = "SELECT * FROM don_hang WHERE teacher_id=?"
    p = [teacher_id]
    if goi in ("vip", "luot"):
        q += " AND goi=?"
        p.append(goi)
    q += " ORDER BY id DESC LIMIT 1"
    r = db.execute(q, p).fetchone()
    return dict(r) if r else None


def ds_ma_don(text):
    """Danh sách mã {tiền tố}+8 số (chuẩn hoá, không trùng thứ tự)."""
    ra, seen = [], set()
    tt = tien_to()
    for m in re_ma().finditer(str(text or "").upper()):
        ma = tt + m.group(1)
        if ma not in seen:
            seen.add(ma)
            ra.append(ma)
    return ra


def la_ma_don(text):
    return bool(ds_ma_don(text))


def lay_ma(data):
    """Trả (ma, loi). loi set thì từ chối: nhiều mã, code ≠ content, không đúng tiền tố+8."""
    if not isinstance(data, dict):
        return "", "sai_ma"
    content = str(data.get("content") or "")
    ds_ct = ds_ma_don(content)
    code_raw = data.get("code")
    co_code = code_raw is not None and str(code_raw).strip() not in ("", "null", "None")
    if co_code:
        ds_cd = ds_ma_don(str(code_raw))
        if len(ds_cd) != 1:
            return "", "sai_ma"
        if ds_ct and (len(ds_ct) != 1 or ds_ct[0] != ds_cd[0]):
            return "", "sai_ma"
        if len(ds_ct) > 1:
            return "", "sai_ma"
        return ds_cd[0], ""
    if len(ds_ct) == 1:
        return ds_ct[0], ""
    return "", "sai_ma"


def so_tien_vnd(v):
    """Số tiền VND: nguyên dương chính xác. Không abs, không int(float), từ chối bool/lẻ/NaN/Inf/âm."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, float):
        return None
    if isinstance(v, int):
        return v if v > 0 else None
    s = str(v).strip()
    if not s or s.lower() in ("nan", "inf", "-inf", "+inf", "true", "false"):
        return None
    if any(ch in s for ch in "eE+"):
        return None
    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError):
        return None
    if d.is_nan() or d.is_infinite() or d <= 0:
        return None
    if d != d.to_integral_value():
        return None
    n = int(d)
    if Decimal(n) != d:
        return None
    return n


def _sepay_id(data):
    v = data.get("id") if isinstance(data, dict) else None
    if v is None or isinstance(v, bool) or str(v).strip() == "":
        return ""
    return str(v).strip()


def _ghi_tx(db, gd, kq):
    now = datetime.datetime.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT OR IGNORE INTO bank_tx(ref,noi_dung,so_tien,loai,ngay,nguon,teacher_id,"
        "goi,code,trang_thai,ghi_chu,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (gd["ref"], gd.get("noi_dung") or "", gd.get("so_tien") or 0, gd.get("loai") or "",
         gd.get("ngay") or now, "sepay", kq.get("teacher_id"), kq.get("goi"),
         kq.get("code"), kq.get("trang_thai"), (kq.get("ghi_chu") or "")[:500], now))


def _kich_hoat(db, u, goi):
    luot = BL.LUOT_MOI_GOI if goi == "luot" else 0
    note = "SePay — đơn đối soát tự động"
    code = BL.create_codes(db, 1, 12 if goi == "vip" else 0, note, goi, luot, commit=False)[0]
    ok, msg = BL.redeem(db, u, code, commit=False)
    if not ok:
        raise RuntimeError("Không cấp được quyền lợi gói")
    return msg, code


def _ket_thuc_nghiep_vu(db, gd, kq, sid):
    """Ghi log + hoá đơn, COMMIT. Không đổi trạng thái đơn chờ (thiếu/thừa tiền, sai mã…)."""
    db.execute("UPDATE sepay_log SET kq=? WHERE sepay_id=?", ((kq.get("ghi_chu") or "")[:300], sid))
    _ghi_tx(db, gd, kq)
    db.commit()
    return kq


def xu_ly(db, data, _truot=None):
    """Idempotent theo id SePay. Giao dịch nguyên tử: lỗi → rollback hết, caller trả 500."""
    kq = {"trang_thai": "bo_qua", "ghi_chu": "", "teacher_id": None, "goi": None,
          "code": None, "vip": False, "sepay_id": ""}
    if not isinstance(data, dict):
        kq["ghi_chu"] = "Payload không hợp lệ"
        return kq

    sid = _sepay_id(data)
    kq["sepay_id"] = sid
    if not sid:
        kq["ghi_chu"] = "Thiếu id giao dịch SePay"
        return kq

    now = datetime.datetime.now()
    now_s = now.isoformat(timespec="seconds")
    noi = str(data.get("content") or "")
    ttype = str(data.get("transferType") if data.get("transferType") is not None else "").strip().lower()
    ngay = str(data.get("transactionDate") or now_s)
    tk = _chi_so(data.get("accountNumber") or "")
    gd = {"ref": "sepay-" + sid, "noi_dung": noi, "so_tien": 0, "loai": ttype,
          "ngay": ngay, "tk": tk}

    try:
        db.rollback()
    except Exception:
        pass
    db.execute("BEGIN IMMEDIATE")
    try:
        try:
            db.execute("INSERT INTO sepay_log(sepay_id,payload,kq,created) VALUES(?,?,?,?)",
                       (sid, str({k: data.get(k) for k in ("id", "transferType", "transferAmount",
                                                           "accountNumber", "gateway", "code",
                                                           "content")})[:1500], "", now_s))
        except sqlite3.IntegrityError:
            hang = db.execute("SELECT kq FROM sepay_log WHERE sepay_id=?", (sid,)).fetchone()
            db.commit()
            kq["trang_thai"] = "trung"
            kq["ghi_chu"] = (hang["kq"] if hang and hang["kq"] else "Giao dịch đã xử lý trước đó")
            return kq

        if _truot == "sau_log":
            raise RuntimeError("SEPAY_TEST_TRUOT")

        if ttype != "in":
            kq["ghi_chu"] = "Không phải tiền vào — không cấp VIP"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        amt = so_tien_vnd(data.get("transferAmount"))
        if amt is None:
            kq["ghi_chu"] = "Số tiền không hợp lệ — không cấp VIP"
            kq["trang_thai"] = "sai_tien"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)
        gd["so_tien"] = amt

        if not khop_ngan_hang(data.get("gateway")):
            kq["ghi_chu"] = "Sai ngân hàng (gateway) — không cấp VIP"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        tk_chuan = so_tk_nhan()
        if not tk_chuan or tk != tk_chuan:
            kq["ghi_chu"] = "Sai tài khoản nhận tiền — không cấp VIP"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        ma, loi_ma = lay_ma(data)
        if loi_ma or not ma:
            kq["trang_thai"] = "sai_ma"
            kq["ghi_chu"] = "Sai mã đơn — không cấp VIP"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        don = db.execute("SELECT * FROM don_hang WHERE ma=?", (ma,)).fetchone()
        if not don:
            kq["trang_thai"] = "sai_ma"
            kq["ghi_chu"] = "Sai mã đơn — không khớp đơn nào"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)
        don = dict(don)
        kq["teacher_id"] = don["teacher_id"]
        kq["goi"] = don["goi"]

        if don["trang_thai"] == "da_thanh_toan":
            kq["trang_thai"] = "trung"
            kq["ghi_chu"] = "Đơn đã thanh toán trước đó"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        if (don.get("het_han") or "") < now_s:
            kq["trang_thai"] = "het_han"
            kq["ghi_chu"] = "Đơn hết hạn — không cấp VIP"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        if amt != int(don["so_tien"] or 0):
            # Thiếu/thừa: chỉ log đối soát, GIỮ đơn chờ để lần CK đúng còn xử lý được.
            kq["trang_thai"] = "doi_soat"
            kq["ghi_chu"] = "Số tiền không khớp đơn — chờ đối soát, không cấp VIP"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        cur = db.execute(
            "UPDATE don_hang SET trang_thai='da_thanh_toan', sepay_id=?, paid_at=? "
            "WHERE ma=? AND trang_thai='cho' AND so_tien=? AND het_han>=?",
            (sid, now_s, ma, int(don["so_tien"]), now_s))
        if cur.rowcount != 1:
            kq["trang_thai"] = "trung"
            kq["ghi_chu"] = "Đơn đã được xử lý bởi lần nhận khác"
            return _ket_thuc_nghiep_vu(db, gd, kq, sid)

        if _truot == "sau_claim":
            raise RuntimeError("SEPAY_TEST_TRUOT")

        u = db.execute("SELECT * FROM teacher WHERE id=?", (don["teacher_id"],)).fetchone()
        if not u:
            raise RuntimeError("Không tìm thấy tài khoản gắn đơn")

        msg, code = _kich_hoat(db, u, don["goi"])
        kq["code"] = code
        kq["ghi_chu"] = msg
        kq["trang_thai"] = "da_kich_hoat"
        kq["vip"] = don["goi"] == "vip"
        db.execute("UPDATE sepay_log SET kq=? WHERE sepay_id=?", ((msg or "")[:300], sid))
        _ghi_tx(db, gd, kq)
        if _truot == "sau_quyen":
            raise RuntimeError("SEPAY_TEST_TRUOT")
        db.commit()
        return kq
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise

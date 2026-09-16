"""Nhận và xử lý giao dịch chuyển khoản tự động (SePay / Casso / SMS forwarder).

Luồng:
  Ngân hàng -> SePay|Casso phát hiện tiền vào -> gọi webhook POST /webhook/bank
  -> chuẩn hoá dữ liệu -> tách mã EDU0007 trong nội dung CK -> khớp giáo viên
  -> đối chiếu số tiền -> tạo mã kích hoạt (hoặc cộng lượt thẳng) -> nhắn tin SMS.

Bật bằng biến môi trường:
    BANK_WEBHOOK_TOKEN   khoá bí mật, bắt buộc, để chặn người lạ gọi webhook
    BANK_PROVIDER        sepay | casso | sms | auto (mặc định auto - tự nhận dạng)
    AUTO_ACTIVATE        1 = cộng lượt/VIP thẳng vào tài khoản (mặc định)
                         0 = chỉ sinh mã, giáo viên tự nhập
"""
import os
import re
import json
import hmac
import hashlib
import datetime
import logging

from . import billing as BL
from . import sms as SMS
from . import config as CFG

log = logging.getLogger("bank")


def __getattr__(name):
    """Đọc cấu hình mới nhất (admin sửa được trên web)."""
    if name == "WEBHOOK_TOKEN":
        return CFG.get("BANK_WEBHOOK_TOKEN", "")
    if name == "PROVIDER":
        return CFG.get("BANK_PROVIDER", "auto")
    if name == "AUTO_ACTIVATE":
        return CFG.get_bool("AUTO_ACTIVATE", True)
    if name == "SAI_SO":
        return CFG.get_int("BANK_SAI_SO", 0)
    raise AttributeError(name)


# ---------------- Xác thực ----------------
def check_auth(headers, raw_body=b""):
    """Kiểm tra webhook có đúng là của mình không."""
    WEBHOOK_TOKEN = CFG.get("BANK_WEBHOOK_TOKEN", "")
    if not WEBHOOK_TOKEN:
        return False, ("Chưa bật đối soát tự động — vào Cài đặt hệ thống "
                       "để sinh khoá bí mật webhook")
    # SePay: Authorization: Apikey <token>
    auth = headers.get("Authorization", "") or ""
    if auth.startswith("Apikey "):
        return (hmac.compare_digest(auth[7:].strip(), WEBHOOK_TOKEN),
                "Sai Apikey")
    if auth.startswith("Bearer "):
        return (hmac.compare_digest(auth[7:].strip(), WEBHOOK_TOKEN), "Sai Bearer token")
    # Casso: Secure-Token: <token>
    for h in ("Secure-Token", "X-Secure-Token", "X-Webhook-Token", "X-Api-Key"):
        v = headers.get(h)
        if v:
            return hmac.compare_digest(v.strip(), WEBHOOK_TOKEN), f"Sai {h}"
    # Chữ ký HMAC-SHA256 toàn thân request (một số dịch vụ dùng)
    sig = headers.get("X-Signature") or headers.get("X-Hub-Signature-256")
    if sig and raw_body:
        calc = hmac.new(WEBHOOK_TOKEN.encode(), raw_body, hashlib.sha256).hexdigest()
        sig = sig.split("=")[-1].strip()
        return hmac.compare_digest(calc, sig), "Sai chữ ký"
    return False, "Thiếu thông tin xác thực (Authorization / Secure-Token)"


# ---------------- Chuẩn hoá dữ liệu từ nhiều nguồn ----------------
def _num(v):
    try:
        return int(float(str(v).replace(",", "").replace(" ", "") or 0))
    except Exception:
        return 0


def parse_payload(data):
    """Trả về danh sách giao dịch đã chuẩn hoá, bất kể nguồn nào.

    Mỗi giao dịch: {ref, noi_dung, so_tien, loai, ngay, tk, nguon}
    loai='in' là tiền vào, 'out' là tiền ra (bỏ qua).
    """
    out = []
    if not isinstance(data, dict):
        return out

    # --- Casso: {"error":0,"data":[{...}]} ---
    items = None
    if isinstance(data.get("data"), list):
        items = data["data"]
    elif isinstance(data.get("transactions"), list):
        items = data["transactions"]
    else:
        items = [data]                      # SePay gửi 1 giao dịch/lần

    for it in items:
        if not isinstance(it, dict):
            continue
        # số tiền: SePay dùng transferAmount + transferType; Casso dùng amount (âm = tiền ra)
        amt = it.get("transferAmount", it.get("amount", it.get("so_tien", 0)))
        amt = _num(amt)
        ttype = (it.get("transferType") or "").lower()
        if ttype == "out" or amt < 0:
            loai = "out"
        elif ttype == "in" or amt > 0:
            loai = "in"
        else:
            loai = "in"
        noi_dung = (it.get("content") or it.get("description") or it.get("noi_dung")
                    or it.get("body") or it.get("message") or "")
        ref = str(it.get("referenceCode") or it.get("reference_number") or it.get("tid")
                  or it.get("id") or it.get("ref") or "")
        ngay = (it.get("transactionDate") or it.get("when") or it.get("ngay")
                or datetime.datetime.now().isoformat(timespec="seconds"))
        tk = (it.get("accountNumber") or it.get("subAccId") or it.get("account_number") or "")
        nguon = (it.get("gateway") or it.get("bank_name") or data.get("provider")
                 or CFG.get("BANK_PROVIDER", "auto"))
        if not ref:
            # không có mã giao dịch thì tự tạo khoá chống trùng từ nội dung
            ref = hashlib.md5(f"{noi_dung}|{amt}|{ngay}".encode()).hexdigest()[:20]
        out.append({"ref": ref, "noi_dung": str(noi_dung), "so_tien": abs(amt),
                    "loai": loai, "ngay": str(ngay), "tk": str(tk), "nguon": str(nguon)})
    return out


# ---------------- Bóc mã tham chiếu & gói ----------------
# Mã tham chiếu có dạng EDU + 4 chữ số (billing.ref_code dùng zfill(4)).
# Khó ở chỗ ngân hàng hay ghi liền: "EDU00053LUOT" = EDU0005 + 3LUOT.
RE_REF = re.compile(r"EDU\s*(\d{1,7})\s*(LUOT|NAM|VIP)?", re.I)
RE_GOI = re.compile(r"(LUOT|NAM|VIP)", re.I)


def tach_ma(noi_dung):
    """'CT DEN:... EDU0007 3LUOT' -> (7, 'luot'). Không thấy -> (None, None)."""
    if not noi_dung:
        return None, None
    # ngân hàng hay chèn dấu chấm/gạch, chuẩn hoá về chữ và số
    s = re.sub(r"[^A-Za-z0-9]+", " ", str(noi_dung)).upper()
    flat = s.replace(" ", "")

    # Ưu tiên bản CÒN khoảng trắng: "EDU7 3LUOT" / "EDU12345 LUOT" thì số mã đã rõ ràng,
    # chỉ cần chắc chắn hậu tố không dính liền số (kiểm tra bằng regex có neo \s+).
    m = re.search(r"EDU\s*(\d{1,7})(?:\s+|$)", s, re.I)
    if m:
        so = m.group(1)
    else:
        m = RE_REF.search(flat)
        if not m:
            return None, None
        so, hau_to = m.group(1), (m.group(2) or "")
        # Ghi liền kiểu "EDU0005" + "3LUOT": chữ số cuối thực ra là số gói,
        # cắt ra để phần còn lại đủ 4 chữ số của mã tài khoản.
        if hau_to in ("LUOT", "NAM") and len(so) > 4:
            so = so[:-1]

    tid = int(so)

    goi = None
    g = RE_GOI.search(flat)
    if g:
        goi = "vip" if g.group(1) in ("NAM", "VIP") else "luot"
    return tid, goi


def doan_goi_theo_tien(so_tien):
    """Không ghi rõ gói thì suy ra từ số tiền."""
    sai_so = CFG.get_int("BANK_SAI_SO", 0)
    if so_tien >= BL.PRICE - sai_so:
        return "vip"
    if so_tien >= BL.PRICE_LUOT - sai_so:
        return "luot"
    return None


def so_goi_le(so_tien):
    """Chuyển 30.000đ thành 3 gói lẻ = 9 lượt."""
    if BL.PRICE_LUOT <= 0:
        return 1
    return max(1, so_tien // BL.PRICE_LUOT)


# ---------------- Xử lý 1 giao dịch ----------------
def xu_ly(db, gd):
    """Xử lý 1 giao dịch đã chuẩn hoá. Trả về dict kết quả để ghi nhật ký."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    kq = {"ref": gd["ref"], "so_tien": gd["so_tien"], "noi_dung": gd["noi_dung"],
          "trang_thai": "bo_qua", "ghi_chu": "", "teacher_id": None, "code": None}

    if gd["loai"] != "in":
        kq["ghi_chu"] = "Giao dịch tiền ra, bỏ qua"
        return _ghi(db, kq, gd, now)

    # chống xử lý trùng (dịch vụ có thể gọi lại webhook nhiều lần)
    if db.execute("SELECT 1 FROM bank_tx WHERE ref=?", (gd["ref"],)).fetchone():
        kq["trang_thai"] = "trung"
        kq["ghi_chu"] = "Giao dịch đã xử lý trước đó"
        return kq

    tid, goi = tach_ma(gd["noi_dung"])
    if not tid:
        kq["ghi_chu"] = "Nội dung chuyển khoản không có mã EDUxxxx — cần đối soát tay"
        kq["trang_thai"] = "cho_doi_soat"
        return _ghi(db, kq, gd, now)

    u = db.execute("SELECT * FROM teacher WHERE id=?", (tid,)).fetchone()
    if not u:
        kq["ghi_chu"] = f"Không tìm thấy tài khoản EDU{str(tid).zfill(4)}"
        kq["trang_thai"] = "cho_doi_soat"
        return _ghi(db, kq, gd, now)
    kq["teacher_id"] = tid

    goi = goi or doan_goi_theo_tien(gd["so_tien"])
    if not goi:
        kq["ghi_chu"] = (f"Số tiền {gd['so_tien']:,}đ nhỏ hơn gói rẻ nhất "
                         f"({BL.PRICE_LUOT:,}đ) — cần đối soát tay")
        kq["trang_thai"] = "cho_doi_soat"
        return _ghi(db, kq, gd, now)

    # đối chiếu số tiền với gói ghi trong nội dung
    can = BL.PRICE if goi == "vip" else BL.PRICE_LUOT
    if gd["so_tien"] + CFG.get_int("BANK_SAI_SO", 0) < can:
        # chuyển thiếu: hạ xuống gói thấp hơn nếu đủ, không thì chờ đối soát
        if goi == "vip" and gd["so_tien"] + CFG.get_int("BANK_SAI_SO", 0) >= BL.PRICE_LUOT:
            goi = "luot"
        else:
            kq["ghi_chu"] = (f"Chuyển thiếu: nhận {gd['so_tien']:,}đ, gói yêu cầu {can:,}đ")
            kq["trang_thai"] = "cho_doi_soat"
            return _ghi(db, kq, gd, now)

    # số lượt: chuyển 30k thì cộng 9 lượt
    luot = BL.LUOT_MOI_GOI * so_goi_le(gd["so_tien"]) if goi == "luot" else 0
    kq["goi"] = goi
    kq["luot"] = luot

    note = f"Tự động — CK {gd['so_tien']:,}đ · {gd['ref']} · {gd['noi_dung'][:60]}"
    code = BL.create_codes(db, 1, 12 if goi == "vip" else 0, note, goi, luot)[0]
    kq["code"] = code

    het_han = ""
    if CFG.get_bool("AUTO_ACTIVATE", True):
        ok, msg = BL.redeem(db, u, code)
        kq["trang_thai"] = "da_kich_hoat" if ok else "cho_doi_soat"
        kq["ghi_chu"] = msg
        u = db.execute("SELECT * FROM teacher WHERE id=?", (tid,)).fetchone()
        if goi == "vip" and u["expires"]:
            het_han = datetime.date.fromisoformat(u["expires"]).strftime("%d/%m/%Y")
    else:
        kq["trang_thai"] = "da_tao_ma"
        kq["ghi_chu"] = "Đã tạo mã, chờ giáo viên tự nhập"
        het_han = (datetime.date.today() + datetime.timedelta(days=365)).strftime("%d/%m/%Y")

    # ---- gửi tin nhắn ----
    phone = None
    try:
        phone = u["phone"]
    except (KeyError, IndexError):
        phone = None
    if phone:
        if CFG.get_bool("AUTO_ACTIVATE", True):
            text = SMS.mau_da_kich_hoat(goi, luot, het_han)
        else:
            text = SMS.mau_ma_kich_hoat(code, goi, luot, het_han)
        ok, msg = SMS.send(phone, text, db=db, teacher_id=tid, loai="kich_hoat")
        kq["sms"] = msg
    else:
        kq["sms"] = "Tài khoản chưa khai số điện thoại — không gửi được tin nhắn"

    return _ghi(db, kq, gd, now)


def _ghi(db, kq, gd, now):
    db.execute(
        "INSERT OR IGNORE INTO bank_tx(ref,noi_dung,so_tien,loai,ngay,nguon,teacher_id,"
        "goi,code,trang_thai,ghi_chu,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (gd["ref"], gd["noi_dung"], gd["so_tien"], gd["loai"], gd["ngay"], gd["nguon"],
         kq.get("teacher_id"), kq.get("goi"), kq.get("code"), kq["trang_thai"],
         (kq.get("ghi_chu", "") + (" | SMS: " + kq["sms"] if kq.get("sms") else ""))[:500],
         now))
    db.commit()
    return kq


def xu_ly_tat_ca(db, data):
    return [xu_ly(db, gd) for gd in parse_payload(data)]

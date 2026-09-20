"""Cổng gửi tin nhắn đa nhà cung cấp (SMS brandname / Zalo ZNS).

Bật bằng biến môi trường SMS_PROVIDER:
    log      - chỉ ghi ra log + CSDL, không gửi thật (mặc định, dùng để chạy thử)
    esms     - eSMS.vn        (ESMS_API_KEY, ESMS_SECRET_KEY, ESMS_BRANDNAME)
    speedsms - SpeedSMS.vn    (SPEEDSMS_TOKEN, SPEEDSMS_SENDER)
    twilio   - Twilio         (TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM)
    zns      - Zalo ZNS       (ZNS_ACCESS_TOKEN, ZNS_TEMPLATE_ID)
    zns,esms - thử lần lượt, cái nào thành công thì dừng

Thêm nhà cung cấp mới: viết 1 hàm _send_xxx(phone, text, **kw) trả về
(ok, thông_điệp) rồi khai báo vào PROVIDERS.
"""
import os
import re
import json
import logging

from . import config as CFG

log = logging.getLogger("sms")


def __getattr__(name):
    """Đọc cấu hình mới nhất (admin sửa được trên web)."""
    if name == "PROVIDER":
        return CFG.get("SMS_PROVIDER", "log")
    if name == "TIMEOUT":
        return CFG.get_int("SMS_TIMEOUT", 15)
    raise AttributeError(name)


def _tg():
    return CFG.get_int("SMS_TIMEOUT", 15)


# ---------------- Chuẩn hoá số điện thoại Việt Nam ----------------
def normalize(phone):
    """0912345678 / +84912345678 / 84912345678 -> 0912345678. Sai -> None."""
    if not phone:
        return None
    p = re.sub(r"[^\d+]", "", str(phone))
    if p.startswith("+84"):
        p = "0" + p[3:]
    elif p.startswith("84") and len(p) >= 11:
        p = "0" + p[2:]
    if not p.startswith("0"):
        p = "0" + p
    # di động VN: 10 số, đầu 03/05/07/08/09
    if re.fullmatch(r"0(3|5|7|8|9)\d{8}", p):
        return p
    # cố định 10-11 số vẫn cho qua (phòng trường hợp đặc biệt)
    if re.fullmatch(r"0\d{9,10}", p):
        return p
    return None


def to_e164(phone):
    p = normalize(phone)
    return "+84" + p[1:] if p else None


def mask(phone):
    """Che bớt số khi hiển thị: 0912345678 -> 0912***678"""
    p = normalize(phone) or str(phone or "")
    return p[:4] + "***" + p[-3:] if len(p) >= 9 else p


# ---------------- Các nhà cung cấp ----------------
def _requests():
    import requests
    return requests


def _send_log(phone, text, **kw):
    """Chế độ chạy thử: không gửi thật, chỉ ghi log."""
    log.info("[SMS-GIẢ LẬP] gửi tới %s: %s", phone, text)
    return True, "Chế độ giả lập (SMS_PROVIDER=log) — tin nhắn được ghi vào nhật ký, chưa gửi thật"


def _send_esms(phone, text, **kw):
    r = _requests().post(
        "https://rest.esms.vn/MainService.svc/json/SendMultipleMessage_V4_post_json/",
        json={
            "ApiKey": CFG.get("ESMS_API_KEY", ""),
            "SecretKey": CFG.get("ESMS_SECRET_KEY", ""),
            "Brandname": CFG.get("ESMS_BRANDNAME", ""),
            "Phone": normalize(phone),
            "Content": text,
            "SmsType": CFG.get("ESMS_SMS_TYPE", "2"),
        }, timeout=_tg())
    d = r.json()
    ok = str(d.get("CodeResult")) == "100"
    return ok, ("Đã gửi qua eSMS" if ok else f"eSMS lỗi {d.get('CodeResult')}: {d.get('ErrorMessage')}")


def _send_speedsms(phone, text, **kw):
    rq = _requests()
    token = CFG.get("SPEEDSMS_TOKEN", "")
    r = rq.post("https://api.speedsms.vn/index.php/sms/send",
                json={"to": [normalize(phone)], "content": text,
                      "sms_type": CFG.get_int("SPEEDSMS_TYPE", 2),
                      "sender": CFG.get("SPEEDSMS_SENDER", "")},
                auth=(token, "x"), timeout=_tg())
    d = r.json()
    ok = d.get("status") == "success"
    return ok, ("Đã gửi qua SpeedSMS" if ok else f"SpeedSMS lỗi: {d.get('message')}")


def _send_twilio(phone, text, **kw):
    sid = CFG.get("TWILIO_SID", "")
    r = _requests().post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data={"To": to_e164(phone), "From": CFG.get("TWILIO_FROM", ""), "Body": text},
        auth=(sid, CFG.get("TWILIO_TOKEN", "")), timeout=_tg())
    ok = r.status_code in (200, 201)
    return ok, ("Đã gửi qua Twilio" if ok else f"Twilio lỗi {r.status_code}: {r.text[:200]}")


def _send_zns(phone, text, **kw):
    """Zalo ZNS gửi theo template có sẵn, truyền tham số thay vì text tự do."""
    params = kw.get("zns_params") or {"content": text}
    r = _requests().post(
        "https://business.openapi.zalo.me/message/template",
        headers={"access_token": CFG.get("ZNS_ACCESS_TOKEN", ""),
                 "Content-Type": "application/json"},
        data=json.dumps({"phone": "84" + (normalize(phone) or "")[1:],
                         "template_id": CFG.get("ZNS_TEMPLATE_ID", ""),
                         "template_data": params}), timeout=_tg())
    d = r.json()
    ok = d.get("error") == 0
    return ok, ("Đã gửi qua Zalo ZNS" if ok else f"ZNS lỗi {d.get('error')}: {d.get('message')}")


PROVIDERS = {
    "log": ("Giả lập (ghi log)", _send_log),
    "esms": ("eSMS.vn", _send_esms),
    "speedsms": ("SpeedSMS.vn", _send_speedsms),
    "twilio": ("Twilio", _send_twilio),
    "zns": ("Zalo ZNS", _send_zns),
}


def send(phone, text, db=None, teacher_id=None, loai="thongbao", **kw):
    """Gửi tin nhắn. Trả về (ok, thông_điệp). Tự ghi nhật ký nếu truyền db."""
    p = normalize(phone)
    if not p:
        return _log_db(db, teacher_id, phone, text, loai, False,
                       "Số điện thoại không hợp lệ")
    prov = CFG.get("SMS_PROVIDER", "log")
    chain = [x.strip() for x in prov.split(",") if x.strip()] or ["log"]
    last = "Chưa cấu hình nhà cung cấp tin nhắn"
    for name in chain:
        ten, fn = PROVIDERS.get(name, (name, None))
        if not fn:
            last = f"Không hỗ trợ nhà cung cấp '{name}'"
            continue
        try:
            ok, msg = fn(p, text, **kw)
        except Exception as e:
            ok, msg = False, f"{ten} lỗi kết nối: {e}"
        log.info("SMS %s -> %s: %s", name, p, msg)
        if ok:
            return _log_db(db, teacher_id, p, text, loai, True, msg)
        last = msg
    return _log_db(db, teacher_id, p, text, loai, False, last)


def _log_db(db, teacher_id, phone, text, loai, ok, msg):
    if db is not None:
        import datetime
        try:
            db.execute(
                "INSERT INTO sms_log(teacher_id,phone,noi_dung,loai,provider,ok,ket_qua,created)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (teacher_id, phone, text, loai, CFG.get("SMS_PROVIDER", "log"), 1 if ok else 0, msg,
                 datetime.datetime.now().isoformat(timespec="seconds")))
            db.commit()
        except Exception as e:          # không để lỗi ghi log làm hỏng luồng chính
            log.warning("Không ghi được sms_log: %s", e)
    return ok, msg


# ---------------- Mẫu tin nhắn ----------------
def mau_ma_kich_hoat(code, goi, so_luot=3, het_han=""):
    if goi == "vip":
        return (f"EduAssist: Cam on ban da thanh toan! Ma kich hoat VIP cua ban la {code} "
                f"(su dung khong gioi han den {het_han}). "
                f"Nhap ma tai muc Nang cap tren website.")
    return (f"EduAssist: Cam on ban da thanh toan! Ma kich hoat {code} "
            f"tuong ung {so_luot} luot su dung. Nhap ma tai muc Nang cap tren website.")


def mau_da_kich_hoat(goi, so_luot=3, het_han=""):
    if goi == "vip":
        return (f"EduAssist: Thanh toan thanh cong! Tai khoan cua ban da duoc nang cap VIP, "
                f"su dung khong gioi han den {het_han}. Cam on ban!")
    return (f"EduAssist: Thanh toan thanh cong! Da cong {so_luot} luot vao tai khoan cua ban. "
            f"Cam on ban!")

"""Cấu hình trung tâm — sửa được ngay trên web, không cần sờ vào biến môi trường.

Thứ tự ưu tiên khi đọc một tham số:
    1. Giá trị admin đã lưu trong CSDL (bảng setting)
    2. Biến môi trường
    3. Giá trị mặc định khai trong DINH_NGHIA

Nhờ vậy vẫn giữ nguyên cách deploy bằng biến môi trường như cũ, nhưng thầy/cô
có thể tự chỉnh giá tiền, số tài khoản, khoá SMS… trong trang Cài đặt hệ thống.
"""
import os
import json
import time
import threading

# Bộ nhớ đệm để không phải truy vấn CSDL mỗi lần đọc cấu hình.
# Khi chạy nhiều worker (gunicorn --workers 2), mỗi worker có bộ đệm riêng,
# nên phải làm mới định kỳ để worker này thấy thay đổi worker kia vừa lưu.
_cache = {}
_lock = threading.Lock()
_da_nap = False
_lan_nap = 0.0
TTL = float(os.environ.get("CONFIG_TTL", 3))     # giây


class Muc:
    """Mô tả một tham số cấu hình để tự dựng giao diện."""

    def __init__(self, key, nhan, mac_dinh="", kieu="text", nhom="chung",
                 mo_ta="", chon=None, bimat=False, don_vi=""):
        self.key = key
        self.nhan = nhan
        self.mac_dinh = mac_dinh
        self.kieu = kieu          # text | number | password | select | bool | textarea
        self.nhom = nhom
        self.mo_ta = mo_ta
        self.chon = chon or []    # [(giá trị, nhãn)]
        self.bimat = bimat        # che khi hiển thị
        self.don_vi = don_vi


NHOM = [
    ("thuong_hieu", "🏫 Thông tin website", "Tên, khẩu hiệu, thông tin liên hệ hiển thị cho giáo viên"),
    ("goi_cuoc", "💳 Gói cước & hạn mức", "Số lượt miễn phí và giá từng gói"),
    ("ngan_hang", "🏦 Tài khoản nhận tiền", "Thông tin in lên mã QR chuyển khoản"),
    ("tu_dong", "⚡ Đối soát chuyển khoản tự động", "Kết nối SePay / Casso để tự kích hoạt khi nhận được tiền"),
    ("tin_nhan", "📩 Nhắn tin cho giáo viên", "Gửi mã kích hoạt qua SMS hoặc Zalo"),
    ("dang_nhap", "🔑 Đăng nhập Google", "Cho phép giáo viên đăng nhập bằng tài khoản Google"),
]

DINH_NGHIA = [
    # --- Thương hiệu ---
    Muc("SITE_NAME", "Tên website", "EduAssist", nhom="thuong_hieu",
        mo_ta="Hiện trên thanh bên và tiêu đề trình duyệt"),
    Muc("SITE_TAGLINE", "Khẩu hiệu", "Trợ lý giáo viên", nhom="thuong_hieu"),
    Muc("SITE_LOGO", "Biểu tượng (emoji)", "📚", nhom="thuong_hieu",
        mo_ta="Một ký tự emoji, ví dụ 📚 🎓 🏫 ✏️"),
    Muc("LIEN_HE_ZALO", "Zalo hỗ trợ", "", nhom="thuong_hieu",
        mo_ta="Số Zalo hiện ở trang thanh toán để giáo viên liên hệ khi cần"),
    Muc("LIEN_HE_EMAIL", "Email hỗ trợ", "", nhom="thuong_hieu"),

    # --- Gói cước ---
    Muc("FREE_QUOTA", "Số lượt dùng thử miễn phí", "3", "number", "goi_cuoc", don_vi="lượt",
        mo_ta="Dùng chung cho tải báo giảng, nhận xét và sửa chính tả"),
    Muc("PRICE_LUOT", "Giá gói lẻ", "10000", "number", "goi_cuoc", don_vi="đ"),
    Muc("LUOT_MOI_GOI", "Số lượt mỗi gói lẻ", "3", "number", "goi_cuoc", don_vi="lượt"),
    Muc("PRICE", "Giá gói VIP 1 năm", "100000", "number", "goi_cuoc", don_vi="đ"),

    # --- Ngân hàng ---
    Muc("BANK_NAME", "Tên ngân hàng", "Agribank", nhom="ngan_hang"),
    Muc("BANK_CODE", "Mã ngân hàng (VietQR)", "agribank", nhom="ngan_hang",
        mo_ta="vietcombank, techcombank, agribank, bidv, mbbank, vietinbank, acb, tpbank…"),
    Muc("BANK_ACC", "Số tài khoản", "7614215002756", nhom="ngan_hang"),
    Muc("BANK_OWNER", "Tên chủ tài khoản", "", nhom="ngan_hang",
        mo_ta="Viết in hoa không dấu, ví dụ NGUYEN VAN A"),

    # --- Đối soát tự động ---
    Muc("BANK_WEBHOOK_TOKEN", "Khoá bí mật webhook", "", "password", "tu_dong", bimat=True,
        mo_ta="Dán cùng khoá này vào SePay / Casso. Bấm nút bên dưới để tự sinh."),
    Muc("AUTO_ACTIVATE", "Tự kích hoạt ngay khi nhận tiền", "1", "bool", "tu_dong",
        mo_ta="Tắt thì hệ thống chỉ sinh mã, giáo viên phải tự nhập"),
    Muc("BANK_SAI_SO", "Cho phép lệch tiền", "0", "number", "tu_dong", don_vi="đ",
        mo_ta="Chuyển thiếu trong khoảng này vẫn chấp nhận"),

    # --- Tin nhắn ---
    Muc("SMS_PROVIDER", "Nhà cung cấp", "log", "select", "tin_nhan",
        chon=[("log", "Giả lập — chỉ ghi nhật ký, không gửi thật"),
              ("esms", "eSMS.vn — SMS brandname"),
              ("speedsms", "SpeedSMS.vn"),
              ("zns", "Zalo ZNS"),
              ("twilio", "Twilio (quốc tế)"),
              ("zns,esms", "Ưu tiên Zalo, lỗi thì chuyển SMS")],
        mo_ta="Để 'Giả lập' khi chạy thử để không tốn tiền tin nhắn"),
    Muc("ESMS_API_KEY", "eSMS — API Key", "", "password", "tin_nhan", bimat=True),
    Muc("ESMS_SECRET_KEY", "eSMS — Secret Key", "", "password", "tin_nhan", bimat=True),
    Muc("ESMS_BRANDNAME", "eSMS — Tên thương hiệu", "", nhom="tin_nhan"),
    Muc("SPEEDSMS_TOKEN", "SpeedSMS — Token", "", "password", "tin_nhan", bimat=True),
    Muc("SPEEDSMS_SENDER", "SpeedSMS — Tên người gửi", "", nhom="tin_nhan"),
    Muc("ZNS_ACCESS_TOKEN", "Zalo ZNS — Access Token", "", "password", "tin_nhan", bimat=True),
    Muc("ZNS_TEMPLATE_ID", "Zalo ZNS — Mã mẫu tin", "", nhom="tin_nhan"),
    Muc("TWILIO_SID", "Twilio — Account SID", "", "password", "tin_nhan", bimat=True),
    Muc("TWILIO_TOKEN", "Twilio — Auth Token", "", "password", "tin_nhan", bimat=True),
    Muc("TWILIO_FROM", "Twilio — Số gửi đi", "", nhom="tin_nhan"),

    # --- Google ---
    Muc("PUBLIC_BASE_URL", "Địa chỉ website HTTPS", "", nhom="dang_nhap",
        mo_ta="Ví dụ https://truong.example.vn — cần tên miền và chứng chỉ HTTPS, không dùng địa chỉ IP."),
    Muc("GOOGLE_CLIENT_ID", "Google Client ID", "", "password", "dang_nhap", bimat=True),
    Muc("GOOGLE_CLIENT_SECRET", "Google Client Secret", "", "password", "dang_nhap", bimat=True),
]

BANG = {m.key: m for m in DINH_NGHIA}
PREFIX = "cfg."          # tiền tố khi lưu vào bảng setting


# ---------------- Đọc / ghi ----------------
def nap(db):
    """Nạp toàn bộ cấu hình từ CSDL vào bộ nhớ đệm."""
    global _da_nap, _lan_nap
    with _lock:
        moi = {}
        try:
            for r in db.execute("SELECT k, v FROM setting WHERE k LIKE ?", (PREFIX + "%",)):
                moi[r["k"][len(PREFIX):]] = r["v"]
        except Exception:
            return
        _cache.clear()
        _cache.update(moi)
        _da_nap = True
        _lan_nap = time.time()


def _lam_moi():
    """Đọc lại từ CSDL nếu bộ đệm đã cũ hơn TTL giây.

    Cần thiết khi chạy nhiều worker: admin lưu cấu hình ở worker 1 thì
    worker 2 cũng phải thấy thay đổi trong vòng vài giây.
    """
    if time.time() - _lan_nap < TTL:
        return
    try:
        from flask import has_app_context
        if not has_app_context():
            return
        from ..db import get_db
        nap(get_db())
    except Exception:
        pass


def get(key, mac_dinh=None):
    """Lấy giá trị: CSDL → biến môi trường → mặc định."""
    _lam_moi()
    if key in _cache and _cache[key] != "":
        return _cache[key]
    v = os.environ.get(key)
    if v not in (None, ""):
        return v
    if mac_dinh is not None:
        return mac_dinh
    m = BANG.get(key)
    return m.mac_dinh if m else ""


def get_int(key, mac_dinh=0):
    try:
        return int(str(get(key)).strip() or mac_dinh)
    except (ValueError, TypeError):
        return mac_dinh


def get_bool(key, mac_dinh=False):
    v = str(get(key, "1" if mac_dinh else "0")).strip().lower()
    return v in ("1", "true", "yes", "on", "co", "có")


def set_many(db, data):
    """Lưu nhiều tham số. Chỉ nhận key có trong DINH_NGHIA."""
    n = 0
    for k, v in data.items():
        if k not in BANG:
            continue
        v = "" if v is None else str(v).strip()
        db.execute(
            "INSERT INTO setting(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (PREFIX + k, v))
        n += 1
    db.commit()
    nap(db)
    return n


def xoa(db, key):
    """Trả tham số về mặc định (xoá bản ghi trong CSDL)."""
    db.execute("DELETE FROM setting WHERE k=?", (PREFIX + key,))
    db.commit()
    nap(db)


def nguon(key):
    """Giá trị hiện tại đến từ đâu — để hiện nhãn trên giao diện."""
    _lam_moi()
    if _cache.get(key):
        return "csdl"
    if os.environ.get(key):
        return "moi_truong"
    return "mac_dinh"


def che(v):
    """Che khoá bí mật khi hiển thị: abcdef123456 -> abcd••••3456"""
    v = str(v or "")
    if len(v) <= 8:
        return "•" * len(v)
    return v[:4] + "•" * 8 + v[-4:]


# ---------------- Kiểm tra mức độ sẵn sàng ----------------
def suc_khoe():
    """Chấm điểm cấu hình để hiện cảnh báo trên bảng điều khiển."""
    ra = []

    def them(muc, ten, ok, canh_bao, goi_y=""):
        ra.append({"muc": muc, "ten": ten, "ok": ok,
                   "thong_diep": canh_bao if not ok else "", "goi_y": goi_y})

    them("ngan_hang", "Tài khoản nhận tiền",
         bool(get("BANK_ACC")), "Chưa khai số tài khoản — giáo viên không chuyển khoản được")
    tok = get("BANK_WEBHOOK_TOKEN")
    them("tu_dong", "Đối soát chuyển khoản tự động", bool(tok),
         "Chưa bật — phải tự tay tạo mã cho từng giáo viên",
         "Bấm 'Tự sinh khoá' trong mục Đối soát tự động, rồi dán sang SePay/Casso")
    sms = get("SMS_PROVIDER", "log")
    them("tin_nhan", "Nhắn tin mã kích hoạt", sms != "log",
         "Đang ở chế độ giả lập — tin nhắn chưa gửi thật",
         "Đăng ký eSMS.vn hoặc Zalo ZNS rồi chọn lại nhà cung cấp")
    them("dang_nhap", "Đăng nhập Google", bool(get("GOOGLE_CLIENT_ID")),
         "Chưa bật — giáo viên chỉ đăng nhập bằng mật khẩu")
    them("thuong_hieu", "Thông tin liên hệ",
         bool(get("LIEN_HE_ZALO") or get("LIEN_HE_EMAIL")),
         "Chưa khai Zalo/email hỗ trợ — giáo viên gặp sự cố không biết hỏi ai")
    return ra

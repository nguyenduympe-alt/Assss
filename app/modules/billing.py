"""Quản lý hạn mức dùng thử và kích hoạt gói trả phí."""
import datetime, secrets, string, os
from . import config as CFG


# Các tham số dưới đây admin sửa được trong Cài đặt hệ thống (không cần deploy lại).
# Dùng __getattr__ để mã cũ viết BL.PRICE vẫn chạy, nhưng luôn lấy giá trị mới nhất.
_DONG = {
    "FREE_QUOTA": ("get_int", 3),
    "PRICE": ("get_int", 100000),
    "PRICE_LUOT": ("get_int", 10000),
    "LUOT_MOI_GOI": ("get_int", 3),
    "BANK_NAME": ("get", "Agribank"),
    "BANK_CODE": ("get", "agribank"),
    "BANK_ACC": ("get", "7614215002756"),
    "BANK_OWNER": ("get", ""),
}


def __getattr__(name):
    if name in _DONG:
        ham, md = _DONG[name]
        return getattr(CFG, ham)(name, md)
    raise AttributeError(name)


def today():
    return datetime.date.today()


def is_pro(user):
    """Còn hạn gói trả phí?"""
    if not user:
        return False
    try:
        exp = user["expires"]
    except (KeyError, IndexError):
        return False
    if not exp:
        return False
    try:
        return datetime.date.fromisoformat(exp) >= today()
    except Exception:
        return False


def days_left(user):
    if not is_pro(user):
        return 0
    return (datetime.date.fromisoformat(user["expires"]) - today()).days


def used_count(user):
    try:
        return int(user["used"] or 0)
    except (KeyError, IndexError, TypeError):
        return 0


def bought_count(user):
    """Số lượt đã mua thêm qua gói lẻ 10k."""
    try:
        return int(user["bought"] or 0)
    except (KeyError, IndexError, TypeError):
        return 0


def remaining(user):
    """Số lượt còn lại (miễn phí + đã mua). None = không giới hạn."""
    if is_pro(user):
        return None
    return max(0, CFG.get_int("FREE_QUOTA", 3) + bought_count(user) - used_count(user))


def can_use(user):
    return is_pro(user) or remaining(user) > 0


def consume(db, user, kind, detail=""):
    """Trừ 1 lượt. Trả về True nếu được phép thực hiện."""
    if is_pro(user):
        db.execute("INSERT INTO usage_log(teacher_id,kind,detail,created) VALUES(?,?,?,?)",
                   (user["id"], kind, detail, datetime.datetime.now().isoformat(timespec="seconds")))
        db.commit()
        return True
    if remaining(user) <= 0:
        return False
    db.execute("UPDATE teacher SET used = COALESCE(used,0) + 1 WHERE id=?", (user["id"],))
    db.execute("INSERT INTO usage_log(teacher_id,kind,detail,created) VALUES(?,?,?,?)",
               (user["id"], kind, detail, datetime.datetime.now().isoformat(timespec="seconds")))
    db.commit()
    return True


def ref_code(user):
    """Mã tham chiếu ghi trong nội dung chuyển khoản, giúp đối soát."""
    return "EDU" + str(user["id"]).zfill(4)


def transfer_content(user, goi="vip"):
    # Không nhúng con số vào đây: admin đổi "số lượt mỗi gói" thì nội dung vẫn đúng,
    # và ngân hàng ghi liền "EDU0003LUOT" cũng không làm lệch mã tài khoản.
    return f"{ref_code(user)} {'1NAM' if goi == 'vip' else 'LUOT'}"


# ---------------- Mã kích hoạt ----------------
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"     # bỏ ký tự dễ nhầm (I,O,0,1)


def gen_code():
    raw = "".join(secrets.choice(ALPHABET) for _ in range(12))
    return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


def create_codes(db, n=1, months=12, note="", loai="vip", luot=0):
    """loai='vip' -> mở khoá theo tháng; loai='luot' -> cộng thêm N lượt."""
    out = []
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for _ in range(n):
        for _try in range(20):
            c = gen_code()
            if not db.execute("SELECT 1 FROM license WHERE code=?", (c,)).fetchone():
                break
        db.execute("INSERT INTO license(code,months,note,created,loai,luot) VALUES(?,?,?,?,?,?)",
                   (c, months, note, now, loai, luot or CFG.get_int("LUOT_MOI_GOI", 3)))
        out.append(c)
    db.commit()
    return out


def redeem(db, user, code):
    """Đổi mã kích hoạt. Trả về (ok, thông_báo)."""
    code = (code or "").strip().upper().replace(" ", "")
    if len(code) == 12 and "-" not in code:
        code = f"{code[:4]}-{code[4:8]}-{code[8:]}"
    row = db.execute("SELECT * FROM license WHERE code=?", (code,)).fetchone()
    if not row:
        return False, "Mã kích hoạt không tồn tại. Vui lòng kiểm tra lại."
    if row["used_by"]:
        if row["used_by"] == user["id"]:
            return False, "Mã này bạn đã sử dụng rồi."
        return False, "Mã này đã được sử dụng bởi tài khoản khác."
    now = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        loai = row["loai"] or "vip"
    except (KeyError, IndexError):
        loai = "vip"

    if loai == "luot":
        try:
            them = int(row["luot"] or CFG.get_int("LUOT_MOI_GOI", 3))
        except (KeyError, IndexError, TypeError):
            them = CFG.get_int("LUOT_MOI_GOI", 3)
        db.execute("UPDATE license SET used_by=?, used_at=? WHERE id=?", (user["id"], now, row["id"]))
        db.execute("UPDATE teacher SET bought = COALESCE(bought,0) + ? WHERE id=?", (them, user["id"]))
        db.commit()
        con_lai = CFG.get_int("FREE_QUOTA", 3) + bought_count(user) + them - used_count(user)
        return True, f"Đã cộng thêm {them} lượt! Bạn còn {max(0, con_lai)} lượt sử dụng."

    months = row["months"] or 12
    base = today()
    if is_pro(user):                       # còn hạn thì cộng dồn
        base = datetime.date.fromisoformat(user["expires"])
    new_exp = base + datetime.timedelta(days=30 * months if months != 12 else 365)
    db.execute("UPDATE license SET used_by=?, used_at=? WHERE id=?", (user["id"], now, row["id"]))
    db.execute("UPDATE teacher SET expires=? WHERE id=?", (new_exp.isoformat(), user["id"]))
    db.commit()
    return True, f"Kích hoạt VIP thành công! Dùng không giới hạn đến ngày {new_exp.strftime('%d/%m/%Y')}."

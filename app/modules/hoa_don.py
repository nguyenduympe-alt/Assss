"""(M28) Hoá đơn / biên lai và thông báo nâng VIP — có logo EduAssist.

Yêu cầu của thầy/cô: “in logo lên tệp Word xuất ra và trên hoá đơn/thông báo nâng VIP”.

Tệp này gom dữ liệu thanh toán của MỘT giáo viên từ hai nguồn đang có trong hệ thống:
  · bảng `bank_tx`  — giao dịch chuyển khoản ngân hàng (SePay/Casso/SMS forwarder hoặc admin nhập tay)
  · bảng `license`  — mã kích hoạt đã dùng
Không tạo bảng mới, không đổi dữ liệu: chỉ đọc và trình bày lại thành hoá đơn in được.
"""
import datetime

CHU_SO = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
DON_VI = ["", "nghìn", "triệu", "tỷ"]


def _doc_ba(n):
    """Đọc một nhóm 3 chữ số."""
    tram, chuc, dv = n // 100, (n // 10) % 10, n % 10
    ra = []
    if tram:
        ra.append(CHU_SO[tram] + " trăm")
    if chuc == 0 and dv and tram:
        ra.append("lẻ")
    elif chuc == 1:
        ra.append("mười")
    elif chuc:
        ra.append(CHU_SO[chuc] + " mươi")
    if dv:
        if dv == 1 and chuc > 1:
            ra.append("mốt")
        elif dv == 5 and chuc:
            ra.append("lăm")
        elif dv == 4 and chuc > 1:
            ra.append("tư")
        else:
            ra.append(CHU_SO[dv])
    return " ".join(ra)


def doc_tien(n):
    """Đọc số tiền thành chữ: 100000 -> “Một trăm nghìn đồng”."""
    try:
        n = int(n or 0)
    except Exception:
        return ""
    if n == 0:
        return "Không đồng"
    nhom, i = [], 0
    while n > 0:
        nhom.append((n % 1000, i))
        n //= 1000
        i += 1
    phan = []
    for k, (so, vitri) in enumerate([x for x in reversed(nhom) if x[0] > 0]):
        if k > 0 and so < 100:                 # nhóm thấp hơn mà thiếu hàng trăm
            phan.append("không trăm" + (" lẻ" if so < 10 else ""))
        phan.append((_doc_ba(so) + (" " + DON_VI[vitri] if DON_VI[vitri] else "")).strip())
    chu = " ".join(phan).replace("  ", " ").strip()
    return chu[:1].upper() + chu[1:] + " đồng"


def _ngay(s):
    """dd/mm/yyyy từ nhiều kiểu ngày khác nhau."""
    s = (s or "").strip()
    for kieu in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s[:19], kieu).strftime("%d/%m/%Y")
        except Exception:
            continue
    return s[:10]


def _goi(goi, so_tien=None):
    g = (goi or "").lower()
    if g == "vip":
        return "Gói VIP 1 năm — dùng không giới hạn"
    if g == "luot":
        return "Gói lẻ — cộng thêm lượt tải tệp"
    return "Nâng cấp tài khoản"


def _trang_thai(t):
    t = (t or "").strip()
    return {"da_kich_hoat": "Đã kích hoạt", "da_tao_ma": "Đã tạo mã kích hoạt",
            "cho_doi_soat": "Chờ hệ thống đối soát", "bo_qua": "Không khớp — bỏ qua",
            "trung": "Giao dịch trùng (đã xử lý)"}.get(t, t or "Đã ghi nhận")


def danh_sach(db, uid):
    """Danh sách hoá đơn / biên lai của một giáo viên (mới nhất trước)."""
    ra = []
    for r in db.execute("SELECT * FROM bank_tx WHERE teacher_id=? ORDER BY id DESC", (uid,)).fetchall():
        r = dict(r)
        ra.append({
            "loai": "bank", "id": r.get("id"),
            "ma": "HD-%05d" % (r.get("id") or 0),
            "ngay": _ngay(r.get("ngay") or r.get("created")),
            "noi_dung": r.get("noi_dung") or "",
            "so_tien": int(r.get("so_tien") or 0),
            "goi": _goi(r.get("goi")),
            "hinh_thuc": "Chuyển khoản ngân hàng" + ((" (%s)" % r["nguon"]) if r.get("nguon") else ""),
            "ma_gd": r.get("ref") or r.get("code") or "",
            "trang_thai": _trang_thai(r.get("trang_thai")),
            "da_kich_hoat": (r.get("trang_thai") == "da_kich_hoat"),
        })
    for r in db.execute("SELECT * FROM license WHERE used_by=? AND used_at IS NOT NULL "
                        "ORDER BY id DESC", (uid,)).fetchall():
        r = dict(r)
        la_vip = (r.get("loai") or "vip") == "vip"
        ra.append({
            "loai": "ma", "id": r.get("id"),
            "ma": "KM-%05d" % (r.get("id") or 0),
            "ngay": _ngay(r.get("used_at")),
            "noi_dung": "Nhập mã kích hoạt %s" % (r.get("code") or ""),
            "so_tien": 0,
            "goi": ("Gói VIP %d tháng — dùng không giới hạn" % (r.get("months") or 12)) if la_vip
                   else ("Gói lẻ — %d lượt tải tệp" % (r.get("luot") or 0)),
            "hinh_thuc": "Mã kích hoạt" + ((" · %s" % r["note"]) if r.get("note") else ""),
            "ma_gd": r.get("code") or "",
            "trang_thai": "Đã kích hoạt",
            "da_kich_hoat": True,
            "la_ma": True,
        })
    ra.sort(key=lambda x: (x["ngay"].split("/")[::-1], x["id"]), reverse=True)
    return ra


def tong_tien(ds):
    return sum(int(x.get("so_tien") or 0) for x in ds)


def tim(ds, loai, id_):
    for x in ds:
        if x["loai"] == loai and str(x["id"]) == str(id_):
            return x
    return None


def tien_chu(ds):
    """Câu tóm tắt cho phần chân hoá đơn danh sách."""
    t = tong_tien(ds)
    return ("Tổng đã ghi nhận: %s đ (%s)" % ("{:,}".format(t).replace(",", "."), doc_tien(t).lower())) if t else ""


def ngay_het_han(expires):
    return _ngay(expires) if expires else ""

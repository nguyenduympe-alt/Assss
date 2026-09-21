"""MÔN DẠY của một giáo viên (M17) — một giáo viên được dạy NHIỀU MÔN.

Cách lưu:
  · Danh sách môn nằm ở cột `teacher.subjects`, **mỗi dòng một môn**.
  · Môn ở DÒNG ĐẦU là **môn chính**; hệ thống ghi luôn giá trị này vào cột `teacher.subject` cũ
    để những phần đang dùng (lịch báo giảng, nhận xét học sinh, tải giáo án…) không phải sửa lại.
  · Môn học ở đây là dữ liệu của riêng từng giáo viên — không ảnh hưởng giáo viên khác.

Ngoài ra module này còn đọc MÔN + KHỐI từ TÊN TỆP KHDH để thầy/cô tải **nhiều phân phối
chương trình lên một lần** (ví dụ: `KHDH Toan 6.docx`, `PPCT-Ngu-van-7.docx`, `Tin học 10.docx`).
"""
import re
import unicodedata

TOI_DA_MON = 20             # số môn tối đa của một giáo viên
DAI_MON = 60                # độ dài tối đa tên một môn

# gợi ý sẵn để thầy/cô bấm chọn nhanh (vẫn nhập được môn khác)
GOI_Y = ["Toán", "Ngữ văn", "Tiếng Việt", "Tiếng Anh", "Tiếng Pháp", "Tiếng Trung", "Tiếng Nhật",
         "Vật lí", "Hoá học", "Sinh học", "Lịch sử", "Địa lí", "Giáo dục Kinh tế và Pháp luật",
         "Giáo dục công dân", "Tin học", "Công nghệ", "Âm nhạc", "Mĩ thuật", "Thể dục",
         "Giáo dục thể chất", "Hoạt động trải nghiệm", "Ngoại ngữ", "Khoa học tự nhiên",
         "Lịch sử và Địa lí", "Đạo đức", "Tự nhiên và Xã hội"]

# CỤM từ không phải tên môn (bỏ trước khi đoán môn) — giữ nguyên những từ có nghĩa như
# "học" trong "Tin học", "Hoá học" bằng cách chỉ bỏ khi đi thành cụm.
CUM_BO = ("ke hoach", "phan phoi", "chuong trinh", "giao an", "bai day", "bai giang", "day hoc",
          "nam hoc", "hoc ky", "hoc ki", "tieu hoc", "giao duc", "khung bo", "tich hop", "day du",
          "giua ky", "cuoi ky", "to bo mon", "to chuyen mon", "ke hoach bai day", "bai kiem tra")
# từ đơn không phải tên môn (đã bỏ cụm ở trên)
TU_BO = set("""khdh khgd ppct nls ai stem giao an bai mon lop khoi tuan tiet nam ky hoc?? gv gvcn to
truong vien khung bo moi chinh thuc day du final ban goc copy sua lan cuoi full version update
docx pdf xlsx giua cuoi hk hk1 hk2 t1 t2 2024 2025 2026 2027 2028 2029 2030""".replace("hoc?? ", "").split())

_SO_KHOI = re.compile(r"(?:khoi|khối|khoi/lop|lop|lớp|kh|l|k)\s*[-_.]?\s*(1[0-2]|[1-9])\b", re.I)
_SO = re.compile(r"^(\d{1,2})$")


def bo_dau(s):
    """Bỏ dấu tiếng Việt (để so khớp tên môn / tên tệp cho dễ)."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def chuan_mon(ten):
    """Chuẩn hoá một tên môn: bỏ khoảng trắng thừa, viết hoa đầu từ, tối đa 60 ký tự."""
    ten = re.sub(r"\s+", " ", (ten or "").replace("\u00a0", " ")).strip(" .,;-–—:")
    ten = ten[:DAI_MON]
    if not ten:
        return ""
    # "tin học" → "Tin học", "TOÁN" → "Toán"; tên đã viết hoa đúng thì giữ nguyên
    if ten == ten.lower():
        ten = ten[:1].upper() + ten[1:]
    elif ten == ten.upper() and len(ten) > 1:
        ten = ten[:1].upper() + ten[1:].lower()
    return ten


def tach_mon(chu):
    """Tách danh sách môn từ ô nhập (mỗi dòng một môn; cho phép ngăn bằng dấu phẩy/chấm phẩy)."""
    ra = []
    for dong in re.split(r"[\r\n;]+", chu or ""):
        for x in dong.split(","):
            ten = chuan_mon(x)
            if not ten:
                continue
            if any(bo_dau(ten) == bo_dau(y) for y in ra):        # bỏ trùng, không phân biệt dấu
                continue
            ra.append(ten)
    return ra[:TOI_DA_MON]


def _tach_cot(chu):
    ra = []
    for dong in re.split(r"[\r\n;]+", chu or ""):
        ten = chuan_mon(dong)
        if ten:
            ra.append(ten)
    return ra[:TOI_DA_MON]


def danh_sach(u):
    """Danh sách môn của một giáo viên (row teacher). Chưa khai thì lấy cột `subject` cũ."""
    if not u:
        return []
    try:
        chu = u["subjects"]
    except Exception:
        chu = ""
    ra = _tach_cot(chu)
    if ra:
        return ra
    try:
        cu = chuan_mon(u["subject"] or "")
    except Exception:
        cu = ""
    return [cu] if cu else []


def mon_chinh(u):
    ds = danh_sach(u)
    return ds[0] if ds else ""


def luu(db, uid, ds):
    """Ghi danh sách môn + đồng bộ `subject` (môn chính = môn đầu). Trả về danh sách đã chuẩn hoá."""
    ds = [chuan_mon(x) for x in (ds or []) if chuan_mon(x)]
    du, sach = set(), []
    for x in ds:
        k = bo_dau(x)
        if k in du:
            continue
        du.add(k)
        sach.append(x)
    sach = sach[:TOI_DA_MON]
    db.execute("UPDATE teacher SET subjects=?, subject=? WHERE id=?",
               ("\n".join(sach), (sach[0] if sach else ""), uid))
    db.commit()
    return sach


def them(db, uid, ten):
    """Thêm MỘT môn vào danh sách của giáo viên (nếu chưa có). Trả về True nếu có thêm mới."""
    ten = chuan_mon(ten)
    if not ten:
        return False
    ds = danh_sach({"subjects": None, "subject": None})
    row = db.execute("SELECT id, subject, subjects FROM teacher WHERE id=?", (uid,)).fetchone()
    if not row:
        return False
    ds = danh_sach(row)
    if any(bo_dau(x) == bo_dau(ten) for x in ds):
        return False
    if len(ds) >= TOI_DA_MON:
        return False
    luu(db, uid, ds + [ten])
    return True


def xoa(db, uid, ten):
    """Bỏ một môn khỏi danh sách (KHDH đã lưu trong kho vẫn giữ nguyên)."""
    row = db.execute("SELECT id, subject, subjects FROM teacher WHERE id=?", (uid,)).fetchone()
    if not row:
        return False
    ds = danh_sach(row)
    con = [x for x in ds if bo_dau(x) != bo_dau(ten)]
    if len(con) == len(ds):
        return False
    luu(db, uid, con)
    return True


def _bang_goi_y():
    """Bảng tra: tên không dấu → tên chuẩn (để 'Toan' thành 'Toán')."""
    return {bo_dau(x): x for x in GOI_Y}


def khop_mon(ten, ds=()):
    """Tìm cách viết ĐÚNG của một môn: ưu tiên môn giáo viên đã khai, rồi tới danh sách gợi ý."""
    ten = chuan_mon(ten)
    if not ten:
        return ""
    k = bo_dau(ten)
    for x in ds or ():
        kx = bo_dau(x)
        if k == kx or (len(k) >= 4 and (k in kx or kx in k)):
            return x
    gy = _bang_goi_y()
    if k in gy:
        return gy[k]
    for kk, chuan in gy.items():                # 'tin hoc 10' chứa 'tin hoc'
        if len(kk) >= 5 and (k.startswith(kk) or kk in k):
            return chuan
    for kk, chuan in gy.items():                # 'cong dan' là một phần của 'Giáo dục công dân'
        if len(k) >= 4 and k in kk:
            return chuan
    return ten


def tu_ten_tep(ten_tep, ds=()):
    """Đọc (môn, khối) từ TÊN TỆP KHDH.

    Ví dụ: `KHDH Toan 6.docx` → ('Toán', '6') · `PPCT-Ngu-van-7-2026.docx` → ('Ngữ văn', '7')
    · `Tin học 10.docx` → ('Tin học', '10'). Không đọc được thì trả ('', '').
    """
    ten = (ten_tep or "").strip()
    if not ten:
        return "", ""
    ten = re.sub(r"\.(docx|doc|pdf|xlsx?)$", "", ten, flags=re.I)
    ten = ten.replace("\u00a0", " ").replace("_", " ").replace("-", " ").replace(".", " ")
    ten = re.sub(r"\s+", " ", ten).strip()
    kd = bo_dau(ten)
    for cum in CUM_BO:                          # bỏ cụm từ không phải tên môn
        if cum in kd:
            i = kd.index(cum)
            ten = (ten[:i] + " " + ten[i + len(cum):]).strip()
            kd = bo_dau(ten)

    khoi = ""
    m = _SO_KHOI.search(ten)                    # có chữ "khối/lớp/k/l" đứng trước số
    if m:
        khoi = m.group(1)
    if not khoi:                                # không có chữ dẫn → lấy số đứng riêng đầu tiên
        for x in ten.split():
            x = x.strip("()[]{},")
            if _SO.match(x) and 1 <= int(x) <= 12:
                khoi = x
                break
    # tên môn = phần chữ còn lại sau khi bỏ từ khoá và số
    giu = []
    for x in ten.split():
        x = x.strip("()[]{},")
        k = bo_dau(x)
        if not x or _SO.match(x) or re.match(r"^\d{4}([-/]\d{4})?$", x) or k in TU_BO:
            continue
        if re.match(r"^[kl]$", k):               # k4 / l4 đã dùng cho khối
            continue
        giu.append(x)
    mon = khop_mon(" ".join(giu), ds) if giu else ""
    return mon, khoi


def tom_tat(u):
    """Chuỗi ngắn để hiện trên giao diện: '3 môn: Toán · Tin học · Ngữ văn'."""
    ds = danh_sach(u)
    if not ds:
        return "chưa khai môn dạy"
    return "%d môn: %s" % (len(ds), " · ".join(ds))

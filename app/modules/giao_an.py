"""Phân tích và chỉnh sửa giáo án Word — giữ nguyên bản gốc, tô đỏ nội dung mới.

Nguyên tắc an toàn:
  - KHÔNG thực thi macro. File .docm bị từ chối. Chỉ đọc XML của .docx.
  - Chỉ ghi thêm nội dung mới; không sửa, không xoá, không định dạng lại nội dung cũ.
  - Mọi nội dung do máy tạo đều bôi đỏ FF0000 để giáo viên nhìn thấy và duyệt.
  - Xử lý lại thì cập nhật mục cũ thay vì chèn thêm (không nhân đôi nội dung).

Cấu trúc một bản phân tích:
  {
    'muc_tieu': {'co': bool, 'vi_tri': int, 'kieu_so': 'I'|'1'|'A', 'so_ke_tiep': str,
                 'tieu_de': str, 'cac_muc_con': [str], 'ket_thuc': int},
    'tien_trinh': {'kieu': 'bang'|'doan', 'vi_tri': int, 'cot': {...},
                   'so_hoat_dong': int, 'hoat_dong': [{'vi_tri','ten','thoi_luong'}]},
    'thoi_luong': {'tong_phut': int, 'nguon': [...]},
    'lop': '...', 'mon': '...', 'canh_bao': [...]
  }
"""
import copy
import io
import re
import unicodedata
import zipfile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import RGBColor

DO = RGBColor(0xFF, 0x00, 0x00)          # đỏ FF0000: nội dung TÍCH HỢP NĂNG LỰC SỐ
XANH = RGBColor(0x00, 0x00, 0xFF)        # xanh dương 0000FF: nội dung TÍCH HỢP GIÁO DỤC AI
MAU_MOI = (DO, XANH)                     # mọi màu dùng cho nội dung hệ thống chèn
NHAN_AI = "[AI đề xuất – cần giáo viên duyệt]"

# ------------------------------------------------------------------ tiện ích
def khong_dau(s):
    s = (s or "").lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))


def gon(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def doc_word(data):
    """Đọc .docx an toàn. Từ chối .doc, .docm và file nén bất thường."""
    if len(data) > 8 * 1024 * 1024:
        raise ValueError("File Word tối đa 8 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            ten = z.namelist()
            if "word/document.xml" not in ten:
                raise ValueError("File không có cấu trúc Word hợp lệ.")
            if any(t.lower().endswith("vbaProject.bin".lower()) for t in ten):
                raise ValueError("File chứa macro (.docm). Hệ thống không thực thi macro — "
                                 "hãy lưu lại thành .docx rồi tải lên.")
            if sum(f.file_size for f in z.infolist()) > 40 * 1024 * 1024:
                raise ValueError("File Word quá lớn sau khi giải nén.")
            if len(ten) > 3000:
                raise ValueError("File Word có quá nhiều thành phần.")
        return Document(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("Không đọc được file Word. Hãy lưu lại dưới dạng .docx.") from None


# --------------------------------------------------- nhận diện tiêu đề mục
# Tên mục "phần mục tiêu" rất khác nhau giữa các bộ sách và cấp học:
#   - "I. MỤC TIÊU" (THCS/THPT, Công văn 5512)
#   - "I. YÊU CẦU CẦN ĐẠT" (tiểu học theo Chương trình GDPT 2018)
#   - "MỤC TIÊU BÀI HỌC", "I. MỤC ĐÍCH YÊU CẦU" (bản cũ)
# Nhận diện đủ các cách gọi này, nếu không giáo án thật sẽ bị báo thiếu mục.
_TEN_MUC_MUC_TIEU = (r"(?:muc\s*tieu|yeu\s*cau\s*can\s*dat|muc\s*dich\s*yeu\s*cau|"
                     r"ket\s*qua\s*can\s*dat)")
RE_MUC_TIEU = re.compile(r"^(?:phan\s+)?(?:[ivx]+|\d+|[a-z])?\s*[.)]?\s*" + _TEN_MUC_MUC_TIEU, re.I)
RE_MUC_TIEU_2 = re.compile(r"(?:" + _TEN_MUC_MUC_TIEU + r"|muc\s*tieu)\s*(?:bai|day|cua\s*bai|mon)", re.I)


def _la_tieu_de_muc_tieu(t):
    n = khong_dau(gon(t))
    if len(n) > 60:
        return None
    if RE_MUC_TIEU.match(n) or RE_MUC_TIEU_2.search(n):
        m = re.match(r"^\s*(?:phan\s+)?([IVXLC]+|\d+|[A-Za-z])\s*[.)]\s*", gon(t))
        kieu = ""
        if m:
            k = m.group(1)
            kieu = "I" if k.isupper() and k.isalpha() else ("1" if k.isdigit() else "A")
        return {"kieu_so": kieu, "tieu_de": gon(t)}
    return None


# ------------------------------------------------- mục con trong MỤC TIÊU
# Giáo án theo Công văn 5512 thường có: 1. Kiến thức · 2. Năng lực · 3. Phẩm chất
# (trong "2. Năng lực" lại có a. Năng lực chung · b. Năng lực đặc thù).
# Mục "Tích hợp năng lực số" phải nằm ở CUỐI PHẦN NĂNG LỰC, tức ngay trước "Phẩm chất"
# — chứ không phải nhảy xuống cuối cả mục MỤC TIÊU.
_ROMAN = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii")


def kieu_so_muc(text):
    """(kiểu đánh số, số/ chữ) của một dòng tiêu đề mục con. ('', '') nếu không phải."""
    t = gon(text)
    m = re.match(r"^\s*(\d+|[A-Za-z]{1,6})\s*[.)]\s+(.*)$", t)
    if not m:
        return "", "", ""
    so, con = m.group(1), m.group(2)
    if so.isdigit():
        kieu = "1"
    elif so.lower() in _ROMAN:
        kieu = "I"
    elif len(so) == 1:
        kieu = "a"
    else:
        return "", "", ""
    return kieu, so.lower(), khong_dau(con)


def _do_sau(kieu):
    """Mức lồng nhau: La Mã (ngoài cùng) < số < chữ cái (trong cùng)."""
    return {"I": 0, "1": 1, "a": 2}.get(kieu, 3)


def _muc_con_trong(paras, tu, den):
    """Các tiêu đề mục con trong khoảng đoạn [tu, den): [{vi_tri, kieu, so, ten}]."""
    ra = []
    for i in range(max(0, tu), min(den, len(paras))):
        kieu, so, ten = kieu_so_muc(paras[i].text)
        if kieu and ten:
            ra.append({"vi_tri": i, "kieu": kieu, "so": so, "ten": ten})
    return ra


def _dau_bang(ten, *cums):
    """Tên mục có khớp một trong các cách gọi không.

    Giáo án thật hay viết kèm dấu câu: "2. Năng lực." hoặc "2. Năng lực:" —
    phải bỏ dấu ở cuối trước khi so, nếu không sẽ bỏ sót mục Năng lực.
    """
    t = " ".join(ten.split()).rstrip(".:;,·-–— ").strip()
    return any(t == c or t.startswith(c + ":") or t.startswith(c + " ") for c in cums)


def tim_muc_nang_luc(paras, tu, den):
    """Tìm mục "Năng lực" trong MỤC TIÊU và vị trí kết thúc của nó.

    Trả về:
      {'co': bool, 'vi_tri': int, 'ket_thuc': int, 'cach_chen': 'trong_muc_nang_luc'
       | 'truoc_pham_chat' | 'cuoi_muc_tieu'}
    'ket_thuc' = đoạn mà mục mới phải được chèn NGAY TRƯỚC nó.
    """
    muc = _muc_con_trong(paras, tu, den)
    # bỏ qua chính mục do hệ thống chèn lần trước
    muc = [m for m in muc if not RE_NLD.search(m["ten"])]

    nl = [m for m in muc if _dau_bang(m["ten"], "nang luc", "ve nang luc")]
    if nl:
        # mục NĂNG LỰC ngoài cùng (nếu có "2. Năng lực" thì lấy nó, không lấy "a. Năng lực chung")
        cap = min(_do_sau(m["kieu"]) for m in nl)
        goc = [m for m in nl if _do_sau(m["kieu"]) == cap][-1]
        # kết thúc = mục kế tiếp cùng cấp hoặc cao hơn (ví dụ "3. Phẩm chất")
        ket_thuc = den
        for m in muc:
            if m["vi_tri"] > goc["vi_tri"] and _do_sau(m["kieu"]) <= cap:
                ket_thuc = m["vi_tri"]
                break
        return {"co": True, "vi_tri": goc["vi_tri"], "ket_thuc": ket_thuc,
                "cach_chen": "trong_muc_nang_luc", "kieu_so": goc["kieu"],
                "cac_muc_con": [m["so"] for m in muc
                                if goc["vi_tri"] < m["vi_tri"] < ket_thuc]}

    pc = [m for m in muc if _dau_bang(m["ten"], "pham chat", "ve pham chat")]
    if pc:
        cap = min(_do_sau(m["kieu"]) for m in pc)
        goc = [m for m in pc if _do_sau(m["kieu"]) == cap][0]
        return {"co": False, "vi_tri": -1, "ket_thuc": goc["vi_tri"],
                "cach_chen": "truoc_pham_chat", "kieu_so": "",
                "cac_muc_con": [m["so"] for m in muc
                                if _do_sau(m["kieu"]) == cap and m["vi_tri"] < goc["vi_tri"]]}
    return {"co": False, "vi_tri": -1, "ket_thuc": den, "cach_chen": "cuoi_muc_tieu",
            "kieu_so": "", "cac_muc_con": [m["so"] for m in muc]}


def _la_tieu_de_khac(t):
    """Tiêu đề mục lớn tiếp theo (để biết MỤC TIÊU kết thúc ở đâu)."""
    n = khong_dau(gon(t))
    if not n or len(n) > 80:
        return False
    return bool(re.match(
        r"^\s*(?:phan\s+)?(?:[ivx]+|\d+|[a-z])\s*[.)]\s*"
        r"(thiet\s*bi|do\s*dung|tien\s*trinh|hoat\s*dong|to\s*chuc|tien\s*trinh\s*day\s*hoc|"
        r"noi\s*dung\s*bai|chuan\s*bi|phuong\s*phap|hinh\s*thuc|dan\s*y|"
        r"ket\s*thuc|cung\s*co|dan\s*do|tong\s*ket|ru\s*kinh\s*nghiem|ghi\s*chu|"
        r"tai\s*lieu|hoc\s*lieu|muc\s*tieu\s*day\s*hoc|"
        # bổ sung theo giáo án thật: tiểu học thường có các mục này ngay sau phần mục tiêu
        r"phuong\s*tien|cac\s*hoat\s*dong|hoat\s*dong\s*day|day\s*-?\s*hoc|"
        r"do\s*dung\s*day|thoi\s*gian|phan\s*bo|ke\s*hoach\s*day)", n))


def _so_ke_tiep(kieu, da_co):
    """Số thứ tự tiếp nối cho mục mới, theo đúng kiểu đánh số đang dùng."""
    if kieu == "I":
        so_la = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
        dung = [x for x in da_co if x in so_la]
        return so_la[len(dung)] if len(dung) < len(so_la) else f"XIII"
    if kieu == "A":
        return chr(ord("A") + len(da_co))
    return str(len(da_co) + 1)


def _danh_so_muc_con(doc, tu, den):
    """Liệt kê các mục con đánh số trong khoảng đoạn [tu, den)."""
    ra = []
    for i in range(tu + 1, min(den, len(doc.paragraphs))):
        t = gon(doc.paragraphs[i].text)
        m = re.match(r"^\s*(\d+)\s*[.)]\s", t)
        if m:
            ra.append(m.group(1))
    return ra


# ------------------------------------------------------------ phân tích
# Các mẫu dưới đây khớp trên văn bản ĐÃ BỎ DẤU để tránh lệch chuẩn hoá Unicode.
_RE_MON = re.compile(r"\bmon\s*(?:hoc)?\s*[:\-]\s*(.{2,60}?)(?=\s*(?:lop|tuan|tiet|bai|ngay)\b|$)", re.I)
_RE_LOP = re.compile(r"\blop\s*[:\-]?\s*(\d{1,2})\b", re.I)
_RE_TIET = re.compile(r"\b(?:thoi\s*luong|so\s*tiet|tiet)\s*[:\-]?\s*(\d{1,3})\b", re.I)
_RE_TUAN = re.compile(r"\btuan\s*[:\-]?\s*(\d{1,2})\b", re.I)
# Giáo án thật ghi thời lượng rất nhiều kiểu: "5 phút", "(5’)", "5'", "5 ph". 
_RE_PHUT = re.compile(r"(\d{1,3})\s*(?:phút|phut|ph\b|['’′])")
_RE_HD = re.compile(r"^\s*(?:hoạt\s*động|hoat\s*dong)\s*(\d+)?\s*[:\-]?\s*(.*)$", re.I)
RE_NLD = re.compile(r"tich\s*hop\s*nang\s*luc\s*so", re.I)


def phan_tich(doc):
    """Phân tích cấu trúc giáo án. Chỉ đọc, không sửa gì."""
    paras = doc.paragraphs
    ra = {"muc_tieu": {"co": False}, "tien_trinh": {"kieu": "khong", "vi_tri": -1},
          "thoi_luong": {"tong_phut": 0, "nguon": []}, "lop": "", "mon": "",
          "so_tiet": 0, "tuan": 0, "canh_bao": [], "so_doan": len(paras),
          "so_bang": len(doc.tables)}

    # --- toàn văn để dò môn/lớp ---
    toan_van = "\n".join(gon(p.text) for p in paras[:60])
    for t in doc.tables[:3]:
        for r in t.rows[:4]:
            toan_van += "\n" + " | ".join(gon(c.text) for c in r.cells)
    toan_van = khong_dau(toan_van)
    m = _RE_MON.search(toan_van)
    if m:
        ra["mon"] = gon(m.group(1))[:60]
    m = _RE_LOP.search(toan_van)
    if m:
        ra["lop"] = m.group(1)
    m = _RE_TIET.search(toan_van)
    if m:
        ra["so_tiet"] = int(m.group(1))
    m = _RE_TUAN.search(toan_van)
    if m:
        ra["tuan"] = int(m.group(1))

    # --- MỤC TIÊU ---
    for i, p in enumerate(paras):
        tt = _la_tieu_de_muc_tieu(p.text)
        if tt:
            cuoi = len(paras)
            for j in range(i + 1, len(paras)):
                if _la_tieu_de_khac(paras[j].text):
                    cuoi = j
                    break
            ra["muc_tieu"] = {"co": True, "vi_tri": i, "kieu_so": tt["kieu_so"],
                              "nhan": tt["tieu_de"][:60],
                              "tieu_de": tt["tieu_de"], "ket_thuc": cuoi,
                              "cac_muc_con": _danh_so_muc_con(doc, i, cuoi),
                              "nang_luc": tim_muc_nang_luc(paras, i + 1, cuoi),
                              "da_co_nld": any(RE_NLD.search(khong_dau(gon(paras[j].text)))
                                               for j in range(i + 1, cuoi))}
            break
    if not ra["muc_tieu"]["co"]:
        ra["canh_bao"].append("Không tìm thấy tiêu đề MỤC TIÊU. Hãy thêm tiêu đề "
                              "“MỤC TIÊU” (hoặc “2. Mục tiêu”) rồi tải lại.")

    # --- TIẾN TRÌNH BÀI DẠY ---
    hd = []
    for i, p in enumerate(paras):
        m = _RE_HD.match(gon(p.text))
        if m:
            hd.append({"vi_tri": i, "ten": gon(p.text)[:120],
                       "thoi_luong": _phut_trong(gon(p.text))})
    ra["tien_trinh"] = {"kieu": "doan" if hd else "khong", "vi_tri": -1, "cot": {},
                        "so_hoat_dong": len(hd), "hoat_dong": hd}

    # bảng tiến trình: có cột hoạt động / thời gian
    for ti, t in enumerate(doc.tables):
        if not t.rows:
            continue
        tieu_de = [" ".join(khong_dau(gon(c.text)).split()) for c in t.rows[0].cells]

        def _co(h, *tu):
            return any(re.search(r"\b" + t + r"\b", h) for t in tu)

        cot = {}
        for ci, h in enumerate(tieu_de):
            la_gv = _co(h, "gv") or "giao vien" in h
            la_hs = _co(h, "hs") or "hoc sinh" in h
            if "thoi gian" in h or "thoi luong" in h:
                cot["thoi_gian"] = ci
            elif la_gv:
                cot["gv"] = ci
            elif la_hs:
                cot["hs"] = ci
            elif ("hoat dong" in h or "ten hoat dong" in h or "noi dung" in h) and ci == 0:
                cot.setdefault("hoat_dong", ci)
            elif re.search(r"ho tro|hskt|khuyet tat|tang cuong|ghi chu", h):
                cot.setdefault("ho_tro", []).append(ci)
        # Bảng 4 cột thường là: Hoạt động | GV | HS | Thời gian.
        # Nhưng KHÔNG được gán bừa cột còn thừa thành "hoạt động": giáo án thật có bảng
        # "Hoạt động của GV | Hoạt động của HS | Hỗ trợ HSKT" — cột 3 là hỗ trợ học sinh
        # khuyết tật, gán thành cột hoạt động sẽ làm tên hoạt động rơi vào ô sai.
        if "hoat_dong" not in cot and cot:
            da_dung = {ci for k, v in cot.items()
                       if k != "ho_tro" and isinstance(v, int)}
            da_dung |= set(cot.get("ho_tro") or [])
            con_lai = sorted(set(range(len(tieu_de))) - da_dung)
            if len(con_lai) == 1:
                h = tieu_de[con_lai[0]]
                if not re.search(r"ho tro|hskt|khuyet tat|tang cuong|ghi chu|thiet bi|phuong tien", h):
                    cot["hoat_dong"] = con_lai[0]
        if len(cot) >= 2:
            ra["tien_trinh"] = {"kieu": "bang", "vi_tri": ti, "cot": cot,
                                "so_hoat_dong": max(0, len(t.rows) - 1), "hoat_dong": hd}
            break

    # --- thời lượng ---
    tong = 0
    nguon = []
    for p in paras:
        for mm in _RE_PHUT.finditer(gon(p.text)):
            tong += int(mm.group(1))
            nguon.append("đoạn")
    if ra["tien_trinh"]["kieu"] == "bang":
        ci = ra["tien_trinh"]["cot"].get("thoi_gian")
        if ci is not None:
            tong = 0
            nguon = ["bảng tiến trình"]
            for r in doc.tables[ra["tien_trinh"]["vi_tri"]].rows[1:]:
                tong += _phut_trong(gon(r.cells[ci].text)) if ci < len(r.cells) else 0
        else:
            # Bảng không có cột "Thời gian": nhiều giáo án (nhất là tiểu học) ghi thời lượng
            # ngay trong ô đầu của mỗi hoạt động, ví dụ "1. KHỞI ĐỘNG (5’)".
            tong, nguon = 0, ["bảng tiến trình (trong tên hoạt động)"]
            for r in doc.tables[ra["tien_trinh"]["vi_tri"]].rows[1:]:
                o_dau = gon(r.cells[0].text) if r.cells else ""
                # Chỉ cộng hoạt động lớn ("2. HÌNH THÀNH KIẾN THỨC (16’)"); bỏ mục con
                # ("2.1. Thông tin và quyết định (8’)") vì thời lượng đã nằm trong hoạt động lớn.
                if re.match(r"^\s*\d+\.\s*(?!\d)\S", o_dau) or "hoat dong" in khong_dau(o_dau)[:14]:
                    tong += _phut_trong(o_dau)
    ra["thoi_luong"] = {"tong_phut": tong, "nguon": nguon}

    if ra["tien_trinh"]["kieu"] == "khong":
        ra["canh_bao"].append("Không nhận diện được phần TIẾN TRÌNH BÀI DẠY dạng bảng hoặc "
                              "các mục “Hoạt động 1, 2…”. Hoạt động năng lực số sẽ được đặt "
                              "ngay sau phần MỤC TIÊU và cần giáo viên tự kéo vào đúng vị trí.")
    return ra


def _phut_trong(t):
    m = _RE_PHUT.search(t or "")
    if m:
        return int(m.group(1))
    return 0


# --------------------------------------------------- đánh dấu nội dung mới
def _xoa_ruan(p):
    for r in list(p.runs):
        r._r.getparent().remove(r._r)


def doan_mau(doc, mau, text, do=True, in_dam=False, le=0, style=None, mau_chu=None):
    """Tạo đoạn mới bám theo định dạng của một đoạn có sẵn (giữ bố cục tài liệu)."""
    if mau is not None:
        p = copy.deepcopy(mau._p)
        mau._p.addnext(p)
        from docx.text.paragraph import Paragraph
        new = Paragraph(p, mau._parent)
        _xoa_ruan(new)
        if style:
            try:
                new.style = doc.styles[style]
            except KeyError:
                pass
    else:
        new = doc.add_paragraph()
    if le:
        new.paragraph_format.left_indent = le
    r = new.add_run(text)
    r.font.color.rgb = ((mau_chu or DO) if do else None)
    r.bold = in_dam
    return new


def _xoa_doan(p):
    p._p.getparent().remove(p._p)


# Tiêu đề mục do hệ thống chèn: có thể đánh số ("2. Tích hợp năng lực số", "c. …")
# hoặc không đánh số (khi nằm trong mục Năng lực vốn không dùng chữ cái).
RE_TIEU_DE_NLD = re.compile(
    r"^(?:\s*(?:\d+|[ivx]+|[a-z])\s*[.)]\s*)?tich hop nang luc so\s*:?\s*$", re.I)


def la_tieu_de_nld(text):
    """Đúng là TIÊU ĐỀ mục 'Tích hợp năng lực số' (không phải câu nhắc tới nó)."""
    return bool(RE_TIEU_DE_NLD.match(khong_dau(gon(text))))


# Mục GIÁO DỤC AI do hệ thống chèn (Quyết định 2422/QĐ-BGDĐT + Công văn 5588/BGDĐT-GDPT).
RE_TIEU_DE_AI = re.compile(
    r"^(?:\s*(?:\d+|[ivx]+|[a-z])\s*[.)]\s*)?"
    r"tich hop giao duc (?:tri tue nhan tao|ai)(?:\s*\(ai\))?\s*:?\s*$", re.I)


def la_tieu_de_ai(text):
    """Đúng là TIÊU ĐỀ mục 'Tích hợp giáo dục trí tuệ nhân tạo (AI)'."""
    return bool(RE_TIEU_DE_AI.match(khong_dau(gon(text))))


# Các dòng con hệ thống sinh ra trong mục "Tích hợp năng lực số"
# và trong khối hoạt động dự phòng — dùng để dọn khi chạy lại.
RE_HOAT_DONG_HE_THONG = re.compile(
    r"^\s*Hoạt động tích hợp (?:năng lực số|giáo dục AI)\b", re.I)

RE_DONG_DO_HE_THONG = re.compile(
    r"^\s*(?:\d+\s*\.\s*(?:Tiêu chí|Mạch)|·\s*\[QUY ĐỊNH\]|·\s*\[ĐỀ XUẤT\]|"
    r"·\s*(?:Mục tiêu|Minh chứng đánh giá|Căn cứ chọn mạch|Hoạt động gợi ý|Nội dung lớp|"
    r"CẦN GIÁO VIÊN DUYỆT)|"
    r"Nguồn:\s*(?:Khung nội dung|Thông tư 02/2025|Công văn 3456|Quyết định 2422|Công văn 5588)|"
    r"Hoạt động tích hợp (?:năng lực số|giáo dục AI)|Mục tiêu:|Thời lượng:|Công cụ:|Các bước:|"
    r"Nhiệm vụ của giáo viên:|Nhiệm vụ của học sinh:|Sản phẩm học tập:|"
    r"Tiêu chí đánh giá:|\()")


def _xoa_muc_nld_cu(doc, mt):
    """Xoá mục 'Tích hợp năng lực số' (và các dòng con) do lần chạy trước tạo.

    Quét toàn tài liệu chứ không chỉ trong khoảng MỤC TIÊU, để dọn cả hoạt động
    đã chèn trước đó — bảo đảm xử lý lại không bị trùng nội dung.
    """
    xoa = 0
    # Lượt 1: dọn khối HOẠT ĐỘNG do hệ thống chèn (dạng đoạn văn) ở bất kỳ đâu trong tài
    # liệu — chạy lại phải CẬP NHẬT, không được nhân thêm khối.
    for i in range(len(doc.paragraphs) - 1, -1, -1):
        t = gon(doc.paragraphs[i].text)
        if not RE_HOAT_DONG_HE_THONG.match(t or ""):
            continue
        _xoa_doan(doc.paragraphs[i]); xoa += 1
        j = i
        while j < len(doc.paragraphs):
            t2 = gon(doc.paragraphs[j].text)
            if not t2:
                _xoa_doan(doc.paragraphs[j]); xoa += 1; continue
            if not RE_DONG_DO_HE_THONG.match(t2):
                break
            _xoa_doan(doc.paragraphs[j]); xoa += 1
    # Lượt 2: dọn mục "Tích hợp năng lực số" và mục "Tích hợp giáo dục AI" trong MỤC TIÊU
    for i in range(len(doc.paragraphs) - 1, -1, -1):
        p = doc.paragraphs[i]
        if not (la_tieu_de_nld(p.text) or la_tieu_de_ai(p.text)):
            continue
        _xoa_doan(p)
        xoa += 1
        # xoá các dòng con đi kèm cho tới khi gặp tiêu đề mục khác
        j = i
        while j < len(doc.paragraphs):
            t = gon(doc.paragraphs[j].text)
            if not t:
                _xoa_doan(doc.paragraphs[j]); xoa += 1; continue
            kd = khong_dau(t)
            if (la_tieu_de_nld(t) or la_tieu_de_ai(t) or _la_tieu_de_khac(t)
                    or re.match(r"^\s*hoat\s*dong\s*\d", kd)):
                break
            # Chỉ xoá dòng ĐÚNG do hệ thống sinh ra (tiêu chí, [QUY ĐỊNH]/[ĐỀ XUẤT], các dòng
            # của khối hoạt động, ghi chú). Dòng nào không khớp thì coi là nội dung của giáo
            # viên -> dừng ngay, tuyệt đối không xoá.
            if not RE_DONG_DO_HE_THONG.match(t):
                break
            _xoa_doan(doc.paragraphs[j]); xoa += 1
    return xoa

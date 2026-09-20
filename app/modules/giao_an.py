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

DO = RGBColor(0xFF, 0x00, 0x00)          # đỏ FF0000 cho nội dung mới
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
RE_MUC_TIEU = re.compile(r"^(?:phan\s+)?(?:[ivx]+|\d+|[a-z])?\s*[.)]?\s*muc\s*tieu", re.I)
RE_MUC_TIEU_2 = re.compile(r"muc\s*tieu\s*(?:bai|day|cua\s*bai)", re.I)


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
        r"tai\s*lieu|hoc\s*lieu|muc\s*tieu\s*day\s*hoc)", n))


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
_RE_PHUT = re.compile(r"(\d{1,3})\s*(?:phút|phut)")
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
                              "tieu_de": tt["tieu_de"], "ket_thuc": cuoi,
                              "cac_muc_con": _danh_so_muc_con(doc, i, cuoi),
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
        # bảng 4 cột thường là: Hoạt động | GV | HS | Thời gian
        if "hoat_dong" not in cot and cot:
            cot["hoat_dong"] = min(set(range(len(tieu_de))) - set(cot.values()))
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


def doan_mau(doc, mau, text, do=True, in_dam=False, le=0, style=None):
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
    r.font.color.rgb = DO if do else None
    r.bold = in_dam
    return new


def _xoa_doan(p):
    p._p.getparent().remove(p._p)


RE_TIEU_DE_NLD = re.compile(r"^\s*(?:\d+|[ivx]+|[a-z])\s*[.)]\s*tich hop nang luc so", re.I)


def la_tieu_de_nld(text):
    """Đúng là TIÊU ĐỀ mục 'Tích hợp năng lực số' (không phải câu nhắc tới nó)."""
    return bool(RE_TIEU_DE_NLD.match(khong_dau(gon(text))))


def _xoa_muc_nld_cu(doc, mt):
    """Xoá mục 'Tích hợp năng lực số' (và các dòng con) do lần chạy trước tạo.

    Quét toàn tài liệu chứ không chỉ trong khoảng MỤC TIÊU, để dọn cả hoạt động
    đã chèn trước đó — bảo đảm xử lý lại không bị trùng nội dung.
    """
    xoa = 0
    for i in range(len(doc.paragraphs) - 1, -1, -1):
        p = doc.paragraphs[i]
        if not la_tieu_de_nld(p.text):
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
            if la_tieu_de_nld(t) or _la_tieu_de_khac(t) or re.match(
                    r"^\s*\d+\s*[.)]\s", t) or re.match(r"^\s*hoat\s*dong\s*\d", kd):
                break
            _xoa_doan(doc.paragraphs[j]); xoa += 1
    return xoa

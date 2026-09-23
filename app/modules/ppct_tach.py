"""(M29) Tách một tệp PPCT / KHDH chứa NHIỀU MÔN + NHIỀU KHỐI thành từng phần riêng.

Yêu cầu của thầy/cô: “Làm thêm chức năng cho phép upload phân phối ct có nhiều môn, nhiều khối”.

Ví dụ tệp thật của tổ chuyên môn: một tệp Word (hoặc Excel) trong đó có nhiều phần, mỗi phần là
phân phối chương trình của một môn/khối khác nhau:

    PHÂN PHỐI CHƯƠNG TRÌNH MÔN TOÁN — LỚP 6
    | Tuần | Tiết PPCT | Tên bài dạy | Năng lực số | AI |
    PHÂN PHỐI CHƯƠNG TRÌNH MÔN TOÁN — LỚP 7
    | ... |
    MÔN: TIN HỌC — KHỐI 10
    | ... |

Cách hệ thống nhận ra từng phần (theo thứ tự ưu tiên):
  1. **Cột “Môn” và “Khối/Lớp” ngay trong bảng** (kiểu Excel hoặc bảng Word có cột) → tách theo cột, mỗi
     cặp môn + khối thành một phần.
  2. **Tiêu đề ngay trên bảng** (đoạn văn ngay trước bảng có ghi môn/khối) → bảng đó thuộc môn + khối đó.
  3. Không đọc được gì (hoặc tệp chỉ có một phần) → dùng **ô Môn + Khối** thầy/cô điền trên màn hình,
     rồi tới **tên tệp** (`KHDH Toan 6.docx` → Toán 6).
     Khối trong tiêu đề chỉ được nhận khi có nhãn “KHỐI/LỚP” (vd “TOÁN — LỚP 6” hoặc “TOÁN 6”) để
     “Âm nhạc kỳ 1”, “Văn học kì 2”, “HK 2” không bị hiểu nhầm thành khối.

Bộ này KHÔNG tự đặt mã, không sửa nội dung: chỉ đọc bảng, gom dòng theo môn + khối.
"""
import copy
import io
import re

from docx import Document
from docx.text.paragraph import Paragraph

from . import digital_plan as DP
from . import mon_day as MD

TOI_DA_PHAN = 24          # số phần (môn + khối) tối đa đọc từ một tệp
TOI_DA_DONG = 1200        # số dòng bài học tối đa đọc từ một tệp

# Tên cột (đã bỏ dấu) → khoá dữ liệu
COT = (
    ("ten_bai", ("ten bai", "bai hoc", "noi dung bai hoc", "ten bai day", "bai day", "noi dung")),
    ("tuan", ("tuan", "tuan thuc hien")),
    ("tiet_pp", ("thoi luong", "so tiet ppct", "tiet ppct", "so tiet", "tiet hoc", "tiet")),
    ("ghi_chu", ("ghi chu", "do dung", "thiet bi day hoc", "thiet bi", "note")),
    ("digital", ("nang luc so", "nls")),
    ("ai", ("tri tue nhan tao", "giao duc ai", "ai")),
    ("stem", ("stem", "steam")),
    ("mon", ("mon hoc", "mon", "subject")),
    ("khoi", ("khoi lop", "khoi", "lop", "khoi/lop")),
)
TIEU_DE_PPCT = ("phan phoi", "ke hoach", "chuong trinh", "khung", "ppct", "khdh", "khgd")


def _khop_o(tu, o):
    """Ô tiêu đề có đúng cột này không: khớp cả ô, hoặc khớp trọn từ (để “AI” không lẫn vào “Bài dạy”)."""
    tu = tu.strip()
    if not tu:
        return False
    if tu == o:
        return True
    return re.search(r"(?<![a-z0-9])" + re.escape(tu) + r"(?![a-z0-9])", o) is not None


# ---------------------------------------------------------------- tiện ích
def _gon(s):
    if not isinstance(s, str):
        s = "" if s is None else str(s)
    return re.sub(r"\s+", " ", s.replace("\u00a0", " ")).strip()


# nhãn hay gặp trước tên môn trong tiêu đề: “MÔN: TOÁN”, “Môn học - Tin học”, “Bộ môn: Lý”
NHAN_MON = ("mon hoc", "bo mon", "mon", "subject", "phan phoi chuong trinh mon",
            "ke hoach day hoc mon", "ke hoach day hoc", "chuong trinh mon", "chuong trinh")


def _la_excel(ten_tep, data):
    return (ten_tep or "").lower().endswith((".xlsx", ".xlsm", ".xls", ".csv"))


def _so(v, toi_da=300):
    """Lấy số đầu tiên trong một ô (vd “4 tiết” → 4). Trả '' nếu không có."""
    ds = ds_so(v, toi_da)
    return str(ds[0]) if ds else ""


def ds_so(v, toi_da=60):
    """Tách ô tuần/tiết: “1-2” “1,2” “1_2” “1;2” “1+2” “1–2” → [1, 2]. “4 tiết” → [4].

    Dấu + / & là liệt kê (1+3 → 1 và 3), không phải khoảng 1…3.
    """
    s = "" if v is None else str(v).strip()
    if not s or s.lower() == "nan":
        return []
    s = (s.replace("–", "-").replace("—", "-").replace("−", "-")
           .replace("_", "-").replace("\\", ",").replace(";", ",")
           .replace("/", ",").replace("+", ",").replace("＋", ",").replace("&", ","))
    s = re.sub(r"(?i)\s*(và|va|tới|toi|đến|den)\s*", "-", s)
    ra = []
    for part in re.split(r"[,]+", s):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d{1,2})\s*[-~]\s*(\d{1,2})\D*$", part)
        if not m:
            m = re.match(r"^(\d{1,2})\s*[-~]\s*(\d{1,2})$", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            if b - a > 15:
                ra.extend([n for n in (a, b) if 0 < n <= toi_da])
            else:
                ra.extend([n for n in range(a, b + 1) if 0 < n <= toi_da])
            continue
        m = re.search(r"\d{1,3}", part)
        if m:
            n = int(m.group(0))
            if 0 < n <= toi_da:
                ra.append(n)
    seen, out = set(), []
    for n in ra:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def no_rong_tuan_tiet(rows, toi_tuan=60, toi_tiet=300):
    """Mỗi dòng có tuần/tiết dạng 1-2, 1,2, 1_2, 1+2 → tách thành từng tuần hoặc từng tiết.

    Tuần 1-2 / 1+2 + một tiết → hai dòng (tuần 1 và tuần 2). Tiết 1-2 / 1+2 + một tuần → hai dòng tiết.
    Tuần 1-2 và tiết 1-2 cùng độ dài → ghép đôi (tuần 1/tiết 1, tuần 2/tiết 2).
    """
    ra = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        d = dict(r)
        tuans = ds_so(d.get("tuan"), toi_tuan)
        tiets = ds_so(d.get("tiet_pp"), toi_tiet)
        if len(tuans) <= 1 and len(tiets) <= 1:
            if tuans:
                d["tuan"] = str(tuans[0])
            if tiets:
                d["tiet_pp"] = str(tiets[0])
            ra.append(d)
            continue
        if not tuans:
            try:
                tuans = [int(d.get("tuan") or 1)]
            except Exception:
                tuans = [1]
        cap = []
        if len(tuans) > 1 and len(tiets) > 1:
            if len(tuans) == len(tiets):
                cap = list(zip(tuans, tiets))
            else:
                cap = [(t, i) for t in tuans for i in tiets]
        elif len(tuans) > 1:
            tiet0 = tiets[0] if tiets else d.get("tiet_pp")
            cap = [(t, tiet0) for t in tuans]
        else:
            cap = [(tuans[0], i) for i in tiets]
        for tuan, tiet in cap:
            x = dict(d)
            x["tuan"] = str(tuan)
            x["tiet_pp"] = "" if tiet in (None, "") else str(tiet)
            ra.append(x)
            if len(ra) >= TOI_DA_DONG:
                return ra
    return ra


def _sach_mon(ten):
    """Bỏ nhãn và phần đuôi thừa của tên môn đọc từ tiêu đề.

    “Môn: TOÁN — LỚP 6” → “TOÁN” · “PHÂN PHỐI CHƯƠNG TRÌNH MÔN TIN HỌC” → “TIN HỌC”.
    """
    ten = _gon(ten)
    if not ten:
        return ""
    truoc = MD.bo_dau(ten)
    for nhan in NHAN_MON:                       # cắt mọi nhãn đứng TRƯỚC tên môn
        if truoc.startswith(nhan):
            ten, truoc = ten[len(nhan):], truoc[len(nhan):]
            ten, truoc = ten.lstrip(" :.-–—•\t"), truoc.lstrip(" :.-–—•\t")
    for nhan in NHAN_MON:                       # “PHÂN PHỐI … MÔN TOÁN” → cắt cả khi nhãn ở giữa
        if nhan + " " in truoc and len(nhan) > 3:
            i = truoc.index(nhan)
            ten, truoc = ten[i + len(nhan):], truoc[i + len(nhan):]
            ten, truoc = ten.lstrip(" :.-–—•\t"), truoc.lstrip(" :.-–—•\t")
    return _gon(ten)


def _mon_khoi(chu, ds_mon=(), chat=False):
    """Đọc (môn, khối) từ một dòng tiêu đề — dùng lại bộ đọc tên tệp của M17.

    `chat=True` (dùng cho tiêu đề trong tệp): số chỉ được coi là KHỐI khi có nhãn “khối/lớp”,
    hoặc đứng ngay sau tên môn (vd “TOÁN 6”). Nhờ vậy “Âm nhạc kỳ 1”, “Văn học kì 2” không bị
    hiểu nhầm thành khối 1 / khối 2.
    """
    chu = _gon(chu)
    if not chu:
        return "", ""
    mon, khoi = MD.tu_ten_tep(chu, ds_mon)
    mon = _sach_mon(mon)
    if chat and khoi:
        kd, so = MD.bo_dau(chu), str(khoi)
        ok = re.search(r"(khoi|lop)\s*[:.\-–—]*\s*" + re.escape(so), kd) is not None
        if not ok and mon:
            kdm = MD.bo_dau(mon)
            i = kd.find(kdm)
            sau = kd[i + len(kdm):] if i >= 0 else ""
            ok = re.match(r"\s*[:.\-–—()]*\s*" + re.escape(so) + r"\s*$", sau) is not None
        if not ok:
            khoi = ""
    return mon, khoi


def _la_tieu_de(chu):
    kd = MD.bo_dau(chu or "")
    return any(x in kd for x in TIEU_DE_PPCT)


# ---------------------------------------------------------------- đọc bảng Word
def _cot_bang(bang):
    """Tìm dòng tiêu đề của bảng và vị trí các cột cần dùng."""
    hang = bang.rows
    tu_ten_bai = dict(COT)["ten_bai"]
    for ri, row in enumerate(hang[:5]):
        tieu_de = [MD.bo_dau(_gon(c.text)) for c in row.cells]
        if not any(any(t in c for t in tu_ten_bai) for c in tieu_de):
            continue
        cot = {}
        for ci, gia_tri in enumerate(tieu_de):
            truoc = ""
            if ri > 0:
                try:
                    truoc = MD.bo_dau(_gon(hang[ri - 1].cells[ci].text))
                except Exception:
                    truoc = ""
            gop = gia_tri + " " + truoc
            for khoa, tu in COT:
                if khoa not in cot and any(_khop_o(t, gop) for t in tu):
                    cot[khoa] = ci
        return ri, cot
    return None, {}


def _doc_bang(bang, ds_mon=()):
    """Đọc một bảng Word → danh sách dòng bài học (kèm môn/khối nếu bảng có cột đó)."""
    ri, cot = _cot_bang(bang)
    if ri is None or "ten_bai" not in cot:
        return []
    ra = []
    for row in bang.rows[ri + 1:]:
        o = row.cells
        lay = lambda k: _gon(o[cot[k]].text) if k in cot and cot[k] < len(o) else ""
        ten_bai = lay("ten_bai")
        if not ten_bai or MD.bo_dau(ten_bai) in ("ten bai", "ten bai day", "bai hoc"):
            continue
        dong = {"ten_bai": ten_bai, "tuan": lay("tuan"), "tiet_pp": lay("tiet_pp"),
                "ghi_chu": lay("ghi_chu"), "digital": lay("digital"), "ai": lay("ai"),
                "stem": lay("stem"), "mon": "", "khoi": ""}
        if lay("mon") or lay("khoi"):
            m, k = _mon_khoi((lay("mon") + " " + lay("khoi")).strip(), ds_mon)
            dong["mon"], dong["khoi"] = _sach_mon(lay("mon")) or m, _so(lay("khoi"), 12) or k
        if dong["tuan"] or dong["tiet_pp"] or dong["ten_bai"]:
            ra.append(dong)
    return ra


def _tach_word(data, ten_tep, ds_mon):
    """Đi qua thân tài liệu theo đúng thứ tự: tiêu đề nào đứng ngay trên bảng nào."""
    try:
        doc = DP.read_word(data)
    except ValueError:
        raise
    except Exception:
        raise ValueError("Không đọc được tệp Word. Hãy lưu lại dưới dạng .docx rồi thử lại.")
    phan, tieu_de = [], ""
    for con in doc.element.body.iterchildren():
        tag = con.tag.split("}")[-1]
        if tag == "p":
            txt = _gon(Paragraph(con, doc).text)
            if not txt:
                continue
            m, k = _mon_khoi(txt, ds_mon)
            if (m or k) and (_la_tieu_de(txt) or len(txt) <= 90):
                tieu_de = txt
            continue
        if tag != "tbl":
            continue
        wrap = Document()
        wrap.element.body.append(copy.deepcopy(con))
        rows = _doc_bang(wrap.tables[0], ds_mon)
        if not rows:
            continue
        m_hd, k_hd = _mon_khoi(tieu_de, ds_mon, chat=True) if tieu_de else ("", "")
        nhom = {}
        for d in rows:
            m = d["mon"] or m_hd
            k = d["khoi"] or k_hd
            cach = "cột trong bảng" if d["mon"] or d["khoi"] else ("tiêu đề trên bảng" if (m_hd or k_hd) else "")
            key = (MD.bo_dau(m), str(k))
            nhom.setdefault(key, {"mon": m, "khoi": str(k), "rows": [], "cach": cach})
            nhom[key]["rows"].append(d)
        for key, g in nhom.items():
            _gop(phan, g["mon"], g["khoi"], g["rows"], g["cach"])
    return phan


# ---------------------------------------------------------------- đọc bảng tính
class _Tep:
    """Vỏ nhỏ để dùng lại XL.read_table (nó cần .filename và .read())."""

    def __init__(self, ten, data):
        self.filename, self._d = ten, data

    def read(self):
        return self._d


def _tach_bang_tinh(data, ten_tep, ds_mon):
    from . import excel_io as XL
    try:
        df = XL.read_table(_Tep(ten_tep, data))
    except Exception:
        raise ValueError("Không đọc được tệp bảng tính. Hãy lưu lại dưới dạng .xlsx hoặc .csv.")
    if df is None or not len(df.columns):
        return []
    cot = {}
    for c in df.columns:
        n = XL._norm(c)
        for khoa, tu in COT:
            if khoa not in cot and any(n == XL._norm(t) or (len(n) > 4 and n.startswith(XL._norm(t)))
                                       for t in tu):
                cot[khoa] = c
    if "ten_bai" not in cot:
        return []
    m_hd, k_hd = _mon_khoi(ten_tep, ds_mon)
    nhom = {}
    for _, row in df.iterrows():
        ten_bai = _gon(row.get(cot["ten_bai"]))
        if not ten_bai or ten_bai.lower() == "nan":
            continue
        lay = lambda k: _gon(row.get(cot[k])) if k in cot else ""
        m, k = _mon_khoi((lay("mon") + " " + lay("khoi")).strip(), ds_mon) if (lay("mon") or lay("khoi")) \
            else ("", "")
        m, k = _sach_mon(lay("mon")) or m or m_hd, _so(lay("khoi"), 12) or k or k_hd
        cach = "cột trong bảng" if (lay("mon") or lay("khoi")) else "tên tệp"
        key = (MD.bo_dau(m), str(k))
        nhom.setdefault(key, {"mon": m, "khoi": str(k), "rows": [], "cach": cach})
        nhom[key]["rows"].append({"ten_bai": ten_bai, "tuan": lay("tuan"),
                                  "tiet_pp": lay("tiet_pp"), "ghi_chu": lay("ghi_chu"),
                                  "digital": lay("digital"), "ai": lay("ai"), "stem": lay("stem"),
                                  "mon": m, "khoi": str(k)})
    phan = []
    for key, g in nhom.items():
        _gop(phan, g["mon"], g["khoi"], g["rows"], g["cach"])
    return phan


# ---------------------------------------------------------------- gom phần
def _gop(phan, mon, khoi, rows, cach=""):
    """Gộp các bảng cùng môn + khối vào một phần (một PPCT có thể trải nhiều bảng)."""
    mon, khoi = _gon(mon), str(khoi or "").strip()
    for p in phan:
        if MD.bo_dau(p["mon"]) == MD.bo_dau(mon) and str(p["khoi"]) == khoi:
            p["rows"].extend(rows)
            p["so_dong"] = len(p["rows"])
            if cach and cach not in p["cach"]:
                p["cach"].append(cach)
            return p
    phan.append({"mon": mon, "khoi": khoi, "rows": list(rows), "so_dong": len(rows),
                 "cach": [cach] if cach else []})
    return phan[-1]


def tach(data, ten_tep="", ds_mon=(), mac_dinh_mon="", mac_dinh_khoi="", toi_da_phan=TOI_DA_PHAN):
    """Tách một tệp thành các phần theo môn + khối.

    Trả về list phần: [{'mon','khoi','rows','so_dong','cach','nguon'}]; rỗng nếu tệp không có bảng bài học.
    """
    ten_tep = _gon(ten_tep)
    if _la_excel(ten_tep, data):
        phan = _tach_bang_tinh(data, ten_tep, ds_mon)
    else:
        phan = _tach_word(data, ten_tep, ds_mon)

    mon_tep, khoi_tep = MD.tu_ten_tep(ten_tep, ds_mon)
    mot_phan = len(phan) <= 1          # tệp chỉ một phần → ô thầy/cô điền luôn được ưu tiên
    for p in phan:
        tu_cot = any("cột" in c for c in p["cach"])
        if mac_dinh_mon and (not p["mon"] or (mot_phan and not tu_cot)):
            p["mon"], p["cach"] = mac_dinh_mon, list(p["cach"]) + ["ô Môn thầy/cô điền"]
        elif not p["mon"] and mon_tep:
            p["mon"], p["cach"] = mon_tep, list(p["cach"]) + ["tên tệp"]
        if mac_dinh_khoi and (not p["khoi"] or (mot_phan and not tu_cot)):
            p["khoi"], p["cach"] = str(mac_dinh_khoi), list(p["cach"]) + ["ô Khối thầy/cô chọn"]
        elif not p["khoi"] and khoi_tep:
            p["khoi"], p["cach"] = khoi_tep, list(p["cach"]) + ["tên tệp"]
    gop = []
    for p in phan:
        _gop(gop, p["mon"], p["khoi"], p["rows"], " · ".join(dict.fromkeys(p["cach"])))
    for p in gop:
        p["mon"] = MD.chuan_mon(p["mon"])
        p["nguon"] = ten_tep
    gop = gop[:toi_da_phan]
    for p in gop:
        p["rows"] = no_rong_tuan_tiet(p["rows"])[:TOI_DA_DONG]
        p["so_dong"] = len(p["rows"])
    return gop


def rows_kho(phan):
    """Đổi dòng sang dạng KHDH (week/topic/title/periods…) để lưu thẳng vào kho KHDH."""
    ra = []
    for d in phan:
        ra.append({"week": d.get("tuan", ""), "topic": "", "title": d.get("ten_bai", ""),
                   "periods": d.get("tiet_pp", ""), "digital": d.get("digital", ""),
                   "ai": d.get("ai", ""), "stem": d.get("stem", ""), "notes": d.get("ghi_chu", "")})
    return ra


def ghi_chu_ppct(dong):
    """Ghi chú cho bảng PPCT: giữ ghi chú gốc, thêm mã tích hợp nếu tệp có cột đó."""
    phan = [dong.get("ghi_chu") or ""]
    for khoa, nhan in (("digital", "NLS"), ("ai", "AI"), ("stem", "STEM")):
        v = (dong.get(khoa) or "").strip()
        kd = MD.bo_dau(v)
        if not v or kd in ("stem", "steam", "nls", "ai", "khong", "khong co"):
            continue
        if kd in ("x", "v", "co", "✓", "có"):        # ô tích trong tệp: chỉ ghi nhãn, không ghi “x”
            phan.append(nhan)
        else:
            phan.append("%s: %s" % (nhan, v))
    return " · ".join([p for p in phan if p])[:300]


def tom_tat(phan):
    """Chuỗi mô tả ngắn: “3 phần: Toán 6 · Toán 7 · Tin học 10”."""
    if not phan:
        return ""
    ds = []
    for p in phan:
        ten = p["mon"] or "chưa rõ môn"
        if p["khoi"]:
            ten += " " + str(p["khoi"])
        ds.append(ten)
    return "%d phần: %s" % (len(phan), " · ".join(ds))

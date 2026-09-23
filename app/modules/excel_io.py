"""Đọc / ghi bảng điểm — nhận xét (Excel, Word, CSV), bất kỳ bố cục nào."""
import csv
import io
import os
import re
import unicodedata
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter


def _norm(s):
    s = str(s).replace("Đ", "D").replace("đ", "d")
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", s)


ALIAS = {
    "ho_ten": ["hoten", "hovaten", "hovatenhocsinh", "tenhocsinh", "tenhs", "hocsinh",
               "hs", "name", "fullname", "hovatenhs"],
    "diem": ["diem", "diemtb", "diemtrungbinh", "dtb", "score", "diemso", "tbm", "diemthi",
             "diemtongket", "diemtk", "diemhk", "diemcanam", "trungbinhmon"],
    "muc_do": ["mucdo", "mucdodat", "mucdat", "mucdatduoc", "xeploai", "danhgia", "ketqua",
               "muc", "level", "hoanthanh", "kqh", "kqht", "ketquahoctap", "xeploaihocluc"],
    "nhan_xet_goc": ["nhanxet", "nhanxetgv", "nhanxetcuagiaovien", "nhanxetmon", "nhanxetmonhoc",
                     "ghichu", "note", "comment", "nx", "ykien", "nhanxethocsinh"],
    "lop": ["lop", "class", "tenlop"],
    "mon": ["mon", "monhoc", "subject"],
    "ma_hs": ["mahs", "ma", "sobaodanh", "id"],
}

# ưu tiên cột điểm: tổng kết / TB trước, điểm lẻ sau
_DIEM_UU = {
    "diemtb": 0, "diemtrungbinh": 0, "tbm": 0, "dtb": 0, "diemtongket": 0, "diemtk": 0,
    "diem": 1, "diemso": 1, "score": 1, "diemhk": 1, "diemcanam": 1, "trungbinhmon": 0,
}


def _nhan_mot_cot(ten):
    """Trả (key, ưu_tiên) hoặc None. Số nhỏ = khớp tốt hơn."""
    n = _norm(ten)
    if not n or n in ("stt", "tt", "sothutu", "sott"):
        return None
    if n in ("ho", "holot", "hodem", "hothuonggoi"):
        return "ho", 0
    if n in ("ten",) or "hoten" in n or n in ALIAS["ho_ten"]:
        return "ho_ten", 0
    if "mucdat" in n or n in ("mucdo", "mucdodat", "xeploaihocluc", "kqh", "kqht"):
        return "muc_do", 0
    if n in ALIAS["muc_do"] or (n.startswith("muc") and "dat" in n):
        return "muc_do", 1
    if (n in ALIAS["nhan_xet_goc"] or "nhanxet" in n or n.startswith("ghichu")
            or n.startswith("ykien") or n in ("nx", "comment", "remarks")):
        return "nhan_xet_goc", 0
    # Bảng điểm xuất từ phần mềm trường (VN.Edu, SMAS...): "KT CK2", "KT GK1", "XL CK2"...
    sau_tl = ("sauthilai" in n) or ("thilai" in n) or n.endswith("sau")
    if sau_tl and (n.startswith("kt") or n.startswith("xl")):
        return ("diem" if n.startswith("kt") else "muc_do"), 7
    if re.match(r"^kt(gk|ck|giuaky|cuoiky)?\d*$", n):
        return "diem", 3
    if re.match(r"^xl(gk|ck)?\d*$", n):
        return "muc_do", 3
    if n in ALIAS["diem"] or n.startswith("diem") or n in ("tbm", "dtb", "score"):
        return "diem", _DIEM_UU.get(n, 2 if n.startswith("diem") else 1)
    if n in ALIAS["lop"] or n.startswith("lop"):
        return "lop", 0
    if n in ALIAS["mon"] or n.startswith("monhoc"):
        return "mon", 0
    if n in ALIAS["ma_hs"]:
        return "ma_hs", 1
    return None


def map_columns(cols):
    """Ánh xạ tên cột gốc → khoá (ho_ten, diem, muc_do, ...). Giữ tương thích cũ."""
    chon = {}  # key -> (uu, ten_cot)
    for c in cols:
        hit = _nhan_mot_cot(c)
        if not hit:
            continue
        key, uu = hit
        if key not in chon or uu < chon[key][0]:
            chon[key] = (uu, c)
    return {ten: key for key, (_uu, ten) in chon.items()}


def read_table(file_storage):
    name = (file_storage.filename or "").lower()
    data = file_storage.read()
    bio = io.BytesIO(data)
    if name.endswith(".csv"):
        df = pd.read_csv(bio)
    else:
        df = pd.read_excel(bio)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.loc[:, ~df.columns.str.match(r"^Unnamed")] if len(df.columns) else df
    return df


NORM_MD = {"cht": "CHT", "chuahoanthanh": "CHT", "chuadat": "CHT", "yeu": "CHT", "kem": "CHT",
           "ht": "HT", "hoanthanh": "HT", "dat": "HT", "tb": "HT", "trungbinh": "HT", "kha": "HT",
           "htt": "HTT", "hoanthanhtot": "HTT", "tot": "HTT", "gioi": "HTT", "xuatsac": "HTT",
           "hoanthanhchua": "CHT", "chua": "CHT",
           # viết tắt trong bảng điểm phần mềm trường (VN.Edu/SMAS): T/H/C, CD
           "t": "HTT", "h": "HT", "c": "CHT", "cd": "CHT"}


def chuan_muc_do(v):
    if v is None or str(v).strip() == "" or str(v).lower() == "nan":
        return None
    return NORM_MD.get(_norm(v))


def _o(v):
    if v is None:
        return ""
    try:
        if str(v).lower() == "nan":
            return ""
    except Exception:
        pass
    return str(v).strip()


def _la_ten(s):
    s = _o(s)
    if len(s) < 4 or len(s) > 70 or re.search(r"\d", s):
        return False
    tu = [t for t in re.split(r"\s+", s) if t]
    return 2 <= len(tu) <= 6


def _diem_so(v):
    s = _o(v).replace(",", ".")
    if not s:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        x = float(m.group(0))
    except Exception:
        return None
    if x < 0 or x > 100:
        return None
    return x


def _diem_hang_tieu_de(hang):
    mp = map_columns(hang)
    d = 0
    if "ho_ten" in mp.values():
        d += 3
    if "ho" in mp.values() or "ten" in mp.values():
        d += 2
    if "diem" in mp.values():
        d += 2
    if "muc_do" in mp.values():
        d += 2
    if "nhan_xet_goc" in mp.values():
        d += 1
    # hàng toàn số / tên học sinh thì không phải tiêu đề
    ten_ok = sum(1 for x in hang if _la_ten(x))
    if ten_ok >= 2:
        d -= 3
    return d, mp


def _chon_tieu_de(luoi):
    tot, mp, idx = -1, {}, 0
    for i, hang in enumerate(luoi[:12]):
        d, m = _diem_hang_tieu_de(hang)
        if d > tot:
            tot, mp, idx = d, m, i
    return idx, mp, tot


def _cot_ten_doan(luoi, hdr, mp):
    if "ho_ten" in mp.values():
        return mp
    best, best_n = None, 0
    ncol = max((len(h) for h in luoi), default=0)
    used = set(mp.keys())
    for j in range(ncol):
        ten = hdr[j] if j < len(hdr) else ""
        if _norm(ten) in ("stt", "tt"):
            continue
        n = 0
        for hang in luoi:
            if j < len(hang) and _la_ten(hang[j]):
                n += 1
        if n > best_n:
            best, best_n = j, n
    if best is not None and best_n >= 2:
        ten = hdr[best] if best < len(hdr) else "Họ và tên"
        mp = dict(mp)
        mp[ten] = "ho_ten"
        mp["_idx_ho_ten"] = best
    return mp


def _them_cot_ten_phu(luoi, hi, hdr, mp):
    """VN.Edu/SMAS: 'Họ và tên' gộp 2 cột (Họ | Tên) mà cột Tên không có tiêu đề riêng."""
    vals_mp = set(mp.values())
    imap = {t: i for i, t in enumerate(hdr)}
    # (a) Cột 'Họ' + cột 'Tên' có tiêu đề riêng cạnh nhau: đổi key cột 'Tên' → ten
    if "ho" in vals_mp and "ten" not in vals_mp:
        j_ho = max((imap.get(t, -1) for t, k in mp.items() if k == "ho"), default=-1)
        for t, k in list(mp.items()):
            if k == "ho_ten" and _norm(t) == "ten" and abs(imap.get(t, -1) - j_ho) == 1:
                mp[t] = "ten"
                vals_mp = set(mp.values())
                break
    # (b) 'Họ và tên' gộp 2 cột, cột Tên bên cạnh không có tiêu đề
    if "ho" in vals_mp or "ten" in vals_mp or "ho_ten" not in vals_mp:
        return mp
    j_ht = max((imap.get(t, -1) for t, k in mp.items() if k == "ho_ten"), default=-1)
    j_ten = j_ht + 1
    if j_ten < 0 or j_ten >= len(hdr) or hdr[j_ten] in mp:
        return mp
    goc = _norm(hdr[j_ten])
    if goc and not re.match(r"^cot\d+$", goc):
        return mp  # cột bên cạnh có tiêu đề riêng → không phải cột Tên
    day = [_o(h[j_ten]) for h in luoi[hi + 1:] if j_ten < len(h) and _o(h[j_ten])]
    if len(day) < 2:
        return mp
    mot_tu = sum(1 for v in day if v.isalpha() and " " not in v and len(v) >= 2)
    if mot_tu * 10 < len(day) * 6:  # ≥60% ô là 1 từ → mới coi là cột Tên
        return mp
    mp[hdr[j_ten]] = "ten"
    return mp


def _hang_thanh_rec(hang, hdr, mp, idx_map, i, lop_o="", mon_o=""):
    rec = {"hang": i, "ho_ten": "", "diem": None, "muc_do": None, "nhan_xet_goc": "",
           "lop": lop_o, "mon": mon_o}
    ho_lot = ten = ""
    for ten_cot, key in mp.items():
        if str(ten_cot).startswith("_"):
            continue
        j = idx_map.get(ten_cot)
        if j is None:
            continue
        v = hang[j] if j < len(hang) else ""
        if key == "diem":
            rec["diem"] = _diem_so(v)
        elif key == "muc_do":
            rec["muc_do"] = chuan_muc_do(v)
        elif key == "ho":
            ho_lot = _o(v)
        elif key == "ten":
            ten = _o(v)
        elif key in ("ho_ten", "nhan_xet_goc", "lop", "mon"):
            s = _o(v)
            if s:
                rec[key] = s
    if ho_lot or ten:
        ung_cu = [rec["ho_ten"]]
        if ho_lot and ten:
            ung_cu.append(ho_lot + " " + ten)
        if ho_lot:
            ung_cu.append(ho_lot)
        if ten:
            ung_cu.append((rec["ho_ten"] + " " + ten).strip())
        gh = max((u for u in ung_cu if u), key=len)
        if gh and len(gh) > len(rec["ho_ten"]):
            rec["ho_ten"] = gh
    if not rec["ho_ten"]:
        j = mp.get("_idx_ho_ten")
        if j is not None and j < len(hang):
            rec["ho_ten"] = _o(hang[j])
    return rec


def _idx_map(hdr):
    return {ten: i for i, ten in enumerate(hdr)}


def _luoi_thanh_bang(luoi, loai, sheet="", sheet_i=0):
    if not luoi:
        return None
    hi, mp, diem = _chon_tieu_de(luoi)
    if diem < 2:
        return None
    hdr = [(_o(x) or "Cột %d" % (j + 1)) for j, x in enumerate(luoi[hi])]
    # tên cột trùng: thêm hậu tố
    dem = {}
    hdr2 = []
    for t in hdr:
        dem[t] = dem.get(t, 0) + 1
        hdr2.append(t if dem[t] == 1 else "%s (%d)" % (t, dem[t]))
    hdr = hdr2
    mp = map_columns(hdr)
    mp = _cot_ten_doan(luoi[hi + 1:], hdr, mp)
    mp = _them_cot_ten_phu(luoi, hi, hdr, mp)
    if ("ho_ten" not in mp.values() and "ho" not in mp.values()
            and "_idx_ho_ten" not in mp):
        return None
    imap = _idx_map(hdr)
    rows = []
    for i, hang in enumerate(luoi[hi + 1:], start=hi + 1):
        rec = _hang_thanh_rec(hang, hdr, mp, imap, i)
        if rec["ho_ten"] and _la_ten(rec["ho_ten"]):
            rows.append(rec)
        elif rec["ho_ten"] and rec["diem"] is not None:
            rows.append(rec)
    if len(rows) < 1:
        return None
    ten_nx = next((t for t, k in mp.items() if k == "nhan_xet_goc"), None)
    cot_nx = imap[ten_nx] if ten_nx in imap else len(hdr)
    if ten_nx is None:
        ten_nx = "Nhận xét"
    return {"loai": loai, "sheet": sheet, "sheet_i": sheet_i, "hang_tieu_de": hi,
            "hdr": hdr, "mp": mp, "rows": rows, "ten_nx": ten_nx, "cot_nx": cot_nx,
            "so_cot": len(hdr)}


def _doc_xlsx(data):
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    tot = []
    try:
        for si, ws in enumerate(wb.worksheets):
            luoi = []
            for row in ws.iter_rows(values_only=True, max_row=800, max_col=40):
                luoi.append([_o(x) for x in row])
            while luoi and all(not x for x in luoi[-1]):
                luoi.pop()
            b = _luoi_thanh_bang(luoi, "xlsx", ws.title, si)
            if b:
                tot.append(b)
    finally:
        wb.close()
    return tot


def _doc_csv(data):
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1258", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except Exception:
            continue
    if text is None:
        text = data.decode("utf-8", "replace")
    snif = csv.Sniffer()
    try:
        dialect = snif.sniff(text[:4000], delimiters=",;\t")
    except Exception:
        dialect = csv.excel
    luoi = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    b = _luoi_thanh_bang(luoi, "csv", "csv", 0)
    return [b] if b else []


def _doc_docx(data):
    from docx import Document
    doc = Document(io.BytesIO(data))
    tot = []
    for si, table in enumerate(doc.tables):
        luoi = [[_o(c.text) for c in row.cells] for row in table.rows]
        b = _luoi_thanh_bang(luoi, "docx", "bảng %d" % (si + 1), si)
        if b:
            tot.append(b)
    return tot


def doc_tep_hs(data, ten_tep=""):
    """Đọc Excel / Word / CSV bất kỳ. Trả (ok, thông_báo, bang|None)."""
    ten = (ten_tep or "").lower()
    if not data:
        return False, "Tệp trống.", None
    if len(data) > 8 * 1024 * 1024:
        return False, "Tệp lớn hơn 8 MB — hãy lưu gọn lại rồi thử lại.", None
    try:
        if ten.endswith(".docx"):
            ds = _doc_docx(data)
        elif ten.endswith(".csv") or ten.endswith(".txt"):
            ds = _doc_csv(data)
        elif ten.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(data), header=None)
            luoi = [[_o(x) for x in row] for row in df.fillna("").values.tolist()]
            b = _luoi_thanh_bang(luoi, "xls", "Sheet", 0)
            ds = [b] if b else []
        elif ten.endswith(".xlsx") or ten.endswith(".xlsm") or not ten:
            ds = _doc_xlsx(data)
        else:
            return False, "Định dạng chưa hỗ trợ — hãy dùng Excel (.xlsx), Word (.docx) hoặc CSV.", None
    except Exception:
        return False, "Không đọc được tệp. Hãy lưu lại .xlsx / .docx rồi thử lại.", None
    ds = [b for b in ds if b and b.get("rows")]
    if not ds:
        return False, ("Không thấy cột họ tên / điểm / mức đạt. "
                       "Tệp cần có bảng với cột tên học sinh và cột điểm hoặc mức đạt được."), None
    bang = max(ds, key=lambda b: len(b["rows"]))
    cot = []
    if any(k == "diem" for k in bang["mp"].values()):
        cot.append("điểm")
    if any(k == "muc_do" for k in bang["mp"].values()):
        cot.append("mức đạt")
    if any(k == "nhan_xet_goc" for k in bang["mp"].values()):
        cot.append("nhận xét (sẽ ghi đè)")
    else:
        cot.append("sẽ thêm cột Nhận xét")
    tb = "Đã đọc %d học sinh từ %s — cột: %s." % (len(bang["rows"]), bang.get("sheet") or ten_tep, ", ".join(cot))
    return True, tb, bang


def dien_vao_tep_goc(data, ten_tep, bang, records):
    """Ghi nhận xét vào đúng cột (tạo cột nếu thiếu), giữ nguyên các cột khác."""
    ten = (ten_tep or "").lower()
    mp_hang = {r.get("hang"): r for r in records if r.get("hang") is not None}
    if ten.endswith(".docx"):
        return _dien_docx(data, bang, mp_hang)
    if ten.endswith(".csv") or ten.endswith(".txt"):
        return _dien_csv(data, bang, mp_hang)
    if ten.endswith(".xls"):
        return _dien_xls(data, bang, mp_hang)
    return _dien_xlsx(data, bang, mp_hang)


def _dien_ghi(ws, bang, mp_hang):
    """Điền nhận xét vào worksheet (dùng chung cho .xlsx và .xls-đổi-đuôi)."""
    cot = int(bang.get("cot_nx") or 0) + 1  # 1-based
    hi = int(bang.get("hang_tieu_de") or 0) + 1
    ten_nx = bang.get("ten_nx") or "Nhận xét"
    # thêm cột nếu chưa có
    da_co = False
    for cell in ws[hi]:
        if cell.value and _norm(cell.value) and "nhanxet" in _norm(cell.value):
            cot = cell.column
            da_co = True
            break
    if not da_co:
        # nếu cot_nx đã nằm trong bảng gốc thì vẫn ghi vào đó (cột trống đặt tên)
        ws.cell(hi, cot, ten_nx)
        ws.cell(hi, cot).font = Font(bold=True)
        ws.cell(hi, cot).fill = PatternFill("solid", fgColor="D6EFE6")
    wrap = Alignment(wrap_text=True, vertical="top")
    for hang0, rec in mp_hang.items():
        nx = rec.get("nhan_xet") or ""
        c = ws.cell(int(hang0) + 1, cot, nx)
        c.alignment = wrap
    if ws.column_dimensions[get_column_letter(cot)].width or 0 < 28:
        ws.column_dimensions[get_column_letter(cot)].width = 48


def _dien_xls(data, bang, mp_hang):
    """File .xls (Excel 97-2003): chép nguyên ô sang workbook xlsx mới rồi điền."""
    sheets = pd.read_excel(io.BytesIO(data), header=None, sheet_name=None)
    if not sheets:
        raise ValueError("Tệp Excel trống")
    df = sheets.get(bang.get("sheet"))
    if df is None:
        idx = min(int(bang.get("sheet_i") or 0), len(sheets) - 1)
        df = list(sheets.values())[idx]
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for row in df.fillna("").values.tolist():
        ws.append([_o(x) for x in row])
    _dien_ghi(ws, bang, mp_hang)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def _dien_xlsx(data, bang, mp_hang):
    wb = load_workbook(io.BytesIO(data))
    ws = None
    if bang.get("sheet") and bang["sheet"] in wb.sheetnames:
        ws = wb[bang["sheet"]]
    else:
        ws = wb.worksheets[min(int(bang.get("sheet_i") or 0), len(wb.worksheets) - 1)]
    _dien_ghi(ws, bang, mp_hang)
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def _dien_csv(data, bang, mp_hang):
    text = data.decode("utf-8-sig", "replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4000], delimiters=",;\t")
    except Exception:
        dialect = csv.excel
    rows = [list(r) for r in csv.reader(io.StringIO(text), dialect)]
    cot = int(bang.get("cot_nx") or 0)
    hi = int(bang.get("hang_tieu_de") or 0)
    while hi < len(rows) and cot >= len(rows[hi]):
        rows[hi].append("")
    if hi < len(rows):
        if cot >= len(rows[hi]):
            rows[hi].append(bang.get("ten_nx") or "Nhận xét")
            cot = len(rows[hi]) - 1
        elif not _o(rows[hi][cot]) or "nhanxet" not in _norm(rows[hi][cot]):
            if cot == len(rows[hi]):
                rows[hi].append(bang.get("ten_nx") or "Nhận xét")
            elif cot < len(rows[hi]) and not _o(rows[hi][cot]):
                rows[hi][cot] = bang.get("ten_nx") or "Nhận xét"
    for hang0, rec in mp_hang.items():
        i = int(hang0)
        if i >= len(rows):
            continue
        while cot >= len(rows[i]):
            rows[i].append("")
        rows[i][cot] = rec.get("nhan_xet") or ""
    out = io.StringIO()
    w = csv.writer(out, dialect)
    w.writerows(rows)
    bio = io.BytesIO(out.getvalue().encode("utf-8-sig"))
    bio.seek(0)
    return bio


def _dien_docx(data, bang, mp_hang):
    from docx import Document
    doc = Document(io.BytesIO(data))
    si = int(bang.get("sheet_i") or 0)
    if si >= len(doc.tables):
        si = 0
    table = doc.tables[si]
    cot = int(bang.get("cot_nx") or 0)
    hi = int(bang.get("hang_tieu_de") or 0)
    # thêm cột? python-docx khó thêm cột — ghi vào ô cuối hoặc ô nhận xét có sẵn
    ncol = len(table.rows[0].cells) if table.rows else 0
    if cot >= ncol:
        cot = ncol - 1 if ncol else 0
    if hi < len(table.rows) and cot < len(table.rows[hi].cells):
        if not _o(table.rows[hi].cells[cot].text):
            table.rows[hi].cells[cot].text = bang.get("ten_nx") or "Nhận xét"
    for hang0, rec in mp_hang.items():
        i = int(hang0)
        if i >= len(table.rows):
            continue
        cells = table.rows[i].cells
        j = cot if cot < len(cells) else len(cells) - 1
        if j >= 0:
            cells[j].text = rec.get("nhan_xet") or ""
    bio = io.BytesIO()
    doc.save(bio)
    bio.seek(0)
    return bio


def ten_tai(ten_goc):
    ten = ten_goc or "bang-diem.xlsx"
    goc, cham, duoi = ten.rpartition(".")
    if not cham:
        return ten + "-nhan-xet.xlsx"
    if duoi.lower() == "xls":
        duoi = "xlsx"
    return "%s-nhan-xet.%s" % (goc or "bang", duoi)


def luu_tam(uid, data, ten_tep, bang, records=None):
    thu = os.environ.get("DB_DIR") or "/tmp"
    os.makedirs(thu, exist_ok=True)
    open(os.path.join(thu, "nx_%s.bin" % uid), "wb").write(data)
    ds = records if records is not None else bang.get("rows") or []
    meta = {"ten": ten_tep, "loai": bang.get("loai"), "sheet": bang.get("sheet"),
            "sheet_i": bang.get("sheet_i"), "hang_tieu_de": bang.get("hang_tieu_de"),
            "cot_nx": bang.get("cot_nx"), "ten_nx": bang.get("ten_nx"),
            "hdr": bang.get("hdr"),
            "mp": {k: v for k, v in (bang.get("mp") or {}).items() if not str(k).startswith("_")},
            "rows": [{"hang": r.get("hang"), "nhan_xet": r.get("nhan_xet") or ""} for r in ds]}
    import json
    open(os.path.join(thu, "nx_%s.json" % uid), "w", encoding="utf-8").write(
        json.dumps(meta, ensure_ascii=False))


def doc_tam(uid):
    thu = os.environ.get("DB_DIR") or "/tmp"
    p = os.path.join(thu, "nx_%s.bin" % uid)
    j = os.path.join(thu, "nx_%s.json" % uid)
    if not os.path.exists(p) or not os.path.exists(j):
        return None, None
    import json
    meta = json.loads(open(j, encoding="utf-8").read())
    return open(p, "rb").read(), meta


def export_xlsx(rows, meta=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Nhan xet"
    meta = meta or {}
    hdr = ["STT", "Họ và tên", "Lớp", "Môn", "Điểm", "Mức độ", "Xếp loại", "Nhận xét"]
    ws.append([meta.get("tieu_de", "BẢNG NHẬN XÉT HỌC SINH")])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(hdr))
    ws["A1"].font = Font(bold=True, size=14)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.append([])
    ws.append(hdr)
    for c in range(1, len(hdr) + 1):
        cell = ws.cell(row=3, column=c)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D6EFE6")
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for i, r in enumerate(rows, 1):
        ws.append([i, r.get("ho_ten"), r.get("lop"), r.get("mon"), r.get("diem"),
                   r.get("muc_do"), r.get("xep_loai"), r.get("nhan_xet")])
    widths = [6, 26, 10, 14, 8, 10, 12, 80]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=4):
        row[7].alignment = Alignment(wrap_text=True, vertical="top")
        row[1].alignment = Alignment(vertical="top")
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio

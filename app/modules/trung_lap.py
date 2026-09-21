"""Kiểm tra TRÙNG LẶP / ĐẠO VĂN — đối chiếu Internet, đối chiếu kho của thầy/cô, so nhiều bài nộp.

CÁCH LÀM (nói thẳng để thầy/cô biết kết quả là gì):
  1. Đo độ giống nhau của chuỗi: TF-IDF (đếm từ có trọng số), shingle n-gram ký tự,
     độ giống chuỗi (difflib), đoạn chung dài nhất, LCS từ, tỉ lệ từ hiếm trùng nhau…
  2. Một MÔ HÌNH HỒI QUY LOGISTIC nhỏ (12 đặc trưng, ~13 tham số, huấn luyện ngay trên
     máy chủ bằng numpy, trọng số lưu ở `app/assets/ml/ml_trung_lap.json`) quyết định
     một cặp câu là "chép", "đổi vài từ nhưng vẫn chép", hay "chỉ cùng chủ đề".
     Chỉ số P/R/F1 của mô hình in ở `thong_tin()` và ghi trong báo cáo.

NÓI THẲNG VỀ GIỚI HẠN (bắt buộc đọc trước khi dùng kết quả):
  · Đây KHÔNG phải mô hình ngôn ngữ lớn, không "hiểu" nội dung, không phán quyết đạo văn.
  · Số % trong báo cáo là TỈ LỆ CHỮ TRÙNG KHỚP với nguồn tìm thấy (bằng chữ), không phải
    kết luận. Trùng lặp có thể do: đề bài, mẫu câu, dẫn chứng, khung chương trình, thuật ngữ.
  · Đối chiếu Internet chỉ thấy những gì công cụ tìm kiếm trả về: bài trong nhóm kín,
    file scan, sách giấy, hoặc bài đã xoá thì KHÔNG thấy được.
  · Không dùng để buộc tội, trừ điểm hay kết luận về một học sinh. Hãy hỏi lại, xem bản nháp,
    xem quá trình học.
"""
import io
import json
import math
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

# ------------------------------------------------------------------ hằng số, từ vựng
TOKEN = re.compile(r"[0-9A-Za-zÀ-ỹĐđ]+", re.UNICODE)
CAU_RE = re.compile(r"[^.!?…\n]+[.!?…]*")
SO = re.compile(r"^[0-9]+([.,/][0-9]+)*$")
# hư từ: không mang nội dung, bỏ ra khi so nội dung (nhưng vẫn dùng ở đặc trưng riêng)
STOP = set("""
và là của có cho các một những được trong với để khi thì mà ở ra vào trên dưới này đó kia ấy
như cũng đã sẽ đang rất hơn nên do vì nếu hay hoặc không phải về theo từ đến tại bằng bị lại
cùng sau trước giữa mỗi mọi ai gì sao thế nào sự việc cái con chiếc số cách rằng thì bởi nơi
chúng ta tôi em mình bạn họ nó anh chị thầy cô giáo các em học sinh
""".split())

TMP_DIR = "trunglap-tmp"
NGUONG_TRUNG = 0.5          # xác suất mô hình: từ mức này coi là "chép"
NGUONG_NGUYEN_VAN = 0.80    # tỉ lệ đoạn chung dài nhất: coi là "chép nguyên văn"
NGUONG_KHAC = 0.12          # dưới mức này coi như không liên quan (không đưa vào bảng)
TOI_DA_TRANG = 10           # số trang tải về tối đa cho 1 lượt đối chiếu Internet
TOI_DA_BYTE_TRANG = 700_000


# ------------------------------------------------------------------ tiền xử lý văn bản
def bo_dau(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "d")


def chuan_hoa(s):
    """Bỏ khoảng trắng thừa, chuẩn hoá nháy kép, gạch đầu dòng."""
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    s = re.sub(r"[ \t\u00a0]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def tach_cau_text(s):
    """Tách câu: trả về danh sách câu đã sạch (bỏ câu quá ngắn / chỉ có số)."""
    ra = []
    for c in CAU_RE.findall(chuan_hoa(s)):
        c = c.strip()
        if not c:
            continue
        t = TOKEN.findall(bo_dau(c))
        if len(t) < 3:
            continue
        if all(SO.match(x) for x in t):
            continue
        ra.append(c)
    return ra


def tach_doan(s):
    ra = []
    for p in re.split(r"\n\s*\n", chuan_hoa(s)):
        p = p.strip()
        if p:
            ra.append(p)
    return ra or ([s.strip()] if (s or "").strip() else [])


def tach_tu(s):
    return TOKEN.findall(bo_dau(s))


def tach_tu_noi_dung(s):
    return [t for t in tach_tu(s) if t not in STOP and len(t) > 1]


def _gram3(s):
    s = " " + re.sub(r"[^a-z0-9 ]", " ", bo_dau(s)) + " "
    s = re.sub(r"\s+", " ", s)
    return {s[i:i + 3] for i in range(max(0, len(s) - 2))}


def _n_gram_tu(tks, n=3):
    return {tuple(tks[i:i + n]) for i in range(max(0, len(tks) - n + 1))}


# ------------------------------------------------------------------ độ giống nhau
def _jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def _doan_chung_dai(a, b):
    """Độ dài ĐOẠN CHUNG DÀI NHẤT (tính theo từ) — dấu hiệu mạnh nhất của chép nguyên câu."""
    if not a or not b:
        return 0
    best = 0
    truoc = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        nay = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                nay[j] = truoc[j - 1] + 1
                if nay[j] > best:
                    best = nay[j]
        truoc = nay
    return best


def _lcs_dai(a, b):
    if not a or not b:
        return 0
    truoc = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        nay = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            nay[j] = truoc[j - 1] + 1 if ai == b[j - 1] else max(truoc[j], nay[j - 1])
        truoc = nay
    return truoc[len(b)]


def _ty_le(a, b):
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def doan_chung(a, b):
    """Trả về chính ĐOẠN CHỮ chung dài nhất (để in ra cho thầy/cô xem)."""
    ta, tb = bo_dau(a).split(), bo_dau(b).split()
    m = SequenceMatcher(None, ta, tb, autojunk=False).find_longest_match(0, len(ta), 0, len(tb))
    if not m.size:
        return ""
    goc = a.split()
    if m.a + m.size <= len(goc):
        return " ".join(goc[m.a:m.a + m.size])
    return " ".join(ta[m.a:m.a + m.size])


def _idf_cau(cac_cau):
    """IDF của từng từ, tính trên tập câu đang so (một chữ xuất hiện ở càng ít câu càng có trọng số)."""
    df = {}
    for c in cac_cau:
        for w in set(tach_tu(c)):
            df[w] = df.get(w, 0) + 1
    n = max(1, len(cac_cau))
    return {w: math.log((1.0 + n) / (1.0 + d)) + 1.0 for w, d in df.items()}


def _cos_tan_suat(ta, tb):
    """Cosine trên vector TẦN SUẤT TỪ (trọng số IDF do bộ tìm nguồn dùng để XẾP HẠNG,
    không đưa vào mô hình — để điểm của mô hình luôn tất định, chạy lại ra cùng kết quả)."""
    if not ta or not tb:
        return 0.0
    ca, cb = {}, {}
    for t in ta:
        ca[t] = ca.get(t, 0) + 1
    for t in tb:
        cb[t] = cb.get(t, 0) + 1
    chung = set(ca) & set(cb)
    if not chung:
        return 0.0
    tich = sum(ca[w] * cb[w] for w in chung)
    na = math.sqrt(sum(v * v for v in ca.values()))
    nb = math.sqrt(sum(v * v for v in cb.values()))
    if na <= 0 or nb <= 0:
        return 0.0
    return tich / (na * nb)


# ------------------------------------------------------------------ đặc trưng cho mô hình
DAC_TRUNG = [
    "jaccard_tu",          # trùng từ nội dung
    "jaccard_3gram_ky_tu", # trùng cụm 3 ký tự
    "difflib",             # độ giống chuỗi từ
    "lcs_chuan",           # LCS từ / độ dài câu ngắn hơn
    "doan_chung_chuan",    # đoạn chung dài nhất / độ dài câu ngắn hơn
    "cos_tan_suat_tu",     # cosine trên vector tần suất từ
    "jaccard_3gram_tu",    # trùng cụm 3 từ
    "tu_dai_trung",        # trùng các từ DÀI (≥6 ký tự) — thuật ngữ riêng của bài
    "trung_mo_dau",        # 3 từ nội dung đầu giống nhau
    "trung_so_lieu",       # số liệu / mốc thời gian trùng nhau
    "chenh_dai",           # lệch độ dài (1.0 = lệch hẳn)
    "log_dai",             # log độ dài câu ngắn (câu càng dài càng đáng tin)
]
_NGUONG_MO_HINH = 0.5


def _cat(x, toi_da=260):
    """Giới hạn độ dài để phép so LCS không nặng (câu dài bất thường)."""
    return x[:toi_da]


def dac_trung_cap(a, b):
    """12 đặc trưng cho một CẶP CÂU. Dùng chung cho cả huấn luyện và chạy thật.

    Tất định (không phụ thuộc thứ tự từ điển hay hạt giống ngẫu nhiên): cùng một cặp câu
    luôn cho cùng một dãy đặc trưng, nhờ vậy kết quả chạy lại không đổi.
    """
    ta, tb = tach_tu(a), tach_tu(b)
    na, nb = tach_tu_noi_dung(a), tach_tu_noi_dung(b)
    ta, tb = _cat(ta), _cat(tb)
    na, nb = _cat(na), _cat(nb)
    dai_ngan = max(1, min(len(ta), len(tb)))
    f = [
        _jaccard(set(na), set(nb)),
        _jaccard(_gram3(a), _gram3(b)),
        _ty_le(ta, tb),
        _lcs_dai(na, nb) / float(max(1, min(len(na), len(nb)))),
        _doan_chung_dai(ta, tb) / float(dai_ngan),
        _cos_tan_suat(ta, tb),
        _jaccard(_n_gram_tu(ta, 3), _n_gram_tu(tb, 3)),
    ]
    # từ dài (thuật ngữ, tên riêng, khái niệm) trùng nhau là dấu hiệu mạnh
    dai_a = {w for w in na if len(w) >= 6}
    dai_b = {w for w in nb if len(w) >= 6}
    f.append(_jaccard(dai_a, dai_b) if (dai_a and dai_b) else 0.0)
    dau_a, dau_b = na[:3], nb[:3]
    f.append(1.0 if dau_a and dau_a == dau_b else 0.0)
    so_a, so_b = {t for t in ta if SO.match(t)}, {t for t in tb if SO.match(t)}
    f.append(_jaccard(so_a, so_b) if (so_a and so_b) else 0.0)
    f.append(abs(len(ta) - len(tb)) / float(max(len(ta), len(tb), 1)))
    f.append(math.log1p(min(len(ta), len(tb))) / 6.0)
    return f


# ------------------------------------------------------------------ mô hình (numpy)
_CACHE = {}


def _duong_mo_hinh():
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "assets", "ml", "ml_trung_lap.json")


def _mo_hinh():
    if "mh" in _CACHE:
        return _CACHE["mh"]
    p = _duong_mo_hinh()
    mh = None
    if os.path.exists(p):
        try:
            mh = json.loads(Path(p).read_text(encoding="utf-8"))
        except Exception:
            mh = None
    _CACHE["mh"] = mh
    return mh


def thong_tin():
    mh = _mo_hinh()
    if not mh:
        return {"co_mo_hinh": False,
                "ten": "Chưa có mô hình trên máy chủ này",
                "chi_so": {}, "ghi_chu": "Chỉ dùng được phần đo độ giống chuỗi."}
    return {"co_mo_hinh": True, "ten": mh.get("ten", "Mô hình so cặp câu"),
            "kieu": mh.get("kieu", ""), "phien_ban": mh.get("phien_ban", ""),
            "huan_luyen_luc": mh.get("huan_luyen_luc", ""),
            "so_dac_trung": len(mh.get("dac_trung") or []),
            "chi_so": mh.get("chi_so") or {},
            "chi_so_nguong_65": mh.get("chi_so_nguong_65") or {},
            "nguong": mh.get("nguong"), "nguong_chac": mh.get("nguong_chac"),
            "so_cap_huan_luyen": mh.get("so_cap_huan_luyen"),
            "nguon_huan_luyen": mh.get("nguon_huan_luyen", ""),
            "ghi_chu": mh.get("ghi_chu", "")}


def _sigmoid(z):
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def diem_cap(a, b):
    """Xác suất 0..1 một cặp câu là "chép" theo mô hình đã huấn luyện."""
    mh = _mo_hinh()
    x = dac_trung_cap(a, b)
    if not mh:
        # không có mô hình: dùng công thức thủ công để trang vẫn chạy được
        return max(min(0.0, 1.0), 0.55 * x[2] + 0.45 * x[4])
    w = mh["trong_so"]
    tb = mh["trung_binh"]
    dl = mh["do_lech"]
    hs = mh.get("he_so_tu_do", 0.0)
    z = hs
    for i, v in enumerate(x):
        z += w[i] * ((v - tb[i]) / (dl[i] or 1.0))
    return _sigmoid(z)


def loai_cap(a, b):
    """Phân loại một cặp câu: (nhãn, xác suất, tỉ lệ đoạn chung)."""
    diem = diem_cap(a, b)
    ta, tb = _cat(tach_tu(a)), _cat(tach_tu(b))
    nv = _doan_chung_dai(ta, tb) / float(max(1, min(len(ta), len(tb))))
    if nv >= NGUONG_NGUYEN_VAN:
        return "trùng nguyên văn", diem, nv
    if diem >= NGUONG_TRUNG:
        return "chép có đổi vài từ", diem, nv
    if diem >= NGUONG_KHAC:
        return "gần giống (cần xem lại)", diem, nv
    return "không liên quan", diem, nv


# ------------------------------------------------------------------ đọc tệp người dùng gửi lên
def doc_docx(blob):
    """Đọc .docx → danh sách đoạn (lấy cả chữ trong bảng)."""
    from docx import Document
    d = Document(io.BytesIO(blob))
    ra = [p.text for p in d.paragraphs if (p.text or "").strip()]
    for t in d.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    if (p.text or "").strip():
                        ra.append(p.text)
    return ra


def doc_pdf(blob):
    """Đọc .pdf → (danh sách đoạn, thông báo lỗi nếu có)."""
    try:
        import pypdf
    except Exception:
        try:
            import PyPDF2 as pypdf
        except Exception:
            return [], "Máy chủ chưa cài thư viện đọc PDF. Thầy/cô dán văn bản trực tiếp hoặc gửi tệp .docx."
    try:
        r = pypdf.PdfReader(io.BytesIO(blob))
        ra = []
        for pg in r.pages[:60]:
            t = (pg.extract_text() or "").strip()
            if t:
                ra.extend([x.strip() for x in t.split("\n") if x.strip()])
        if not ra:
            return [], ("Tệp PDF này không có lớp chữ (bản scan/ảnh) nên chưa đọc được. "
                        "Thầy/cô gửi tệp .docx hoặc dán văn bản.")
        return ra, ""
    except Exception:
        return [], "Không mở được tệp PDF này (tệp có thể hỏng hoặc được bảo vệ bằng mật khẩu)."


def tai_lieu(tu_tep, tu_text):
    """Gom đoạn văn từ (tệp tải lên, ô dán) → (danh sách đoạn, tên hiển thị, lỗi)."""
    ra, ten, loi = [], "", ""
    if tu_tep is not None and (getattr(tu_tep, "filename", "") or "").strip():
        ten = tu_tep.filename
        blob = tu_tep.read(8 * 1024 * 1024 + 1)
        if len(blob) > 8 * 1024 * 1024:
            return [], ten, "Tệp lớn hơn 8 MB nên hệ thống chưa xử lý."
        l = ten.lower()
        if l.endswith(".docx"):
            try:
                ra = doc_docx(blob)
            except Exception:
                return [], ten, "Không mở được tệp Word này (tệp có thể hỏng hoặc đang mở ở máy khác)."
        elif l.endswith(".pdf"):
            ra, loi = doc_pdf(blob)
            if loi:
                return [], ten, loi
        elif l.endswith(".txt"):
            for enc in ("utf-8", "utf-16", "cp1258", "latin-1"):
                try:
                    ra = [x for x in blob.decode(enc).splitlines() if x.strip()]
                    break
                except Exception:
                    ra = []
            if not ra:
                return [], ten, "Không đọc được nội dung tệp văn bản này."
        else:
            return [], ten, ("Chỉ nhận tệp .docx, .pdf hoặc .txt. Với tệp .doc thầy/cô mở bằng Word rồi "
                             "“Lưu thành” .docx (hoặc dán văn bản vào ô bên dưới).")
    elif (tu_text or "").strip():
        ra = tach_doan(tu_text)
        ten = "Văn bản dán trực tiếp"
    else:
        return [], ten, "Thầy/cô chưa chọn tệp và cũng chưa dán văn bản."
    if not ra:
        return [], ten, "Không đọc được chữ nào trong tài liệu này."
    return ra, ten, ""


# ------------------------------------------------------------------ đối chiếu với kho / nguồn
def _chi_so_nhan(nhan):
    if nhan == "trùng nguyên văn":
        return 1.0
    if nhan == "chép có đổi vài từ":
        return 0.8
    if nhan == "gần giống (cần xem lại)":
        return 0.3
    return 0.0


def _ung_vien(cau, kho_cau, so=25):
    """Chọn nhanh các câu nguồn đáng so (lọc bằng shingle ký tự) để đỡ phải so tất cả."""
    g = _gram3(cau)
    ra = []
    for i, c in enumerate(kho_cau):
        gg = c.get("gram")
        if gg is None:
            gg = c["gram"] = _gram3(c["chu"])
        if not gg:
            continue
        d = len(g & gg) / float(max(1, min(len(g), len(gg))))
        if d >= 0.18:
            ra.append((d, i))
    ra.sort(reverse=True)
    return [i for _, i in ra[:so]]


def so_khop_voi_nguon(doan, nguon, soi_toi_da=400):
    """So từng câu của `doan` với kho câu `nguon` (đã dựng sẵn chỉ số).

    `nguon`: [{'ten':…, 'loai':…, 'cau': [{'chu':…}, …]}]
    Trả về (danh sách câu khớp, thống kê).
    """
    tat_ca = []
    for n in nguon:
        n["_idx"] = n.get("_idx") or []
        for c in n["cau"]:
            c.setdefault("nd", tach_tu_noi_dung(c["chu"]))
            tat_ca.append((n, c))
    kho_cau = [{"chu": c["chu"], "gram": None} for _, c in tat_ca]
    cau_doan = []
    for d in doan:
        for x in danh_dau_trich_dan([d]):
            if len(tach_tu(x["chu"])) >= 6:
                cau_doan.append(x)
    if len(cau_doan) > soi_toi_da:
        cau_doan = sorted(cau_doan, key=lambda x: -len(tach_tu(x["chu"])))[:soi_toi_da]
    ket = []
    tong_tu = sum(len(tach_tu(x["chu"])) for x in cau_doan)
    tu_trung = 0.0
    for x in cau_doan:
        c = x["chu"]
        tot, giu = None, 0.0
        for i in _ung_vien(c, kho_cau):
            n, cn = tat_ca[i]
            nhan, diem, nv = loai_cap(c, cn["chu"])
            if diem > giu:
                giu, tot = diem, (n, cn, nhan, nv)
        if not tot or giu < NGUONG_KHAC:
            continue
        n, cn, nhan, nv = tot
        do_dai = len(tach_tu(c))
        tu_trung += _chi_so_nhan(nhan) * do_dai
        ket.append({"cau": c, "nguon": n["ten"], "loai_nguon": n.get("loai", ""),
                    "cau_nguon": cn["chu"], "diem": round(giu, 3), "nhan": nhan,
                    "doan_chung": doan_chung(c, cn["chu"]),
                    "ty_le_nguyen_van": round(nv, 3), "so_tu": do_dai,
                    "trich_dan": bool(x.get("trich_dan")),
                    "cau_nguon_url": cn.get("url", "")})
    ket.sort(key=lambda x: -x["diem"])
    ty_le = (tu_trung / float(max(1, tong_tu))) * 100.0
    tk = {"so_cau_xet": len(cau_doan), "so_cau_khop": len([k for k in ket if k["diem"] >= NGUONG_TRUNG]),
          "so_tu": tong_tu, "ty_le_trung": round(ty_le, 1),
          "nguyen_van": len([k for k in ket if k["nhan"] == "trùng nguyên văn"]),
          "doi_tu": len([k for k in ket if k["nhan"] == "chép có đổi vài từ"])}
    return ket, tk


def dung_kho_cau(ten, van_ban, loai="kho", url=""):
    """Dựng cấu trúc kho câu từ một văn bản nguồn."""
    return {"ten": ten, "loai": loai, "url": url,
            "cau": [{"chu": c, "url": url} for c in tach_cau_text(van_ban)]}


# ------------------------------------------------------------------ so nhiều bài nộp với nhau
def so_khop_cheo(cac_bai, soi_toi_da=500):
    """`cac_bai`: [{'ten':…, 'cau': [câu, …]}] → bảng so từng cặp bài + đoạn trùng."""
    ket, canh_bao = [], []
    for i, b in enumerate(cac_bai):
        b["cau"] = [c for c in b["cau"] if len(tach_tu(c)) >= 6][:soi_toi_da]
        b["nd"] = {id(c): tach_tu_noi_dung(c) for c in b["cau"]}
        b["_gram"] = {id(c): None for c in b["cau"]}
    for i in range(len(cac_bai)):
        for j in range(i + 1, len(cac_bai)):
            A, B = cac_bai[i], cac_bai[j]
            if not A["cau"] or not B["cau"]:
                continue
            cap = []
            dem_a, dem_b = set(), set()
            for ia, ca in enumerate(A["cau"]):
                tot, giu = None, 0.0
                for ib, cb in enumerate(B["cau"]):
                    if ib in dem_b and len(B["cau"]) > 12:
                        continue
                    g1 = A["_gram"][id(ca)] or _gram3(ca)
                    A["_gram"][id(ca)] = g1
                    g2 = B["_gram"][id(cb)] or _gram3(cb)
                    B["_gram"][id(cb)] = g2
                    if g1 and g2 and len(g1 & g2) / float(max(1, min(len(g1), len(g2)))) < 0.18:
                        continue
                    nhan, diem, nv = loai_cap(ca, cb)
                    if diem > giu:
                        giu, tot = diem, (ib, cb, nhan, nv)
                if tot and giu >= NGUONG_KHAC:
                    ib, cb, nhan, nv = tot
                    dem_a.add(ia)
                    dem_b.add(ib)
                    cap.append({"i_a": ia, "i_b": ib, "cau_a": ca, "cau_b": cb, "diem": round(giu, 3),
                                "nhan": nhan, "ty_le_nguyen_van": round(nv, 3),
                                "doan_chung": doan_chung(ca, cb)})
            if not cap:
                continue
            cap.sort(key=lambda x: -x["diem"])
            tu_a = sum(len(tach_tu(c)) for c in A["cau"])
            tu_b = sum(len(tach_tu(c)) for c in B["cau"])
            chem_a = sum(len(tach_tu(A["cau"][k])) * _chi_so_nhan(k2["nhan"])
                         for k, k2 in [(x["i_a"], x) for x in cap if x["diem"] >= NGUONG_TRUNG])
            chem_b = sum(len(tach_tu(B["cau"][k])) * _chi_so_nhan(k2["nhan"])
                         for k, k2 in [(x["i_b"], x) for x in cap if x["diem"] >= NGUONG_TRUNG])
            # dấu hiệu chép NGUYÊN ĐOẠN: nhiều câu khớp và giữ nguyên thứ tự
            day, day_dai = [], 0
            for x in sorted([c for c in cap if c["diem"] >= NGUONG_TRUNG], key=lambda z: z["i_a"]):
                if day and x["i_a"] <= day[-1]["i_a"] + 2 and abs((x["i_b"] - x["i_a"]) - (day[-1]["i_b"] - day[-1]["i_a"])) <= 2:
                    day.append(x)
                else:
                    day = [x]
                day_dai = max(day_dai, len(day))
            if day_dai >= 3:
                canh_bao.append("“%s” và “%s”: %d câu liên tiếp khớp nhau và giữ nguyên thứ tự — "
                                "dấu hiệu chép nguyên một đoạn." % (A["ten"], B["ten"], day_dai))
            ket.append({"a": A["ten"], "b": B["ten"], "cap": cap[:40],
                        "ty_le_a": round(100.0 * chem_a / float(max(1, tu_a)), 1),
                        "ty_le_b": round(100.0 * chem_b / float(max(1, tu_b)), 1),
                        "so_cap_trung": len([c for c in cap if c["diem"] >= NGUONG_TRUNG]),
                        "nguyen_van": len([c for c in cap if c["nhan"] == "trùng nguyên văn"]),
                        "day_dai_nhat": day_dai})
    # tổng hợp theo từng bài: bài này trùng nhiều nhất với bài nào
    for b in cac_bai:
        moc = [k for k in ket if k["a"] == b["ten"] or k["b"] == b["ten"]]
        b["cao_nhat"] = max([max(k["ty_le_a"], k["ty_le_b"]) for k in moc], default=0.0)
        b["so_ban"] = len(moc)
    ket.sort(key=lambda k: -max(k["ty_le_a"], k["ty_le_b"]))
    return ket, canh_bao


# ------------------------------------------------------------------ tìm nguồn trên Internet
UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/122 Safari/537.36"),
      "Accept-Language": "vi,en;q=0.8", "Accept": "text/html,application/xhtml+xml"}
DDG = ("https://html.duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/")
BO_QUA_TEN_MIEN = ("facebook.com", "tiktok.com", "youtube.com", "instagram.com", "pinterest.",
                   "zalo.me", "shopee.", "lazada.", "google.com/url", "bing.com/ck")


def _requests():
    import requests
    return requests


def _url_that(u):
    if not u:
        return ""
    from urllib.parse import unquote
    if u.startswith("//"):                # liên kết không ghi giao thức
        u = "https:" + u
    if "uddg=" in u:
        m = re.search(r"[?&]uddg=([^&]+)", u)
        if m:
            return unquote(m.group(1))
    return u


def _ddg_post(url, truy_van, timeout=15):
    """Gọi một máy tìm kiếm DuckDuckGo (bản không cần JavaScript) và bóc kết quả."""
    import html as _html
    requests = _requests()
    ra = []
    try:
        r = requests.post(url, data={"q": truy_van}, headers=UA, timeout=timeout)
        if r.status_code != 200 or "result__a" not in r.text:
            time.sleep(2)                  # bị máy tìm kiếm chặn tạm thời → chờ rồi thử lại 1 lần
            r = requests.post(url, data={"q": truy_van}, headers=UA, timeout=timeout)
        if r.status_code != 200 or "result__a" not in r.text:
            return ra, "DuckDuckGo trả về mã %s" % r.status_code
        for b in re.split(r'<div class="result', r.text)[1:]:
            a = re.search(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
            if not a:
                continue
            u = _url_that(_html.unescape(a.group(1)))
            if not u.startswith("http"):
                continue
            sn = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', b, re.S)
            sach = lambda x: _html.unescape(re.sub(r"<[^>]+>", " ", x)).strip()
            ra.append({"url": u, "tieu_de": sach(a.group(2))[:160],
                       "trich": sach(sn.group(1))[:240] if sn else "", "may_tim": "DuckDuckGo"})
    except Exception as e:
        return ra, "Không gọi được máy tìm kiếm (%s)" % type(e).__name__
    return ra, ""


def _wiki_api(truy_van, so=3, timeout=15):
    """Tra thẳng Wikipedia tiếng Việt.

    Thử CỤM NGUYÊN VĂN trước (khớp chính xác, tỉ lệ tìm đúng trang nguồn rất cao); nếu không ra
    kết quả nào mới tra theo từ khoá. Wikipedia ổn định hơn máy tìm kiếm với câu tiếng Việt.
    """
    requests = _requests()
    ra = []
    for truy in (truy_van, truy_van.strip('"')):
        try:
            r = requests.get("https://vi.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search", "srsearch": truy, "format": "json",
                "srlimit": so, "srprop": "snippet"}, headers=UA, timeout=timeout)
            for x in (r.json().get("query", {}) or {}).get("search", [])[:so]:
                u = "https://vi.wikipedia.org/wiki/" + x["title"].replace(" ", "_")
                if any(k["url"] == u for k in ra):
                    continue
                ra.append({"url": u, "tieu_de": x["title"],
                           "trich": re.sub(r"<[^>]+>", "", x.get("snippet", ""))[:240],
                           "may_tim": "Wikipedia"})
        except Exception:
            pass
        if len(ra) >= so:
            break
    return ra


def diem_lien_quan(truy_van, ket_qua, so_tu=6):
    """Điểm liên quan của một kết quả tìm kiếm: trùng bao nhiêu từ với câu truy vấn."""
    tu = set(tach_tu_noi_dung(truy_van))
    if not tu:
        return 0.0
    chung = set(tach_tu_noi_dung((ket_qua.get("tieu_de") or "") + " " + (ket_qua.get("trich") or "")))
    return len(tu & chung) / float(min(len(tu), so_tu * 2))


def tim_nguon(truy_van, so=8, timeout=15):
    """Tìm nguồn trên Internet cho MỘT câu truy vấn.

    Gọi DuckDuckGo (bản html, nếu ít kết quả thì gọi thêm bản lite) + tra thẳng Wikipedia
    tiếng Việt, rồi xếp theo mức liên quan với câu truy vấn. Trả về (danh sách, ghi chú).
    """
    ra, ghi_chu = [], []
    kq1, gc = _ddg_post(DDG[0], truy_van, timeout)
    ra += kq1
    if len(kq1) < 4:                       # máy tìm kiếm trả ít → thử tiếp bản lite
        kq2, gc2 = _ddg_post(DDG[1], truy_van, timeout)
        ra += kq2
        gc = gc or gc2
    if gc:
        ghi_chu.append(gc)
    ra += _wiki_api(truy_van, so=3, timeout=timeout)
    for k in ra:
        k["lien_quan"] = diem_lien_quan(truy_van, k)
    du, ra2 = set(), []
    for k in sorted(ra, key=lambda x: -x["lien_quan"]):
        ten_mien = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", k["url"]))
        if any(x in k["url"] for x in BO_QUA_TEN_MIEN):
            continue
        if ten_mien in du:
            continue
        du.add(ten_mien)
        k["ten_mien"] = ten_mien
        ra2.append(k)
    return ra2[:so], "; ".join(ghi_chu)


def lam_sach_html(du_lieu):
    """Lấy chữ đọc được từ HTML (bỏ script/style/menu/chân trang)."""
    try:
        from lxml import html as LH
        cay = LH.fromstring(du_lieu if isinstance(du_lieu, bytes) else du_lieu.encode("utf-8"))
    except Exception:
        t = du_lieu.decode("utf-8", "replace") if isinstance(du_lieu, bytes) else du_lieu
        t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
        return chuan_hoa(re.sub(r"<[^>]+>", " ", t))
    for xau in ("script", "style", "noscript", "svg", "nav", "header", "footer", "form",
                "iframe", "aside", "button"):
        for e in cay.xpath("//" + xau):
            e.getparent().remove(e)
    chu = " ".join(cay.itertext())
    return chuan_hoa(chu)


def tai_trang(url, timeout=12, toi_da=TOI_DA_BYTE_TRANG):
    """Tải một trang và trả về (chữ, lỗi). Bỏ qua tệp nhị phân; giới hạn dung lượng."""
    requests = _requests()
    try:
        r = requests.get(url, headers=UA, timeout=timeout, stream=True, allow_redirects=True)
        if r.status_code != 200:
            return "", "mã %s" % r.status_code
        ct = (r.headers.get("Content-Type") or "").lower()
        if ct and not any(x in ct for x in ("text/html", "text/plain", "application/xhtml")):
            return "", "không phải trang chữ (%s)" % ct.split(";")[0]
        du, da = b"", 0
        for phan in r.iter_content(32 * 1024):
            du += phan
            da += len(phan)
            if da >= toi_da:
                break
        if not du:
            return "", "trang rỗng"
        return lam_sach_html(du), ""
    except Exception as e:
        return "", "lỗi %s" % type(e).__name__


def cau_nghi_van(doan, so=4, it_nhat=8):
    """Chọn những câu đáng đem đi tra Internet: câu dài, nhiều từ hiếm, chưa nằm trong ngoặc kép."""
    cau = []
    for c in doan:
        for x in tach_cau_text(c):
            if len(tach_tu(x)) >= it_nhat and not x.strip().startswith(">"):
                cau.append(x)
    if not cau:
        return []
    idf = _idf_cau(cau)
    def _diem(x):
        t = tach_tu_noi_dung(x)
        if not t:
            return 0.0
        return sum(idf.get(w, 1.0) for w in t) * math.log1p(len(t))
    cau.sort(key=lambda x: -_diem(x))
    ra = []
    for c in cau:
        if any(_ty_le(tach_tu(c), tach_tu(x)) > 0.6 for x in ra):
            continue
        ra.append(c)
        if len(ra) >= so:
            break
    return ra


def truy_van_tu_cau(cau, so_tu=12):
    """Biến một câu thành câu truy vấn đưa ra Internet: 10–12 từ NỘI DUNG liền nhau, GIỮ NGUYÊN DẤU.

    Giữ dấu là bắt buộc: máy tìm kiếm với tiếng Việt không dấu trả về kết quả gần như ngẫu nhiên.
    Lấy đoạn ở giữa câu vì đó thường là chỗ ít bị sửa nhất khi chép.
    """
    giu = [w for w in TOKEN.findall(cau or "") if len(bo_dau(w)) > 1 and bo_dau(w) not in STOP]
    if not giu:
        return ""
    if len(giu) <= so_tu:
        return " ".join(giu)
    giua = len(giu) // 2
    nua = so_tu // 2
    doan = giu[max(0, giua - nua):giua + nua]
    if len(doan) < 3:                     # câu rất ngắn: lấy từ đầu
        doan = giu[:so_tu]
    return " ".join(doan)


def truy_van_nguyen_van(cau, so_tu=8):
    """Lấy một CỤM LIỀN NHAU không có dấu câu ở giữa câu để tra cụm nguyên văn (bọc ngoặc kép).

    Tra cụm nguyên văn chính xác hơn hẳn tra cả câu: máy tìm kiếm và Wikipedia đều có chế độ
    khớp đúng cụm, mà câu chép lại thường chỉ bị đổi vài chỗ nên cụm giữa câu hay còn nguyên.
    """
    doan = [x.strip() for x in re.split(r"[,;:.!?…()\[\]\"“”]", chuan_hoa(cau or ""))]
    doan = [x for x in doan if len(tach_tu(x)) >= 2]
    if not doan:
        return ""
    dai_nhat = max(doan, key=lambda x: len(tach_tu(x)))
    w = dai_nhat.split()
    if len(w) <= so_tu:
        return dai_nhat.strip()
    giua = max(0, len(w) // 2 - so_tu // 2)
    return " ".join(w[giua:giua + so_tu]).strip()


def doi_chieu_internet(doan, ghi_de=(), so_truy_van=3, so_trang=TOI_DA_TRANG,
                       han_giay=75, gio=None, so_ket_qua=10):
    """Tra Internet rồi so văn bản với những trang tải về được.

    `ghi_de`: hàm nhận (sự_kiện, dữ_liệu) để ghi nhật ký hiển thị cho người dùng.
    Trả về dict kết quả (đã gồm cả trường hợp không tải được nguồn nào).
    """
    t0 = time.time()
    gio = gio or (lambda *a, **k: None)
    nghi = cau_nghi_van(doan, so=max(2, so_truy_van))
    kq = {"bat": True, "truy_van": [], "tim_thay": [], "tai_duoc": [], "khong_tai_duoc": [],
          "lay_duoc_nguon": False, "ghi_chu": "", "giay": 0}
    if not nghi:
        kq["ghi_chu"] = ("Không có câu nào đủ dài để tra Internet (cần câu từ 8 từ trở lên). "
                         "Thầy/cô có thể dán đoạn văn dài hơn.")
        return kq
    kho, da_tai = [], []
    for c in nghi:
        if time.time() - t0 > han_giay:
            kq["ghi_chu"] = "Hết thời gian tra Internet, đã dừng ở phần tìm được."
            break
        q = truy_van_nguyen_van(c)          # cụm nguyên văn → khớp chính xác
        if not q:
            continue
        q = '"%s"' % q
        kq["truy_van"].append(q)
        gio("truy_van", q)
        thay, gc = tim_nguon(q, so=so_ket_qua)
        if not thay:                        # không ra gì → tra rộng theo từ khoá
            q2 = truy_van_tu_cau(c)
            if q2:
                kq["truy_van"].append(q2)
                gio("truy_van", q2)
                thay, gc = tim_nguon(q2, so=so_ket_qua)
        kq["tim_thay"] = thay
        if gc:
            kq["ghi_chu"] = (kq["ghi_chu"] + "; " + gc).strip("; ")
        for k in kq["tim_thay"]:
            if len(da_tai) >= so_trang or time.time() - t0 > han_giay:
                break
            if k["url"] in da_tai:
                continue
            da_tai.append(k["url"])
            gio("tai", k["url"])
            chu, loi = tai_trang(k["url"])
            if loi or len(tach_tu(chu)) < 40:
                kq["khong_tai_duoc"].append({"url": k["url"], "ly_do": loi or "trang quá ít chữ"})
                continue
            kq["tai_duoc"].append({"url": k["url"], "tieu_de": k["tieu_de"],
                                   "so_tu": len(tach_tu(chu)), "may_tim": k["may_tim"]})
            kho.append(dung_kho_cau(k["tieu_de"] or k["ten_mien"], chu, loai="Internet", url=k["url"]))
    kq["lay_duoc_nguon"] = bool(kho)
    if kho:
        bang, tk = so_khop_voi_nguon(doan, kho)
        kq["bang"] = bang
        kq["tk"] = tk
    else:
        kq["bang"], kq["tk"] = [], {"so_cau_xet": 0, "so_cau_khop": 0, "so_tu": 0,
                                    "ty_le_trung": 0.0, "nguyen_van": 0, "doi_tu": 0}
    kq["giay"] = int(time.time() - t0)
    if not kq["lay_duoc_nguon"]:
        kq["ghi_chu"] = ((kq["ghi_chu"] + "; ") if kq["ghi_chu"] else "") + \
            ("Đã tra Internet nhưng chưa tải được trang nào để so (máy tìm kiếm không trả kết quả "
             "hoặc các trang chặn truy cập tự động). Kết quả bên dưới chỉ là đối chiếu trong kho của thầy/cô.")
    return kq


# ------------------------------------------------------------------ trích dẫn hợp lệ
TRICH_DAN = ("nguồn:", "theo ", "trích", "dẫn theo", "tài liệu tham khảo", "trích dẫn",
             "nguồn tham khảo", "theo tài liệu", "theo số liệu", "http")


def cau_co_trich_dan(cau, cau_truoc=""):
    """Câu này có dấu hiệu GHI NGUỒN / trích dẫn không (để không tính là đạo văn)."""
    t = bo_dau(cau)
    if cau.count('"') >= 2 or cau.count(">") >= 1:
        return True
    for k in TRICH_DAN:
        if k in t or k in cau:
            return True
    if cau_truoc and "nguon:" in bo_dau(cau_truoc):
        return True
    return False


def danh_dau_trich_dan(doan):
    """Thêm cờ `trich_dan` cho từng câu (dùng khi so khớp)."""
    ra = []
    truoc = ""
    for d in doan:
        for c in tach_cau_text(d):
            x = {"chu": c, "trich_dan": cau_co_trich_dan(c, truoc)}
            ra.append(x)
            truoc = c
    return ra


# ------------------------------------------------------------------ kho của thầy/cô
def kho_he_thong(uid, gio=None):
    """Nguồn đối chiếu sẵn có trên hệ thống: KHDH đã lưu của chính thầy/cô + khung/văn bản Bộ."""
    import sqlite3
    gio = gio or (lambda *a, **k: None)
    ra = []
    goc = Path(os.environ.get("DB_DIR", "data"))
    d = goc / "khdh" / str(uid)
    if d.exists():
        for p in sorted(d.glob("*.docx"))[:20]:
            try:
                blob = p.read_bytes()
                from docx import Document
                doc = Document(io.BytesIO(blob))
                chu = "\n".join([x.text for x in doc.paragraphs if (x.text or "").strip()])
                if len(tach_tu(chu)) >= 40:
                    ra.append(dung_kho_cau("KHDH đã lưu: " + p.stem, chu, loai="Kho KHDH"))
            except Exception:
                continue
    gio("kho", len(ra))
    # khung / văn bản pháp quy đóng gói sẵn cùng hệ thống
    thu_muc = Path(__file__).resolve().parents[1] / "assets"
    for ten, nhan in (("khung-giao-duc-ai.json", "Khung nội dung giáo dục AI (QĐ 2422/QĐ-BGDĐT)"),
                      ("khung-nang-luc-ai.json", "Khung năng lực AI cho học sinh (CV 5588/BGDĐT-GDPT)"),
                      ("khung-nld-so.json", "Khung năng lực số (TT 02/2025/TT-BGDĐT)"),
                      ("digital-framework.json", "Khung năng lực số — phụ lục chỉ báo")):
        p = thu_muc / ten
        if not p.exists():
            continue
        try:
            chu = " ".join(_gom_chu(json.loads(p.read_text(encoding="utf-8"))))
        except Exception:
            continue
        if len(tach_tu(chu)) >= 40:
            ra.append(dung_kho_cau(nhan, chu, loai="Văn bản của Bộ"))
    return ra


def _gom_chu(d, ra=None, sau=0):
    """Lấy mọi chuỗi chữ trong một JSON lồng nhau (để làm kho câu)."""
    ra = ra if ra is not None else []
    if sau > 6 or len(ra) > 4000:
        return ra
    if isinstance(d, str):
        if len(d) > 25 and not d.startswith("http"):
            ra.append(d)
    elif isinstance(d, dict):
        for v in d.values():
            _gom_chu(v, ra, sau + 1)
    elif isinstance(d, (list, tuple)):
        for v in d:
            _gom_chu(v, ra, sau + 1)
    return ra


# ------------------------------------------------------------------ tổng hợp báo cáo
def muc_do(ty_le):
    if ty_le < 5:
        return "rất thấp", "#16a34a"
    if ty_le < 15:
        return "thấp", "#65a30d"
    if ty_le < 30:
        return "trung bình", "#d97706"
    if ty_le < 50:
        return "cao", "#ea580c"
    return "rất cao", "#dc2626"


def goi_y_sua(bang):
    """Gợi ý sửa cho từng đoạn trùng (nói rõ cách xử lý, không máy móc)."""
    ra = []
    for k in bang[:12]:
        if k["nhan"] == "trùng nguyên văn":
            ra.append({"cau": k["cau"], "cach": "Viết lại bằng lời của mình, hoặc để nguyên trong ngoặc kép "
                                               "và ghi rõ nguồn (%s)." % (k["nguon"] or "nguồn")})
        elif k["nhan"] == "chép có đổi vài từ":
            ra.append({"cau": k["cau"], "cach": "Diễn giải lại ý bằng câu của mình, thêm ví dụ/số liệu riêng; "
                                               "nếu giữ ý của nguồn thì ghi nguồn."})
        else:
            ra.append({"cau": k["cau"], "cach": "Chỉ gần giống do cùng chủ đề/thuật ngữ — thường không cần sửa."})
    return ra


def gop_internet(kq, it):
    """Gộp kết quả đối chiếu Internet vào báo cáo (gọi sau khi tra xong)."""
    kq["internet"] = it
    bang = [k for k in kq["bang"] if k.get("loai_nguon") != "Internet"]
    for k in (it.get("bang") or []):
        x = dict(k)
        x["nguon"] = "%s — %s" % (x.get("nguon") or "", x.get("loai_nguon") or "Internet")
        bang.append(x)
    bang.sort(key=lambda x: -x["diem"])
    kq["bang"] = bang
    kq["tk"]["ty_le_trung_kho"] = kq["tk"].get("ty_le_trung_kho", kq["tk"]["ty_le_trung"])
    kq["tk"]["ty_le_trung_internet"] = (it.get("tk") or {}).get("ty_le_trung", 0.0)
    kq["tk"]["ty_le_trung"] = round(max(kq["tk"]["ty_le_trung_kho"],
                                         kq["tk"]["ty_le_trung_internet"]), 1)
    kq["muc"], kq["mau"] = muc_do(kq["tk"]["ty_le_trung"])
    kq["goi_y"] = goi_y_sua(kq["bang"])
    kq["trich_dan_hop_le"] = [k for k in kq["bang"] if k.get("trich_dan")]
    return kq


def phan_tich_mot_bai(doan, ten, nguon=None, gio=None):
    """Phân tích 1 bài: đối chiếu với `nguon` (mặc định: kho của thầy/cô + văn bản Bộ).

    Đối chiếu Internet chạy ở bước sau (xem `doi_chieu_internet` + `gop_internet`) vì
    phải tải trang về nên chậm hơn.
    """
    gio = gio or (lambda *a, **k: None)
    if nguon is None:
        nguon = kho_he_thong(0, gio)
    bang, tk = so_khop_voi_nguon(doan, nguon)
    kq = {"kieu": "mot_bai", "ten": ten, "doan": doan, "bang": bang, "tk": tk,
          "so_tu": sum(len(tach_tu(d)) for d in doan), "so_doan": len(doan),
          "internet": None, "kho": [n["ten"] for n in nguon]}
    if kq["so_tu"] < 120:
        kq["canh_bao_ngan"] = ("Bài chỉ có %d từ. Văn bản ngắn thì tỉ lệ %% rất dễ lệch — "
                               "kết quả chỉ để tham khảo." % kq["so_tu"])
    kq["muc"], kq["mau"] = muc_do(kq["tk"]["ty_le_trung"])
    kq["goi_y"] = goi_y_sua(bang)
    kq["trich_dan_hop_le"] = [k for k in bang if k.get("trich_dan")]
    kq["thong_tin_mo_hinh"] = thong_tin()
    return kq


def phan_tich_nhieu_bai(cac_bai, nguon=None, gio=None):
    """`cac_bai`: [(tên, danh sách đoạn)] → so chéo các bài nộp + đối chiếu kho của thầy/cô."""
    gio = gio or (lambda *a, **k: None)
    ds = [{"ten": t, "cau": [c for d in doan for c in tach_cau_text(d)]} for t, doan in cac_bai]
    cheo, canh_bao = so_khop_cheo(ds)
    if nguon is None:
        nguon = kho_he_thong(0, gio)
    kho_ket, tong = [], 0.0
    for (t, doan) in cac_bai:
        bang, tk = so_khop_voi_nguon(doan, nguon)
        kho_ket.append({"ten": t, "bang": bang[:20], "tk": tk})
        tong = max(tong, tk["ty_le_trung"])
    ty_le_cao_nhat = max([max(k["ty_le_a"], k["ty_le_b"]) for k in cheo] or [0.0])
    kq = {"kieu": "nhieu_bai", "bai": [{"ten": b["ten"], "so_cau": len(b["cau"])} for b in ds],
          "cheo": cheo, "canh_bao": canh_bao, "kho": kho_ket, "so_bai": len(cac_bai),
          "ty_le_cao_nhat": round(ty_le_cao_nhat, 1), "ty_le_kho": round(tong, 1)}
    kq["muc"], kq["mau"] = muc_do(max(ty_le_cao_nhat, tong))
    kq["thong_tin_mo_hinh"] = thong_tin()
    kq["goi_y"] = []
    for k in cheo[:8]:
        for x in k["cap"][:4]:
            kq["goi_y"].append({"cau": x["cau_a"],
                                "cach": "Trùng với bài “%s”: viết lại bằng lời của mình hoặc ghi rõ nguồn."
                                        % k["b"]})
    return kq


# ------------------------------------------------------------------ xuất báo cáo Word
def _chuan_bi_du_lieu_docx(kq):
    """Gom dữ liệu chung để ghi ra .docx (dùng cho cả 2 kiểu phân tích)."""
    d = {"tieu_de": "BÁO CÁO KIỂM TRA TRÙNG LẶP / ĐẠO VĂN",
         "muc": kq.get("muc", ""), "dong": [], "bang": [], "canh_bao": []}
    if kq["kieu"] == "mot_bai":
        d["dong"] = [("Văn bản kiểm tra", kq["ten"]),
                     ("Số từ / số đoạn", "%d từ · %d đoạn" % (kq["so_tu"], kq["so_doan"])),
                     ("Tỉ lệ trùng trong kho của thầy/cô", "%.1f%%" % kq["tk"].get("ty_le_trung_kho", kq["tk"]["ty_le_trung"])),
                     ("Tỉ lệ trùng với nguồn Internet", "%.1f%%" % (kq["tk"].get("ty_le_trung_internet", 0.0))
                      if kq.get("internet") and kq["internet"].get("lay_duoc_nguon") else "chưa đối chiếu được"),
                     ("Kết luận sơ bộ", kq["muc"])]
        for k in kq["bang"][:40]:
            d["bang"].append([k["nhan"], "%.0f%%" % (k["diem"] * 100),
                              k["nguon"] + (("\n" + k["cau_nguon_url"]) if k.get("cau_nguon_url") else ""),
                              k["cau"], k["doan_chung"]])
        if kq.get("canh_bao_ngan"):
            d["canh_bao"].append(kq["canh_bao_ngan"])
        if kq.get("internet") and not kq["internet"].get("lay_duoc_nguon"):
            d["canh_bao"].append((kq["internet"].get("ghi_chu") or "")[:300])
    else:
        d["dong"] = [("Số bài nộp so với nhau", str(kq["so_bai"])),
                     ("Tỉ lệ trùng cao nhất giữa 2 bài", "%.1f%%" % kq["ty_le_cao_nhat"]),
                     ("Tỉ lệ trùng với kho của thầy/cô", "%.1f%%" % kq["ty_le_kho"]),
                     ("Kết luận sơ bộ", kq["muc"])]
        for k in kq["cheo"][:15]:
            d["bang"].append(["%s ↔ %s" % (k["a"], k["b"]), "%.0f%% / %.0f%%" % (k["ty_le_a"], k["ty_le_b"]),
                              "%d cặp câu trùng, %d câu nguyên văn" % (k["so_cap_trung"], k["nguyen_van"]),
                              (k["cap"][0]["cau_a"][:120] if k["cap"] else ""),
                              (k["cap"][0]["cau_b"][:120] if k["cap"] else "")])
        d["canh_bao"] = list(kq["canh_bao"])
    return d


def xuat_docx(kq):
    """Ghi báo cáo ra .docx (Times New Roman 13, có bảng)."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor

    d = Document()
    st = d.styles["Normal"]
    st.font.name = "Times New Roman"
    st.font.size = Pt(13)
    t = d.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run(_chuan_bi_du_lieu_docx(kq)["tieu_de"])
    r.bold = True
    r.font.size = Pt(15)
    tt = thong_tin()
    d.add_paragraph("Mô hình: %s (P %.3f · R %.3f · F1 %.3f). Kết quả là chỉ báo kỹ thuật, "
                    "không phải kết luận đạo văn." % (
                        tt["ten"], tt["chi_so"].get("precision", 0), tt["chi_so"].get("recall", 0),
                        tt["chi_so"].get("f1", 0)))
    for k, v in _chuan_bi_du_lieu_docx(kq)["dong"]:
        p = d.add_paragraph()
        p.add_run(k + ": ").bold = True
        p.add_run(str(v))
    for c in _chuan_bi_du_lieu_docx(kq)["canh_bao"]:
        p = d.add_paragraph()
        r = p.add_run("⚠️ " + c)
        r.font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)
    bang = _chuan_bi_du_lieu_docx(kq)["bang"]
    if bang:
        d.add_paragraph()
        d.add_paragraph("Bảng chi tiết:").runs[0].bold = True
        tieu_de = ["Mức", "Độ giống", "Nguồn / cặp bài", "Câu trong bài cần kiểm tra", "Đoạn chữ trùng"]
        tb = d.add_table(rows=1, cols=len(tieu_de))
        tb.style = "Table Grid"
        for i, x in enumerate(tieu_de):
            tb.rows[0].cells[i].text = x
        for hang in bang:
            o = tb.add_row().cells
            for i, x in enumerate(hang):
                o[i].text = str(x)
    d.add_paragraph()
    p = d.add_paragraph()
    p.add_run("Lưu ý bắt buộc: ").bold = True
    p.add_run("Kết quả trên là chỉ báo kỹ thuật (đo độ giống chữ), KHÔNG phải kết luận đạo văn. "
              "Trùng lặp có thể do đề bài, mẫu câu, dẫn chứng hoặc thuật ngữ dùng chung. "
              "Đối chiếu Internet chỉ thấy nội dung mà máy tìm kiếm trả về được. "
              "Hãy hỏi lại học sinh và xem quá trình học trước khi kết luận.")
    bio = io.BytesIO()
    d.save(bio)
    bio.seek(0)
    return bio


def ten_tep_docx(kq):
    if kq["kieu"] == "mot_bai":
        goc = re.sub(r"[^\w\-]+", "-", bo_dau(kq["ten"]) or "van-ban")[:40].strip("-")
    else:
        goc = "so-%d-bai-nop" % kq.get("so_bai", 0)
    return "bao-cao-trung-lap-%s.docx" % goc

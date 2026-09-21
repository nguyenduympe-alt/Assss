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
  · Đối chiếu Internet hỏi nhiều nguồn (Wikipedia tiếng Việt + toàn văn bài, DuckDuckGo,
    Google Books, Google Tin tức, OpenAlex) rồi TẢI VỀ hàng chục → hàng trăm trang để so
    từng câu; nhưng không công cụ nào quét hết được toàn bộ Internet: bài trong nhóm kín,
    tệp scan (ảnh), sách giấy, bài đã xoá thì KHÔNG thấy được.
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


def _dung_chi_muc(kho_cau):
    """Chỉ mục ngược: cụm 3 ký tự → các câu nguồn chứa cụm đó.

    Nhờ chỉ mục này mà so được với HÀNG NGHÌN trang đã tải về (mỗi trang có thể vài trăm câu)
    mà vẫn nhanh: chỉ những câu nguồn trùng cụm mới được đem ra chấm bằng mô hình.
    """
    idx = {}
    for i, c in enumerate(kho_cau):
        g = c.get("gram")
        if g is None:
            g = c["gram"] = _gram3(c["chu"])
        for x in g:
            idx.setdefault(x, []).append(i)
    return idx


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


def _ung_vien_nhanh(cau, chi_muc, so=40):
    """Lấy ứng viên qua chỉ mục ngược (dùng khi kho câu rất lớn: hàng nghìn trang)."""
    g = _gram3(cau)
    if not g or not chi_muc:
        return [], {}
    dem = {}
    for x in g:
        for i in chi_muc.get(x, ()):
            dem[i] = dem.get(i, 0) + 1
    if not dem:
        return [], {}
    nguong = max(3, int(0.10 * len(g)))
    ra = [(v, i) for i, v in dem.items() if v >= nguong]
    if not ra:
        ra = list(dem.items())
    ra.sort(reverse=True)
    return [i for _, i in ra[:so]], dem


def so_khop_voi_nguon(doan, nguon, soi_toi_da=400):
    """So từng câu của `doan` với kho câu `nguon`.

    `nguon`: [{'ten':…, 'loai':…, 'url':…, 'cau': [{'chu':…}, …]}]
    Trả về (danh sách câu khớp, thống kê). Dùng chỉ mục cụm ký tự nên chịu được kho rất lớn
    (kho Internet có thể là hàng nghìn câu từ hàng trăm trang).
    """
    tat_ca = []
    for n in nguon:
        for c in n["cau"]:
            c.setdefault("nd", tach_tu_noi_dung(c["chu"]))
            tat_ca.append((n, c))
    kho_cau = [{"chu": c["chu"], "gram": None} for _, c in tat_ca]
    chi_muc = _dung_chi_muc(kho_cau) if len(kho_cau) > 120 else {}
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
        if chi_muc:
            ung_vien, _ = _ung_vien_nhanh(c, chi_muc)
        else:
            ung_vien = _ung_vien(c, kho_cau)
        tot, giu = None, 0.0
        for i in ung_vien:
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
                    "cau_nguon_url": cn.get("url", "") or n.get("url", "")})
    ket.sort(key=lambda x: -x["diem"])
    ty_le = (tu_trung / float(max(1, tong_tu))) * 100.0
    tk = {"so_cau_xet": len(cau_doan), "so_cau_khop": len([k for k in ket if k["diem"] >= NGUONG_TRUNG]),
          "so_tu": tong_tu, "ty_le_trung": round(ty_le, 1),
          "nguyen_van": len([k for k in ket if k["nhan"] == "trùng nguyên văn"]),
          "doi_tu": len([k for k in ket if k["nhan"] == "chép có đổi vài từ"])}
    return ket, tk


def dung_kho_cau(ten, van_ban, loai="kho", url=""):
    """Dựng cấu trúc kho câu từ một văn bản nguồn (giới hạn số câu để chạy nhanh)."""
    cau = tach_cau_text(van_ban)
    if len(cau) > 400:
        cau = sorted(cau, key=lambda x: -len(tach_tu(x)))[:400]
    return {"ten": ten, "loai": loai, "url": url,
            "cau": [{"chu": c, "url": url} for c in cau]}


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
# Mục tiêu: đối chiếu với CÀNG NHIỀU TRANG càng tốt. Toàn bộ Internet thì không công cụ nào
# quét hết được, nên cách làm ở đây là:
#   1) Sinh câu hỏi phủ ĐỀU CẢ BÀI (không chỉ 3 câu), mỗi câu hỏi là một cụm nguyên văn
#      (bọc ngoặc kép) để máy tìm kiếm khớp chính xác.
#   2) Hỏi NHIỀU nguồn: máy tìm kiếm DuckDuckGo (bản html + bản lite), Wikipedia tiếng Việt,
#      Google Books (nội dung trong sách) và Google Tin tức — nguồn nào trả lời được thì lấy.
#   3) Tải về HÀNG TRĂM trang (chạy song song nhiều luồng), có bộ nhớ đệm trên máy chủ để
#      những lần kiểm tra sau đối chiếu lại được cả những trang đã tải trước đó.
#   4) So từng câu của bài với TOÀN BỘ số câu của tất cả các trang tải được (dùng chỉ mục
#      cụm ký tự nên vẫn nhanh với hàng nghìn câu).
# Chế độ "Sâu" hỏi nhiều câu hơn, tải nhiều trang hơn và chạy lâu hơn (xem CHE_DO).
CHE_DO = {
    "tieu_chuan": {"ten": "Tiêu chuẩn", "so_truy_van": 12, "so_ket_qua": 20, "so_trang": 60,
                   "han_giay": 180, "so_song_song": 8, "trang_moi_mien": 2,
                   "theo_trang": 1, "so_wiki": 20,
                   "mo_ta": "khoảng 1–3 phút: 12 câu hỏi phủ cả bài, tối đa 60 trang"},
    "sau": {"ten": "Sâu", "so_truy_van": 40, "so_ket_qua": 40, "so_trang": 200,
            "han_giay": 480, "so_song_song": 12, "trang_moi_mien": 4,
            "theo_trang": 2, "so_wiki": 60,
            "mo_ta": "khoảng 3–8 phút: 40 câu hỏi, tối đa 200 trang, lần theo liên kết trong trang"},
}


def thong_so_che_do(che_do=None):
    return dict(CHE_DO.get(che_do or "tieu_chuan") or CHE_DO["tieu_chuan"])


UA = {"User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/122 Safari/537.36"),
      "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8", "Accept": "text/html,application/xhtml+xml"}
DDG = ("https://html.duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/")
BO_QUA_TEN_MIEN = ("facebook.com", "tiktok.com", "youtube.com", "instagram.com", "pinterest.",
                   "zalo.me", "shopee.", "lazada.", "google.com/url", "bing.com/ck",
                   "news.google.com/rss")


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


# ------------------------------------------------------------------ từ khoá / câu hỏi
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
    """Câu truy vấn rộng theo TỪ KHOÁ (giữ dấu) — dùng khi tra cụm nguyên văn không ra kết quả."""
    giu = [w for w in TOKEN.findall(cau or "") if len(bo_dau(w)) > 1 and bo_dau(w) not in STOP]
    if not giu:
        return ""
    if len(giu) <= so_tu:
        return " ".join(giu)
    giua = len(giu) // 2
    nua = so_tu // 2
    doan = giu[max(0, giua - nua):giua + nua]
    if len(doan) < 3:
        doan = giu[:so_tu]
    return " ".join(doan)


def truy_van_nguyen_van(cau, so_tu=8):
    """Lấy một CỤM LIỀN NHAU không có dấu câu ở giữa câu để tra cụm nguyên văn (bọc ngoặc kép)."""
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


def sinh_truy_van(doan, toi_da=12, it_nhat=7, toi_thieu=6):
    """Sinh danh sách câu hỏi PHỦ ĐỀU CẢ BÀI (không chỉ vài câu đầu).

    Cách làm: cắt bài thành `toi_da` khúc theo số từ, mỗi khúc chọn câu "đáng tra" nhất
    (nhiều từ hiếm, câu dài) rồi lấy cụm nguyên văn ở giữa câu đó. Nhờ vậy phần nào của bài
    cũng có cơ hội được mang đi đối chiếu.
    """
    tat_ca = []
    for d in doan:
        for x in danh_dau_trich_dan([d]):
            if x.get("trich_dan"):        # câu đã ghi nguồn thì không cần tra
                continue
            if len(tach_tu(x["chu"])) >= it_nhat:
                tat_ca.append(x["chu"])
    if not tat_ca:
        return []
    toi_da = max(1, int(toi_da))
    if len(tat_ca) <= toi_da:
        return [q for q in (truy_van_nguyen_van(c) for c in tat_ca) if q]
    idf = _idf_cau(tat_ca)

    def _diem(x):
        t = tach_tu_noi_dung(x)
        return (sum(idf.get(w, 1.0) for w in t) * math.log1p(len(t))) if t else 0.0

    tong = sum(len(tach_tu(c)) for c in tat_ca)
    khuc = [[] for _ in range(toi_da)]
    da = 0
    for c in tat_ca:
        vt = int((da + len(tach_tu(c)) / 2.0) / max(1, tong) * toi_da)
        khuc[min(toi_da - 1, max(0, vt))].append(c)
        da += len(tach_tu(c))
    ra, da_dung = [], set()
    for k in khuc:
        if not k:
            continue
        chon = max(k, key=_diem)
        q = truy_van_nguyen_van(chon)
        if q and q not in da_dung:
            da_dung.add(q)
            ra.append(q)
    # bài ngắn: lấy thêm một cụm KHÁC (lệch về nửa sau câu) để vẫn có nhiều câu hỏi đi tra
    if len(ra) < min(toi_thieu, len(tat_ca)) and len(tat_ca) <= toi_da:
        for c in sorted(tat_ca, key=lambda x: -len(tach_tu(x))):
            w = c.split()
            if len(w) >= 10:
                nua = max(1, len(w) // 2)
                q = " ".join(w[nua:nua + 8]).strip()
            else:
                q = truy_van_nguyen_van(c)
            if q and q not in da_dung and all(_ty_le(tach_tu(q), tach_tu(x)) < 0.7 for x in ra):
                da_dung.add(q)
                ra.append(q)
            if len(ra) >= min(toi_thieu, len(tat_ca) * 2):
                break
    return ra


# ------------------------------------------------------------------ từng nguồn tìm kiếm
def _ddg_post(url, truy_van, timeout=15):
    """Một máy tìm kiếm DuckDuckGo (bản không cần JavaScript). Tự thử lại 1 lần khi bị chặn tạm."""
    import html as _html
    requests = _requests()
    ra = []
    try:
        r = requests.post(url, data={"q": truy_van}, headers=UA, timeout=timeout)
        if r.status_code != 200 or "result__a" not in r.text:
            time.sleep(2)
            r = requests.post(url, data={"q": truy_van}, headers=UA, timeout=timeout)
        if r.status_code != 200 or "result__a" not in r.text:
            return ra, "DuckDuckGo mã %s" % r.status_code
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


WIKI_API = "https://vi.wikipedia.org/w/api.php"


def _wiki_search(truy_van, so=20, timeout=15):
    """Wikipedia tiếng Việt: tìm BÀI chứa cụm nguyên văn (thử cả tìm trong mã nguồn bài).

    Trả về danh sách BÀI THẬT (kèm `wiki` = tên bài) để bước sau tải TOÀN VĂN bằng API —
    nhanh hơn tải từng trang HTML rất nhiều, nên so được với số lượng bài lớn.
    """
    requests = _requests()
    so = max(1, min(int(so), 50))
    ds, ghi_chu = [], ""
    for truy in ('"%s"' % truy_van.strip('"'), 'insource:"%s"' % truy_van.strip('"')[:60],
                 " ".join(tach_tu_noi_dung(truy_van)[:10])):
        if not truy.strip():
            continue
        try:
            r = requests.get(WIKI_API, params={"action": "query", "list": "search", "srsearch": truy,
                                               "format": "json", "srlimit": so, "srnamespace": 0,
                                               "srprop": "snippet"}, headers=UA, timeout=timeout)
            if r.status_code != 200:
                ghi_chu = "Wikipedia mã %s" % r.status_code
                break
            ds = ((r.json().get("query") or {}).get("search") or [])
        except Exception as e:
            return [], "Wikipedia lỗi %s" % type(e).__name__
        if ds:
            break
    ra = []
    for x in ds[:so]:
        ten = x.get("title") or ""
        if not ten:
            continue
        ra.append({"url": "https://vi.wikipedia.org/wiki/" + _lien_wiki(ten), "tieu_de": ten,
                   "trich": re.sub(r"<[^>]+>", "", x.get("snippet") or "")[:240],
                   "may_tim": "Wikipedia", "ten_mien": "vi.wikipedia.org", "wiki": ten})
    return ra, ghi_chu


# tên cũ: giữ lại để mã/test cũ vẫn chạy
def _wiki_api(truy_van, so=3, timeout=15):
    ra, _ = _wiki_search(truy_van, so=so, timeout=timeout)
    return [{k: v for k, v in x.items() if k != "wiki"} for x in ra]


def _lien_wiki(ten):
    from urllib.parse import quote
    return quote((ten or "").replace(" ", "_"), safe="/()!,:._-")


def _wiki_noi_dung(ds, timeout=25):
    """Tải TOÀN VĂN nhiều bài Wikipedia trong MỘT request (API cho 20 bài mỗi lần)."""
    ten = [x.get("wiki") for x in ds if x.get("wiki")][:20]
    if not ten:
        return {}
    try:
        r = _requests().get(WIKI_API, params={"action": "query", "prop": "extracts", "explaintext": 1,
                                              "exlimit": 20, "titles": "|".join(ten), "format": "json",
                                              "redirects": 1}, headers=UA, timeout=timeout)
        if r.status_code != 200:
            return {}
        ra = {}
        for v in (((r.json().get("query") or {}).get("pages")) or {}).values():
            if v.get("extract"):
                ra[v.get("title")] = v["extract"]
        return ra
    except Exception:
        return {}


def _loc_lien_ket(trang, toi_da=3):
    """Chọn liên kết đáng tải tiếp trong một trang: ưu tiên CÙNG NHÁNH đường dẫn,
    bỏ trang mục lục / trang đặc biệt / trang chủ."""
    from urllib.parse import urlparse
    goc = urlparse(trang.get("url_cuoi") or trang.get("url") or "")
    nhanh = (goc.path.strip("/").split("/") or [""])[0]
    ung = []
    for u in (trang.get("lien_ket") or []):
        pu = urlparse(u)
        if pu.netloc.lower() != goc.netloc.lower():
            continue
        if not pu.path or pu.path in ("/", "/index.html", "/index.php"):
            continue
        if any(x in u for x in ("Trang_Chính", "Đặc_biệt:", "Special:", "Thể_loại:", "Category:")):
            continue
        cung = 0 if (nhanh and (pu.path.strip("/").split("/") or [""])[0] == nhanh) else 1
        ung.append((cung, u))
    ung.sort(key=lambda x: x[0])
    return [u for _, u in ung[:max(1, int(toi_da))]]


def tai_wiki_nhieu(ds, gio=None, timeout=25):
    """Tải toàn văn các bài Wikipedia tìm được → coi như những TRANG đã đối chiếu."""
    gio = gio or (lambda *a, **k: None)
    ra = []
    for i in range(0, len(ds), 20):
        lo = ds[i:i + 20]
        noi_dung = _wiki_noi_dung(lo, timeout=timeout)
        for k in lo:
            chu = noi_dung.get(k.get("wiki")) or ""
            if len(tach_tu(chu)) < 40:
                continue
            ra.append({"url": k["url"], "url_cuoi": k["url"], "chu": chu, "lien_ket": [],
                       "tieu_de": k.get("tieu_de", ""), "may_tim": "Wikipedia",
                       "ten_mien": "vi.wikipedia.org", "tu_dem": False, "tu_wiki": True,
                       "so_tu": len(tach_tu(chu))})
        gio("tai", "Wikipedia: đã lấy toàn văn %d/%d bài" % (min(i + 20, len(ds)), len(ds)))
    return ra


def _openalex(truy_van, so=10, timeout=20):
    """OpenAlex: bài báo / công trình khoa học (miễn phí, không cần khoá) — lấy TIÊU ĐỀ + TÓM TẮT."""
    try:
        r = _requests().get("https://api.openalex.org/works",
                            params={"search": truy_van.strip('"'), "per-page": max(1, min(so, 25)),
                                    "mailto": "eduassist@example.com"}, headers=UA, timeout=timeout)
        if r.status_code != 200:
            return [], "OpenAlex mã %d" % r.status_code
        ra = []
        for w in (((r.json() or {}).get("results")) or [])[:so]:
            tom = w.get("abstract_inverted_index")
            chu_tom = ""
            if tom:
                vt = {}
                for tu, ds_vt in tom.items():
                    for i in (ds_vt or [])[:12]:
                        vt[i] = tu
                chu_tom = " ".join(vt[k] for k in sorted(vt)[:150])
            doi = w.get("doi") or ((w.get("primary_location") or {}).get("landing_page_url")) or \
                "https://openalex.org/" + str(w.get("id") or "").rsplit("/", 1)[-1]
            ra.append({"url": doi, "tieu_de": w.get("title") or "(không có tiêu đề)",
                       "trich": chu_tom, "may_tim": "OpenAlex", "ten_mien": "openalex.org",
                       "chi_trich": True})
        return ra, ""
    except Exception as e:
        return [], "OpenAlex lỗi %s" % type(e).__name__


def _gbooks(truy_van, so=10, timeout=15):
    """Tra Google Books — tìm cụm chữ trong SÁCH (nhiều giáo trình, sách tham khảo tiếng Việt).

    Sách không tải về đọc được nên chỉ lấy ĐOẠN TRÍCH mà Google trả về, đủ để thấy cụm chữ
    có trong sách nào.
    """
    requests = _requests()
    ra = []
    try:
        r = requests.get("https://www.googleapis.com/books/v1/volumes", params={
            "q": truy_van, "maxResults": so, "country": "VN", "hl": "vi"},
            headers=UA, timeout=timeout)
        if r.status_code == 429:
            return ra, "Google Books: hết hạn mức truy vấn trong ngày"
        if r.status_code != 200:
            return ra, "Google Books mã %d" % r.status_code
        for x in (r.json().get("items") or []):
            v = x.get("volumeInfo") or {}
            tr = ((x.get("searchInfo") or {}).get("textSnippet") or "")
            u = (v.get("infoLink") or v.get("canonicalVolumeLink") or "") \
                or ("https://books.google.com/books?id=" + (x.get("id") or ""))
            ra.append({"url": u, "tieu_de": (v.get("title") or "Sách") +
                       ((" — " + ", ".join(v.get("authors") or [])) if v.get("authors") else ""),
                       "trich": re.sub(r"<[^>]+>", "", tr)[:400], "may_tim": "Google Books",
                       "chi_trich": True, "ten_mien": "books.google.com"})
    except Exception as e:
        return ra, "Google Books lỗi %s" % type(e).__name__
    return ra, ""


def _gnews(truy_van, so=10, timeout=15):
    """Google Tin tức (RSS): bài báo tiếng Việt cùng chủ đề.

    RSS chỉ trả về TIÊU ĐỀ + tên báo (đường dẫn là trang trung gian của Google), nên kết quả
    ở đây được dùng làm DANH SÁCH BÀI BÁO CẦN MỞ XEM TAY — không đo được chữ trùng.
    """
    requests = _requests()
    ra = []
    import html as _html
    # tra bằng TỪ KHOÁ (Google Tin tức không trả kết quả cho cụm bọc ngoặc kép)
    for truy in (" ".join(tach_tu_noi_dung(truy_van)[:12]), truy_van.strip('"')):
        if not truy.strip():
            continue
        try:
            r = requests.get("https://news.google.com/rss/search", params={
                "q": truy, "hl": "vi", "gl": "VN", "ceid": "VN:vi"}, headers=UA, timeout=timeout)
            if r.status_code != 200:
                return ra, "Google Tin tức mã %s" % r.status_code
            for b in re.findall(r"<item>(.*?)</item>", r.text, re.S)[:so]:
                t = re.search(r"<title>(.*?)</title>", b, re.S)
                l = re.search(r"<link>(.*?)</link>", b, re.S)
                nguon = re.search(r'<source url="([^"]+)"', b)
                ngay = re.search(r"<pubDate>(.*?)</pubDate>", b, re.S)
                if not l:
                    continue
                ten_bao = re.sub(r"^https?://(www\.)?", "", (nguon.group(1) if nguon else "")).strip("/")
                ra.append({"url": _html.unescape(l.group(1)).strip(),
                           "tieu_de": _html.unescape(re.sub(r"<[^>]+>", "",
                                                            t.group(1)))[:160] if t else "",
                           "trich": "", "may_tim": "Google Tin tức", "chi_trich": True,
                           "tin": True, "ten_bao": ten_bao, "ten_mien": "news.google.com",
                           "ngay": (ngay.group(1).strip()[:16] if ngay else "")})
        except Exception as e:
            return ra, "Google Tin tức lỗi %s" % type(e).__name__
        if ra:
            break
    return ra, ""


def _tu_khoa_ngan(truy_van, so_tu=6):
    """Cụm 4–6 từ khoá (máy tìm kiếm dạng API thường cần câu NGẮN, không cần ngoặc kép)."""
    t = tach_tu_noi_dung((truy_van or "").strip('"'))
    if len(t) <= so_tu:
        return " ".join(t)
    giua = max(0, len(t) // 2 - so_tu // 2)
    return " ".join(t[giua:giua + so_tu])


def _parallel_mcp(truy_van, so=10, timeout=45):
    """Parallel Web Search — máy tìm kiếm CHẠY ĐƯỢC KHÔNG CẦN KHOÁ (máy chủ MCP công khai).

    Trả về kết quả thật kèm ĐOẠN TRÍCH nội dung trang, nên vẫn so được cả khi trang gốc
    không tải về được.
    """
    import uuid
    requests = _requests()
    ra = []
    q_ngan = _tu_khoa_ngan(truy_van, 6) or truy_van.strip('"')[:60]
    q_dai = " ".join(tach_tu_noi_dung(truy_van)[:9]) or q_ngan
    than = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "web_search", "arguments": {
                "objective": "Tìm trang web chứa nguyên văn đoạn văn này (để kiểm tra trùng lặp "
                             "trong bài làm của học sinh)",
                "search_queries": [q_ngan, q_dai],
                "session_id": uuid.uuid4().hex,
                "max_results": max(3, min(int(so), 20))}}}
    try:
        r = requests.post("https://search.parallel.ai/mcp", json=than,
                          headers={"Content-Type": "application/json",
                                   "Accept": "application/json, text/event-stream",
                                   "User-Agent": UA["User-Agent"]}, timeout=timeout)
        if r.status_code != 200:
            return ra, "Parallel Search mã %s" % r.status_code
        j = r.json()
        khung = (j.get("result") or {}).get("content") or []
        du = ""
        for x in khung:
            if x.get("type") == "text":
                du += x.get("text") or ""
        if not du.strip():
            return ra, ""
        d = json.loads(du)
        for x in (d.get("results") or [])[:so]:
            u = (x.get("url") or "").strip()
            if not u.startswith("http"):
                continue
            nhan = x.get("excerpts") or x.get("snippets") or []
            if isinstance(nhan, str):
                nhan = [nhan]
            ra.append({"url": u, "tieu_de": (x.get("title") or "")[:160],
                       "trich": " … ".join(nhan)[:1500], "may_tim": "Parallel Search"})
    except Exception as e:
        return ra, "Parallel Search lỗi %s" % type(e).__name__
    return ra, ""


def _tavily(truy_van, so=10, timeout=25):
    """Tavily (cần khoá): kết quả kèm NỘI DUNG trang đã lọc sạch — so được cả khi trang gốc chặn."""
    k = _khoa("tavily")
    if not k:
        return [], ""
    if not _duoc_dung_api("tavily"):
        return [], "Tavily: đã chạm hạn mức đặt trước trong tháng"
    ra = []
    try:
        r = _requests().post("https://api.tavily.com/search", json={
            "api_key": k, "query": truy_van.strip('"'), "max_results": max(3, min(int(so), 20)),
            "search_depth": "basic", "include_answer": False, "include_raw_content": False},
            headers={"Content-Type": "application/json"}, timeout=timeout)
        _tang_dem_api("tavily")
        if r.status_code != 200:
            return ra, "Tavily mã %s" % r.status_code
        for x in ((r.json() or {}).get("results") or [])[:so]:
            ra.append({"url": x.get("url") or "", "tieu_de": (x.get("title") or "")[:160],
                       "trich": (x.get("content") or "")[:1500], "may_tim": "Tavily",
                       "ngay": (x.get("published_date") or "")[:10]})
    except Exception as e:
        return ra, "Tavily lỗi %s" % type(e).__name__
    return [x for x in ra if x["url"].startswith("http")], ""


def _serper(truy_van, so=10, timeout=25):
    """Serper (cần khoá): kết quả Google thật (organic) — bắt được cả trang web giáo án, báo, blog."""
    k = _khoa("serper")
    if not k:
        return [], ""
    if not _duoc_dung_api("serper"):
        return [], "Serper: đã chạm hạn mức đặt trước trong tháng"
    ra = []
    try:
        r = _requests().post("https://google.serper.dev/search", json={
            "q": truy_van.strip('"'), "gl": "vn", "hl": "vi", "num": max(3, min(int(so), 20))},
            headers={"X-API-KEY": k, "Content-Type": "application/json"}, timeout=timeout)
        _tang_dem_api("serper")
        if r.status_code != 200:
            return ra, "Serper mã %s" % r.status_code
        j = r.json() or {}
        for x in (j.get("organic") or [])[:so]:
            ra.append({"url": x.get("link") or "", "tieu_de": (x.get("title") or "")[:160],
                       "trich": (x.get("snippet") or "")[:600], "may_tim": "Serper (Google)"})
        kg = j.get("knowledgeGraph") or {}
        if kg.get("description"):
            ra.append({"url": kg.get("descriptionLink") or ("https://www.google.com/search?q=" +
                                                            _tu_khoa_ngan(truy_van, 6).replace(" ", "+")),
                       "tieu_de": (kg.get("title") or "")[:160], "trich": kg["description"][:600],
                       "may_tim": "Serper (Google)", "chi_trich": True})
    except Exception as e:
        return ra, "Serper lỗi %s" % type(e).__name__
    return [x for x in ra if x["url"].startswith("http")], ""


def _brave(truy_van, so=10, timeout=25):
    """Brave Search (cần khoá): chỉ mục riêng, không phụ thuộc Google."""
    k = _khoa("brave")
    if not k:
        return [], ""
    if not _duoc_dung_api("brave"):
        return [], "Brave: đã chạm hạn mức đặt trước trong tháng"
    ra = []
    try:
        r = _requests().get("https://api.search.brave.com/res/v1/web/search",
                            params={"q": truy_van.strip('"'), "count": max(3, min(int(so), 20)),
                                    "country": "vn", "search_lang": "vi", "extra_snippets": 1},
                            headers={"X-Subscription-Token": k, "Accept": "application/json"},
                            timeout=timeout)
        _tang_dem_api("brave")
        if r.status_code != 200:
            return ra, "Brave mã %s" % r.status_code
        for x in (((r.json() or {}).get("web") or {}).get("results") or [])[:so]:
            tr = x.get("description") or ""
            if x.get("extra_snippets"):
                tr += " … " + " … ".join(x["extra_snippets"])
            ra.append({"url": x.get("url") or "", "tieu_de": (x.get("title") or "")[:160],
                       "trich": tr[:1200], "may_tim": "Brave Search"})
    except Exception as e:
        return ra, "Brave lỗi %s" % type(e).__name__
    return [x for x in ra if x["url"].startswith("http")], ""


def _exa(truy_van, so=10, timeout=25):
    """Exa (cần khoá): trả cả đoạn nội dung trang tìm được."""
    k = _khoa("exa")
    if not k:
        return [], ""
    if not _duoc_dung_api("exa"):
        return [], "Exa: đã chạm hạn mức đặt trước trong tháng"
    ra = []
    try:
        r = _requests().post("https://api.exa.ai/search", json={
            "query": truy_van.strip('"'), "numResults": max(3, min(int(so), 20)),
            "contents": {"text": {"maxCharacters": 1200}}},
            headers={"x-api-key": k, "Content-Type": "application/json"}, timeout=timeout)
        _tang_dem_api("exa")
        if r.status_code != 200:
            return ra, "Exa mã %s" % r.status_code
        for x in ((r.json() or {}).get("results") or [])[:so]:
            ra.append({"url": x.get("url") or "", "tieu_de": (x.get("title") or "")[:160],
                       "trich": (x.get("text") or "")[:1200], "may_tim": "Exa",
                       "ngay": (x.get("publishedDate") or "")[:10]})
    except Exception as e:
        return ra, "Exa lỗi %s" % type(e).__name__
    return [x for x in ra if x["url"].startswith("http")], ""


def _googlecse(truy_van, so=10, timeout=25):
    """Google Programmable Search (cần khoá cũ + mã công cụ): 100 lượt/ngày miễn phí."""
    k, cx = _khoa("googlecse"), (os.environ.get("GOOGLE_CSE_CX") or "").strip()
    if not k or not cx:
        return [], ""
    if not _duoc_dung_api("googlecse"):
        return [], "Google (Programmable Search): đã chạm hạn mức đặt trước trong tháng"
    ra = []
    try:
        r = _requests().get("https://www.googleapis.com/customsearch/v1",
                            params={"key": k, "cx": cx, "q": truy_van.strip('"'),
                                    "num": max(1, min(int(so), 10)), "gl": "vn", "hl": "vi"},
                            timeout=timeout)
        _tang_dem_api("googlecse")
        if r.status_code != 200:
            return ra, "Google (Programmable Search) mã %s" % r.status_code
        for x in ((r.json() or {}).get("items") or [])[:so]:
            ra.append({"url": x.get("link") or "", "tieu_de": (x.get("title") or "")[:160],
                       "trich": (x.get("snippet") or "")[:600],
                       "may_tim": "Google (Programmable Search)"})
    except Exception as e:
        return ra, "Google (Programmable Search) lỗi %s" % type(e).__name__
    return [x for x in ra if x["url"].startswith("http")], ""


def diem_lien_quan(truy_van, ket_qua, so_tu=6):
    """Điểm liên quan của một kết quả tìm kiếm: trùng bao nhiêu từ với câu truy vấn."""
    tu = set(tach_tu_noi_dung(truy_van))
    if not tu:
        return 0.0
    chung = set(tach_tu_noi_dung((ket_qua.get("tieu_de") or "") + " " + (ket_qua.get("trich") or "")))
    return len(tu & chung) / float(min(len(tu), so_tu * 2))


NGUON_TIM = {"ddg": "DuckDuckGo", "ddg_lite": "DuckDuckGo (bản nhẹ)", "wiki": "Wikipedia",
             "gbooks": "Google Books", "gnews": "Google Tin tức", "openalex": "OpenAlex",
             "parallel": "Parallel Search", "tavily": "Tavily", "serper": "Serper (Google)",
             "brave": "Brave Search", "exa": "Exa", "googlecse": "Google (Programmable Search)"}

# Nguồn cần KHOÁ API (thầy/cô tự lấy khoá miễn phí, xem hướng dẫn ở `nguon_api()`).
# Khoá để trong /etc/eduassist.env (chỉ root đọc được), KHÔNG ghi vào mã nguồn.
API_TIM_KIEM = {
    "tavily": {"ten": "Tavily", "bien": "TAVILY_API_KEY",
               "lay_khoa": "https://app.tavily.com — gói Researcher miễn phí 1.000 lượt/tháng, không cần thẻ",
               "tra": "trả cả NỘI DUNG trang nên so được cả khi không tải được trang"},
    "serper": {"ten": "Serper (Google)", "bien": "SERPER_API_KEY",
               "lay_khoa": "https://serper.dev — 2.500 lượt miễn phí, không cần thẻ",
               "tra": "kết quả Google y như tìm trên google.com"},
    "brave": {"ten": "Brave Search", "bien": "BRAVE_API_KEY",
              "lay_khoa": "https://brave.com/search/api — có 5 USD tín dụng mỗi tháng (cần thẻ)",
              "tra": "chỉ mục riêng của Brave, không phụ thuộc Google"},
    "exa": {"ten": "Exa", "bien": "EXA_API_KEY",
            "lay_khoa": "https://exa.ai — 20 USD tín dụng khi đăng ký, không cần thẻ",
            "tra": "trả cả nội dung đoạn văn tìm được"},
    "googlecse": {"ten": "Google (Programmable Search)", "bien": "GOOGLE_CSE_KEY",
                  "lay_khoa": "khoá cũ + mã công cụ GOOGLE_CSE_CX (Google đã đóng với người mới, "
                              "ngừng 1/1/2027)",
                  "tra": "100 lượt/ngày miễn phí cho tài khoản đã có"},
}


def _khoa(ma):
    """Đọc khoá API của một nguồn từ biến môi trường (trên máy chủ: /etc/eduassist.env)."""
    return (os.environ.get(API_TIM_KIEM[ma]["bien"]) or "").strip()


def nguon_api():
    """Danh sách các nguồn cần khoá: đã bật hay chưa (để hiện lên giao diện)."""
    ra = []
    for ma, tt in API_TIM_KIEM.items():
        co = bool(_khoa(ma))
        if ma == "googlecse":
            co = co and bool((os.environ.get("GOOGLE_CSE_CX") or "").strip())
        ra.append({"ma": ma, "ten": tt["ten"], "da_bat": co, "lay_khoa": tt["lay_khoa"],
                   "tra": tt["tra"], "da_dung": _dem_api(ma) if co else 0})
    return ra


def _nguon_api_da_bat():
    return [x["ma"] for x in nguon_api() if x["da_bat"]]


def _tep_dem_api():
    return Path(os.environ.get("DB_DIR", "data")) / "api-tim-kiem-dem.json"


def _gioi_han_api():
    try:
        return max(20, int(os.environ.get("API_TIM_KIEM_TOI_DA", "500")))
    except Exception:
        return 500


def _dem_api(ma):
    """Số lượt đã gọi API trong THÁNG NÀY (để không tiêu quá hạn mức miễn phí)."""
    try:
        d = json.loads(_tep_dem_api().read_text(encoding="utf-8"))
    except Exception:
        return 0
    return int(((d.get(time.strftime("%Y-%m")) or {}).get(ma) or 0))


def _tang_dem_api(ma):
    """Tăng số lượt đã gọi API của tháng này (để tự giữ trong hạn mức miễn phí).

    Ghi ra tệp tạm rồi THAY THẾ tệp cũ (`os.replace`) — nhờ vậy tiến trình web chạy dưới
    quyền www-data vẫn cập nhật được, kể cả khi tệp cũ do root tạo và không cho ghi.
    """
    try:
        p = _tep_dem_api()
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            d = {}
        thang = time.strftime("%Y-%m")
        d = {thang: (d.get(thang) or {})}          # chỉ giữ tháng hiện tại
        d[thang][ma] = int(d[thang].get(ma, 0)) + 1
        tam = p.with_name(p.name + ".tam")
        tam.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tam, 0o666)                   # cả root và www-data đọc/ghi được
        except Exception:
            pass
        os.replace(tam, p)
    except Exception:
        pass


def _duoc_dung_api(ma):
    """Còn trong hạn mức đặt trước cho tháng này thì mới gọi (tránh tiêu hết lượt miễn phí)."""
    return _dem_api(ma) < _gioi_han_api()
_SUC_KHOE = {}          # mã nguồn → (số lỗi liên tiếp, lúc lỗi cuối) để tạm bỏ nguồn đang chặn


def _nguon_ok(ma, cho_giay=300):
    dem, luc = _SUC_KHOE.get(ma, (0, 0))
    if dem < 2:
        return True
    return (time.time() - luc) > cho_giay       # thử lại sau một lúc


def _nguon_xong(ma, duoc):
    if duoc:
        _SUC_KHOE.pop(ma, None)
    else:
        dem, _ = _SUC_KHOE.get(ma, (0, 0))
        _SUC_KHOE[ma] = (dem + 1, time.time())


def tim_nhieu_nguon(truy_van, so=20, timeout=15, nguon=None):
    """Hỏi NHIỀU nguồn tìm kiếm rồi gộp kết quả (bỏ trùng theo đường dẫn).

    Nguồn nào đang bị chặn/hết hạn mức thì tạm bỏ qua trong 5 phút để không làm chậm lượt chạy.
    Trả về (danh sách kết quả, ghi chú) — ghi chú nói rõ nguồn nào không trả lời được.
    """
    nguon = nguon or tuple(_nguon_api_da_bat()) + ("parallel", "ddg", "wiki", "ddg_lite",
                                                   "gnews", "gbooks", "openalex")
    ra, ghi_chu = [], []
    for ma in nguon:
        ten = NGUON_TIM.get(ma, ma)
        if not _nguon_ok(ma):
            ghi_chu.append("%s: tạm bỏ qua (vừa bị chặn)" % ten)
            continue
        try:
            if ma in ("ddg", "ddg_lite"):
                kq, gc = _ddg_post(DDG[0 if ma == "ddg" else 1], truy_van, timeout)
            elif ma == "wiki":
                kq, gc = _wiki_search(truy_van, so=min(20, max(5, so)), timeout=timeout)
            elif ma == "gbooks":
                kq, gc = _gbooks(truy_van, so=8, timeout=timeout)
            elif ma == "gnews":
                kq, gc = _gnews(truy_van, so=10, timeout=timeout)
            elif ma == "openalex":
                kq, gc = _openalex(truy_van, so=10, timeout=timeout)
            elif ma == "parallel":
                kq, gc = _parallel_mcp(truy_van, so=max(6, min(int(so), 20)), timeout=max(30, timeout * 2))
            elif ma == "tavily":
                kq, gc = _tavily(truy_van, so=min(15, max(5, int(so))), timeout=timeout)
            elif ma == "serper":
                kq, gc = _serper(truy_van, so=min(20, max(5, int(so))), timeout=timeout)
            elif ma == "brave":
                kq, gc = _brave(truy_van, so=min(20, max(5, int(so))), timeout=timeout)
            elif ma == "exa":
                kq, gc = _exa(truy_van, so=min(20, max(5, int(so))), timeout=timeout)
            elif ma == "googlecse":
                kq, gc = _googlecse(truy_van, so=min(10, max(5, int(so))), timeout=timeout)
            else:
                kq, gc = [], ""
        except Exception as e:
            kq, gc = [], "%s lỗi %s" % (ten, type(e).__name__)
        if gc:
            ghi_chu.append(gc)
        _nguon_xong(ma, bool(kq))
        ra += kq
    du, ra2 = set(), []
    for k in ra:
        u = (k.get("url") or "").split("#")[0]
        if not u or u in du:
            continue
        du.add(u)
        k["lien_quan"] = diem_lien_quan(truy_van, k)
        ra2.append(k)
    ra2.sort(key=lambda x: -x["lien_quan"])
    return ra2[:max(10, int(so))], "; ".join(dict.fromkeys(ghi_chu))


# tên cũ: giữ lại để mã/test cũ vẫn chạy
def tim_nguon(truy_van, so=8, timeout=15):
    """(Giữ tên cũ) Tìm nguồn cho một câu truy vấn, bỏ trùng theo tên miền."""
    ra, gc = tim_nhieu_nguon(truy_van, so=so, timeout=timeout)
    du, ra2 = set(), []
    for k in ra:
        ten_mien = k.get("ten_mien") or re.sub(r"^www\.", "",
                                               re.sub(r"^https?://([^/]+).*$", r"\1", k["url"]))
        if any(x in k["url"] for x in BO_QUA_TEN_MIEN):
            continue
        if ten_mien in du:
            continue
        du.add(ten_mien)
        k["ten_mien"] = ten_mien
        ra2.append(k)
    return ra2[:so], gc


# ------------------------------------------------------------------ tải trang + bộ nhớ đệm
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
            try:
                e.getparent().remove(e)
            except Exception:
                pass
    chu = " ".join(cay.itertext())
    return chuan_hoa(chu)


_LIEN_KET = {}          # url → các liên kết nội bộ trong trang đó (để mở rộng phạm vi tải)


def _lien_ket_noi_bo(du_lieu, goc, toi_da=30):
    """Lấy các liên kết CÙNG TÊN MIỀN trong một trang HTML (để lần theo, mở rộng phạm vi)."""
    from urllib.parse import urljoin, urlparse
    try:
        from lxml import html as LH
        cay = LH.fromstring(du_lieu if isinstance(du_lieu, bytes) else du_lieu.encode("utf-8"))
    except Exception:
        return []
    host = urlparse(goc).netloc.lower()
    ra, du = [], set()
    for a in cay.xpath("//a[@href]"):
        u = urljoin(goc, (a.get("href") or "").strip())
        if not u.lower().startswith("http") or urlparse(u).netloc.lower() != host:
            continue
        u = u.split("#")[0]
        if u == goc.split("#")[0] or u in du:
            continue
        if any(u.lower().endswith(x) for x in (".jpg", ".png", ".gif", ".pdf", ".zip", ".mp4", ".doc",
                                              ".docx", ".xls", ".xlsx", ".ppt", ".pptx")):
            continue
        du.add(u)
        ra.append(u)
        if len(ra) >= toi_da:
            break
    return ra


def tai_trang(url, timeout=12, toi_da=TOI_DA_BYTE_TRANG, tra_ve_url=False):
    """Tải một trang → (chữ, lỗi) hoặc (chữ, lỗi, địa_chỉ_cuối). Bỏ tệp nhị phân, giới hạn dung lượng."""
    requests = _requests()
    try:
        r = requests.get(url, headers=UA, timeout=timeout, stream=True, allow_redirects=True)
        if r.status_code != 200:
            return ("", "mã %s" % r.status_code, r.url) if tra_ve_url else ("", "mã %s" % r.status_code)
        ct = (r.headers.get("Content-Type") or "").lower()
        if ct and not any(x in ct for x in ("text/html", "text/plain", "application/xhtml")):
            loi = "không phải trang chữ (%s)" % ct.split(";")[0]
            return ("", loi, r.url) if tra_ve_url else ("", loi)
        du, da = b"", 0
        for phan in r.iter_content(32 * 1024):
            du += phan
            da += len(phan)
            if da >= toi_da:
                break
        if not du:
            return ("", "trang rỗng", r.url) if tra_ve_url else ("", "trang rỗng")
        chu = lam_sach_html(du)
        _LIEN_KET[url] = _lien_ket_noi_bo(du, r.url or url)
        return (chu, "", r.url) if tra_ve_url else (chu, "")
    except Exception as e:
        loi = "lỗi %s" % type(e).__name__
        return ("", loi, url) if tra_ve_url else ("", loi)


def _thu_muc_dem():
    p = Path(os.environ.get("DB_DIR", "data")) / "trunglap-cache"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p


def _dem_khoa(url):
    import hashlib
    return hashlib.sha1((url or "").encode("utf-8")).hexdigest()


def doc_dem(url, toi_da_ngay=45):
    """Đọc lại trang đã tải trước đây (bộ nhớ đệm trên máy chủ) — giúp lần sau đối chiếu được
    cả những trang đã từng tải mà không cần tải lại."""
    p = _thu_muc_dem() / (_dem_khoa(url) + ".txt")
    if not p.exists():
        return None
    try:
        if (time.time() - p.stat().st_mtime) > toi_da_ngay * 86400:
            return None
        chu = p.read_text(encoding="utf-8")
        return chu if len(tach_tu(chu)) >= 40 else None
    except Exception:
        return None


def ghi_dem(url, chu):
    try:
        p = _thu_muc_dem() / (_dem_khoa(url) + ".txt")
        p.write_text(chu[:400_000], encoding="utf-8")
        _don_dem()
    except Exception:
        pass


def _don_dem(toi_da_tep=800):
    try:
        p = _thu_muc_dem()
        tep = sorted(p.glob("*.txt"), key=lambda x: x.stat().st_mtime)
        for f in tep[:-toi_da_tep] if len(tep) > toi_da_tep else []:
            f.unlink()
    except Exception:
        pass


def tai_nhieu_trang(ds, so_song_song=8, gio=None, timeout=12):
    """Tải nhiều trang CÙNG LÚC (nhiều luồng) — trả về (tải_được, không_tải_được).

    Mỗi trang tải về được lưu vào bộ nhớ đệm để lần kiểm tra sau dùng lại.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    gio = gio or (lambda *a, **k: None)
    ra, loi, hang_doi = [], [], []
    for k in ds:
        chu = doc_dem(k["url"])
        if chu:
            ra.append({"url": k["url"], "url_cuoi": k["url"], "chu": chu, "lien_ket": [],
                       "tieu_de": k.get("tieu_de", ""), "may_tim": k.get("may_tim", ""),
                       "ten_mien": k.get("ten_mien", ""), "tu_dem": True,
                       "so_tu": len(tach_tu(chu))})
        else:
            hang_doi.append(k)
    if not hang_doi:
        return ra, loi
    gio("tien_do", "dùng lại %d trang trong bộ nhớ đệm, tải %d trang mới" % (len(ra), len(hang_doi)))
    with ThreadPoolExecutor(max_workers=max(2, int(so_song_song))) as pool:
        viec = {pool.submit(tai_trang, k["url"], timeout, TOI_DA_BYTE_TRANG, True): k for k in hang_doi}
        for f in as_completed(viec):
            k = viec[f]
            try:
                chu, loi_t, url_cuoi = f.result()
            except Exception as e:
                chu, loi_t, url_cuoi = "", "lỗi %s" % type(e).__name__, k["url"]
            if loi_t or len(tach_tu(chu)) < 40:
                du_phong = (k.get("trich") or "").strip()
                if len(tach_tu(du_phong)) >= 12 and not k.get("chi_trich"):
                    # không mở được trang thì vẫn so được với ĐOẠN TRÍCH mà máy tìm kiếm trả về
                    ra.append({"url": k["url"], "url_cuoi": k["url"], "chu": du_phong, "lien_ket": [],
                               "tieu_de": (k.get("tieu_de") or "")[:160], "may_tim": k.get("may_tim", ""),
                               "ten_mien": k.get("ten_mien", ""), "tu_dem": False, "tu_trich": True,
                               "so_tu": len(tach_tu(du_phong))})
                    gio("tai", "%s → không mở được trang (%s), dùng đoạn trích có sẵn (%d từ)"
                        % (k["url"][:70], loi_t or "ít chữ", len(tach_tu(du_phong))))
                    continue
                loi.append({"url": k["url"], "ly_do": loi_t or "trang quá ít chữ"})
                continue
            ghi_dem(k["url"], chu)
            ra.append({"url": k["url"], "url_cuoi": url_cuoi or k["url"], "chu": chu,
                       "lien_ket": _LIEN_KET.pop(k["url"], []),
                       "tieu_de": k.get("tieu_de", ""), "may_tim": k.get("may_tim", ""),
                       "ten_mien": k.get("ten_mien", ""), "tu_dem": False,
                       "so_tu": len(tach_tu(chu))})
            gio("tai", "%s (%d từ)" % (k["url"][:90], len(tach_tu(chu))))
    ra.sort(key=lambda x: -x["so_tu"])
    return ra, loi


# ------------------------------------------------------------------ pipeline đối chiếu Internet
def doi_chieu_internet(doan, ghi_de=(), che_do="tieu_chuan", gio=None, so_truy_van=None,
                       so_trang=None, han_giay=None, so_ket_qua=None, so_song_song=None,
                       trang_moi_mien=None):
    """Tra Internet rồi so văn bản với TẤT CẢ các trang tải được.

    Trả về dict kết quả (gồm cả trường hợp không tải được nguồn nào).
    """
    t0 = time.time()
    gio = gio or (lambda *a, **k: None)
    ts = thong_so_che_do(che_do)
    if so_truy_van is not None:
        ts["so_truy_van"] = so_truy_van
    if so_trang is not None:
        ts["so_trang"] = so_trang
    if han_giay is not None:
        ts["han_giay"] = han_giay
    if so_ket_qua is not None:
        ts["so_ket_qua"] = so_ket_qua
    if so_song_song is not None:
        ts["so_song_song"] = so_song_song
    if trang_moi_mien is not None:
        ts["trang_moi_mien"] = trang_moi_mien
    kq = {"bat": True, "che_do": che_do if che_do in CHE_DO else "tieu_chuan",
          "ten_che_do": ts["ten"], "truy_van": [], "tim_thay": [], "tai_duoc": [],
          "khong_tai_duoc": [], "lay_duoc_nguon": False, "ghi_chu": "", "giay": 0,
          "so_cau_hoi": 0, "so_ket_qua": 0, "so_trang_tai": 0, "so_trang_dem": 0,
          "so_may_tim": [], "nguon_ngan": [], "tk": {}, "bang": [],
          "nguon_kq": {}, "tin_lien_quan": [], "so_trang_theo_lien_ket": 0}
    het_gio = lambda: (time.time() - t0) > ts["han_giay"]

    cau_hoi = sinh_truy_van(doan, toi_da=ts["so_truy_van"])
    if not cau_hoi:
        kq["ghi_chu"] = ("Không có câu nào đủ dài để tra Internet (cần câu từ 7 từ trở lên, "
                         "không nằm trong phần trích dẫn).")
        return kq
    kq["so_cau_hoi"] = len(cau_hoi)
    gio("buoc", "sinh %d câu hỏi phủ đều cả bài → tra %d nguồn tìm kiếm (%s)"
        % (len(cau_hoi), len(NGUON_TIM), ", ".join(NGUON_TIM.values())))

    tat_ca, da_co, ghi_chu = [], set(), []
    for i, c in enumerate(cau_hoi):
        if het_gio():
            ghi_chu.append("hết thời gian tra cứu ở câu %d/%d" % (i + 1, len(cau_hoi)))
            break
        q = '"%s"' % c
        gio("truy_van", "%d/%d — %s" % (i + 1, len(cau_hoi), q))
        kq["truy_van"].append(q)
        thay, gc = tim_nhieu_nguon(q, so=ts["so_ket_qua"])
        if gc:
            ghi_chu.append(gc)
        if not thay:                        # cụm nguyên văn không ra gì → tra rộng theo từ khoá
            q2 = truy_van_tu_cau(c)
            if q2:
                kq["truy_van"].append(q2)
                thay, _ = tim_nhieu_nguon(q2, so=ts["so_ket_qua"])
        moi = 0
        for k in thay:
            u = k["url"].split("#")[0]
            if u in da_co:
                continue
            da_co.add(u)
            tat_ca.append(k)
            kq["nguon_kq"][k.get("may_tim") or "khác"] = kq["nguon_kq"].get(k.get("may_tim") or "khác", 0) + 1
            moi += 1
        gio("ket_qua", "câu %d: thêm %d kết quả (tổng %d)" % (i + 1, moi, len(tat_ca)))

    kq["tim_thay"] = tat_ca[:300]
    kq["so_ket_qua"] = len(tat_ca)
    # chọn trang để tải: ưu tiên liên quan + đa dạng tên miền, chừa chỗ cho nguồn trích sẵn
    dem_mien, chon, tam_tin = {}, [], []
    for k in tat_ca:
        if k.get("tin"):
            tam_tin.append(k)
        if het_gio():
            break
        if k.get("chi_trich"):              # Google Books: chỉ có đoạn trích, không tải được
            if k.get("trich") and len(tach_tu(k["trich"])) >= 8:
                kq["nguon_ngan"].append(k)
            continue
        if len(chon) >= ts["so_trang"]:
            break
        tm = k.get("ten_mien") or re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", k["url"]))
        k["ten_mien"] = tm
        if any(x in k["url"] for x in BO_QUA_TEN_MIEN):
            continue
        if dem_mien.get(tm, 0) >= ts["trang_moi_mien"]:
            continue
        dem_mien[tm] = dem_mien.get(tm, 0) + 1
        chon.append(k)
    gio("buoc", "chọn %d trang để tải về (trong %d kết quả, tối đa %d trang)"
        % (len(chon), len(tat_ca), ts["so_trang"]))

    tai_duoc, khong_tai = [], []
    # Wikipedia: tải TOÀN VĂN các bài tìm được (nhanh, mỗi request 20 bài) — đối chiếu được
    # với hàng chục bài bách khoa chứ không phải chỉ vài trang HTML
    _wiki_ds = [k for k in tat_ca if k.get("wiki")][:int(ts.get("so_wiki", 0) or 0)]
    if _wiki_ds and not het_gio():
        gio("buoc", "tải toàn văn %d bài Wikipedia tìm được" % len(_wiki_ds))
        try:
            tai_duoc += tai_wiki_nhieu(_wiki_ds, gio=gio)
        except Exception as e:
            ghi_chu.append("Wikipedia: không lấy được toàn văn bài (%s)" % type(e).__name__)
    con = max(0, ts["so_trang"] - len(tai_duoc))
    for i in range(0, len(chon), max(2, ts["so_song_song"])):
        if het_gio() or con <= 0:
            ghi_chu.append("hết thời gian tải trang — đã tải %d trang" % len(tai_duoc))
            break
        lo = chon[i:i + max(2, ts["so_song_song"])][:con]
        d, l = tai_nhieu_trang(lo, so_song_song=ts["so_song_song"], gio=gio)
        tai_duoc += d
        khong_tai += l
        con = ts["so_trang"] - len(tai_duoc)
        kq["so_may_tim"] = sorted({x["may_tim"] for x in tai_duoc if x.get("may_tim")})
        gio("tien_do", "đã tải %d/%d trang · %d lỗi · %.0f giây"
            % (len(tai_duoc), ts["so_trang"], len(khong_tai), time.time() - t0))

    # BƯỚC 1: so bài với những gì đã tải được (toàn văn Wikipedia + trang tải về + đoạn trích)
    def _dung_kho(ds):
        k = []
        for x in ds:
            k.append(dung_kho_cau(x["tieu_de"] or x["ten_mien"] or x["url"], x["chu"],
                                  loai="Internet", url=x["url"]))
        for z in kq["nguon_ngan"]:          # đoạn trích sách/báo/tóm tắt: so trong phạm vi đoạn trích
            k.append(dung_kho_cau((z.get("tieu_de") or "")[:120] or z.get("may_tim", ""), z.get("trich") or "",
                                  loai="Internet (%s)" % z.get("may_tim", ""), url=z.get("url", "")))
        return k

    kq["tin_lien_quan"] = [{"tieu_de": k.get("tieu_de", ""), "ten_bao": k.get("ten_bao", ""),
                            "url": k.get("url", ""), "ngay": k.get("ngay", "")}
                           for k in tam_tin if k.get("tin")][:20]
    kq["lay_duoc_nguon"] = bool(tai_duoc or kq["nguon_ngan"])
    if kq["lay_duoc_nguon"]:
        gio("so", "bước 1: so bài với %d nguồn (%d trang + %d đoạn trích)…"
            % (len(tai_duoc), len(tai_duoc), len(kq["nguon_ngan"])))
        ban1, tk1 = so_khop_voi_nguon(doan, _dung_kho(tai_duoc))
        kq["bang"], kq["tk"] = ban1, tk1

        # BƯỚC 2 (mở rộng phạm vi): lần theo LIÊN KẾT trong những trang ĐÃ CÓ CÂU KHỚP —
        # những trang cùng website với nguồn chép thường chứa bài gốc hoặc các bài cùng chuyên mục
        theo = int(ts.get("theo_trang", 0) or 0)
        if theo and ban1 and not het_gio() and len(tai_duoc) < ts["so_trang"]:
            mien_khop = set()
            for k in ban1:
                m = re.sub(r"^https?://(www\.)?([^/]+).*$", r"\2", k.get("cau_nguon_url") or "")
                if m:
                    mien_khop.add(m)
            da_co_url = set()
            for x in tai_duoc:
                da_co_url.add(x["url"])
                da_co_url.add(x.get("url_cuoi") or "")
            for k in chon:
                da_co_url.add(k["url"])
            them = []
            for x in tai_duoc:
                tm = x.get("ten_mien") or ""
                if tm not in mien_khop or "wikipedia.org" in tm:
                    continue
                n = 0
                for u in _loc_lien_ket(x, theo):
                    if n >= theo or len(them) >= ts["so_trang"] - len(tai_duoc) or het_gio():
                        break
                    if u in da_co_url:
                        continue
                    da_co_url.add(u)
                    them.append({"url": u, "tieu_de": (x.get("tieu_de") or "")[:60] + " — trang cùng website",
                                 "may_tim": "Mở rộng theo liên kết", "ten_mien": tm})
                    n += 1
            if them:
                gio("buoc", "bước 2: tải thêm %d trang CÙNG WEBSITE với nguồn đã khớp" % len(them))
                for i in range(0, len(them), max(2, ts["so_song_song"])):
                    if het_gio():
                        break
                    d, l = tai_nhieu_trang(them[i:i + max(2, ts["so_song_song"])],
                                           so_song_song=ts["so_song_song"], gio=gio)
                    tai_duoc += d
                    khong_tai += l
                kq["so_trang_theo_lien_ket"] = len([y for y in tai_duoc
                                                    if y.get("may_tim") == "Mở rộng theo liên kết"])
                if kq["so_trang_theo_lien_ket"]:
                    gio("so", "bước 2: so lại với %d trang (thêm %d trang cùng website)…"
                        % (len(tai_duoc), kq["so_trang_theo_lien_ket"]))
                    kq["bang"], kq["tk"] = so_khop_voi_nguon(doan, _dung_kho(tai_duoc))
    else:
        kq["tk"] = {"so_cau_xet": 0, "so_cau_khop": 0, "so_tu": 0, "ty_le_trung": 0.0,
                    "nguyen_van": 0, "doi_tu": 0}

    kq["tai_duoc"] = [{"url": x["url"], "url_cuoi": x.get("url_cuoi", ""), "tieu_de": x["tieu_de"],
                       "so_tu": x["so_tu"], "may_tim": x["may_tim"], "ten_mien": x["ten_mien"],
                       "tu_dem": x["tu_dem"], "toan_van_wiki": bool(x.get("tu_wiki")),
                       "tu_trich": bool(x.get("tu_trich"))} for x in tai_duoc]
    kq["khong_tai_duoc"] = khong_tai
    kq["so_trang_tai"] = len(tai_duoc)
    kq["so_trang_dem"] = len([x for x in tai_duoc if x["tu_dem"]])
    kq["so_may_tim"] = sorted({x["may_tim"] for x in tai_duoc if x.get("may_tim")})
    kq["giay"] = int(time.time() - t0)
    if not kq["lay_duoc_nguon"]:
        ghi_chu.append("Đã tra %d câu hỏi qua các nguồn tìm kiếm nhưng chưa tải được trang nào để so "
                       "(nguồn chặn truy cập tự động hoặc không có kết quả). Kết quả bên dưới chỉ là "
                       "đối chiếu trong kho của thầy/cô." % len(kq["truy_van"]))
    if kq["nguon_kq"]:
        gio("so", "kết quả theo từng nguồn: " + ", ".join(
            "%s %d" % (t, n) for t, n in sorted(kq["nguon_kq"].items(), key=lambda x: -x[1])))
    kq["ghi_chu"] = "; ".join(dict.fromkeys([x for x in ghi_chu if x]))[:600]
    gio("xong", "tra %d câu hỏi · %d kết quả · tải %d trang · %d câu nghi trùng · %d giây"
        % (len(kq["truy_van"]), kq["so_ket_qua"], kq["so_trang_tai"], kq["tk"]["so_cau_khop"],
           kq["giay"]))
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
    kq["tk"]["so_cau_hoi"] = it.get("so_cau_hoi", 0)
    kq["tk"]["so_ket_qua"] = it.get("so_ket_qua", 0)
    kq["tk"]["so_trang_tai"] = it.get("so_trang_tai", 0)
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
        _it = kq.get("internet") or {}
        if _it.get("so_cau_hoi"):
            d["dong"].append(("Phần đối chiếu Internet",
                              "%s: tra %d câu hỏi, tìm được %d kết quả, tải về %d trang để so khớp "
                              "(nguồn: %s)" % (_it.get("ten_che_do", ""), _it.get("so_cau_hoi", 0),
                                               _it.get("so_ket_qua", 0), _it.get("so_trang_tai", 0),
                                               ", ".join(_it.get("so_may_tim") or []) or "—")))
            for x in (_it.get("tai_duoc") or [])[:25]:
                d["canh_bao"].append("Đã đối chiếu: %s — %s" % ((x.get("tieu_de") or "")[:80],
                                                                 (x.get("url") or "")[:110]))
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

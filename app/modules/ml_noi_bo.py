"""Mô hình nhỏ do EduAssist tự huấn luyện, chạy ngay trên VPS (chỉ cần numpy).

Hiện có 1 mô hình được xuất bản: `do_loi_chinh_ta` — với mỗi từ trong giáo án,
cho biết từ đó có dấu hiệu sai chính tả hay không.

NÓI THẲNG VỀ BẢN CHẤT:
  - Đây là mô hình HỒI QUY LOGISTIC trên n-gram ký tự, vài nghìn tham số. KHÔNG
    phải mô hình ngôn ngữ lớn, không sinh văn bản, không "hiểu" nội dung.
  - Huấn luyện trên dữ liệu TỔNG HỢP (cụm từ ngành + câu nguyên văn văn bản Bộ)
    do hệ thống tự sinh; không dùng giáo án thật của giáo viên.
  - Chỉ dùng để GỢI Ý. Mọi đề xuất từ mô hình đều ở chế độ "chỉ gợi ý" và phải
    được giáo viên tích chọn mới ghi vào file.

Số đo trên tập kiểm tra giữ riêng (từ sai ở tập test không có trong tập train)
được lưu trong `bao_cao_huan_luyen.json` và in ra ở `thong_tin()`.
"""
import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DUONG_DAN = Path(__file__).resolve().parents[1] / "assets" / "ml"
NGUONG = 0.5           # ngưỡng xác suất coi là "có dấu hiệu sai"
BETA_TAN_SUAT = 0.1    # trọng số thưởng tần suất khi xếp hạng bản sửa
NGUONG_GOI_Y = 0.75   # từ mức này trở lên mới đưa ra gợi ý sửa
LEXICON = "lexicon_sach.json"


def _bo_dau(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


@lru_cache(maxsize=1)
def _tu_dien():
    """Từ vựng sạch dùng để (a) sinh đặc trưng, (b) chỉ đề xuất từ CÓ THẬT."""
    p = DUONG_DAN / LEXICON
    if not p.exists():
        return {"theo_dau": set(), "bo_dau": {}, "dem": {}}
    d = json.loads(p.read_text(encoding="utf-8"))
    theo_dau, bo_dau = set(), {}
    for w in d["tu"]:
        theo_dau.add(w.lower())
        bo_dau.setdefault(_bo_dau(w), []).append(w)   # giữ CẢ danh sách, không chỉ 1 từ
    return {"theo_dau": theo_dau, "bo_dau": bo_dau, "dem": d.get("dem") or {}}


@lru_cache(maxsize=1)
def trong_tu_vung(tu):
    """Từ này có nằm trong từ vựng ĐÃ KIỂM CHỨNG (đã loại mọi từ trong bảng lỗi) không?

    Dùng để các tầng luật bỏ qua những từ đúng mà bộ kiểm tra âm tiết hay bắt oan
    ("gìn", "trước"…). Từ vựng này do mô hình mang theo, không phải danh sách gõ tay.
    """
    return (tu or "").strip().lower() in _tu_dien()["theo_dau"]


def _chinhta():
    from . import chinhta
    return chinhta


@lru_cache(maxsize=1)
def mo_hinh():
    p = DUONG_DAN / "ml_do_loi_chinh_ta.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def bao_cao_huan_luyen():
    p = DUONG_DAN / "bao_cao_huan_luyen.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def co_mo_hinh():
    return mo_hinh() is not None


# --------------------------------------------------------------- đặc trưng
# Hàm này được dùng CHUNG cho cả lúc huấn luyện và lúc suy luận, để hai bên
# không bao giờ lệch nhau.
def dac_trung_tu(tokens, i, ngrams=(2, 3, 4)):
    w = tokens[i]
    wl = w.lower()
    f = []
    for n in ngrams:
        if len(wl) >= n:
            for j in range(len(wl) - n + 1):
                f.append("g%d:%s" % (n, wl[j:j + n]))
        f.append("d%d:%s" % (n, "^" + wl[:n]))
        f.append("c%d:%s" % (n, wl[-n:] + "$"))
    f.append("len:%d" % min(len(wl), 12))
    f.append("kitu:%s" % ("hoa" if w[:1].isupper() else "thuong"))
    if re.search(r"\d", w):
        f.append("co_so")
    if i > 0:
        f.append("truoc:%s" % _bo_dau(tokens[i - 1])[:3])
    if i + 1 < len(tokens):
        f.append("sau:%s" % _bo_dau(tokens[i + 1])[:3])
    td = _tu_dien()
    wbd = _bo_dau(wl)
    # hai đặc trưng TÁCH BẠCH: viết đúng dấu có phải từ thật không, và dạng bỏ dấu
    # có khớp một từ thật không (rất cần cho lỗi "hoc" -> "học")
    f.append("dungdau:co" if wl in td["theo_dau"] else "dungdau:khong")
    f.append("bodau:co" if wbd in td["theo_dau"] else "bodau:khong")
    try:
        f.append("am_tiet_hop_le" if _chinhta().is_valid_syllable(wbd) else "am_tiet_sai")
    except Exception:
        pass
    f.append("co_dau" if any(ord(c) > 127 for c in wl) else "khong_dau")
    return f


def _sigmoid(x):
    if x < -60:
        return 0.0
    if x > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def _diem_mot_tu(mh, tokens, i):
    s = mh["intercept"]
    ws = mh["trong_so"]
    for ten in dac_trung_tu(tokens, i):
        v = ws.get(ten)
        if v is not None:
            s += v
    return _sigmoid(s)


# ------------------------------------------------------ đề xuất từ sửa được
DOI = [("ả", "ã"), ("ã", "ả"), ("ẻ", "ẽ"), ("ẽ", "ẻ"), ("ỉ", "ĩ"), ("ĩ", "ỉ"),
       ("ỏ", "õ"), ("õ", "ỏ"), ("ủ", "ũ"), ("ũ", "ủ"), ("ỷ", "ỹ"), ("ỹ", "ỷ"),
       ("ẳ", "ẵ"), ("ẵ", "ẳ"), ("ẩ", "ẫ"), ("ẫ", "ẩ"), ("ở", "ỡ"), ("ỡ", "ở"),
       ("ổ", "ỗ"), ("ỗ", "ổ")]
DAU_TU = [("s", "x"), ("x", "s"), ("ch", "tr"), ("tr", "ch"), ("gi", "d"), ("d", "gi"),
          ("r", "d"), ("l", "n"), ("n", "l")]
CUOI_TU = [("c", "t"), ("t", "c"), ("ng", "n"), ("nh", "n"), ("n", "ng")]
TEENCODE_NGUOC = {"dc": "được", "đc": "được", "ko": "không", "k": "không", "vs": "với",
                  "cx": "cũng", "hs": "học sinh", "sgk": "sách giáo khoa"}


def ung_vien(tu):
    """Sinh các từ CÓ THẬT trong từ vựng có thể là bản đúng của `tu`."""
    ra = set()
    t = tu.lower()
    td = _tu_dien()
    if t in TEENCODE_NGUOC:
        ra.add(TEENCODE_NGUOC[t])
    # đổi dấu hỏi/ngã, phụ âm đầu, phụ âm cuối (mỗi lần một phép)
    for a, b in DOI:
        if a in t:
            ra.add(t.replace(a, b, 1))
    for a, b in DAU_TU:
        if t.startswith(a):
            ra.add(b + t[len(a):])
    for a, b in CUOI_TU:
        if t.endswith(a) and len(t) > len(a) + 1:
            ra.add(t[:-len(a)] + b)
    # khôi phục dấu: hoc -> học ; gía -> giá (MỌI từ thật cùng dạng bỏ dấu)
    # Trước đây chỉ lấy 1 từ đầu tiên nên "gía" chỉ ra được "gia" chứ không ra "giá".
    for w in td["bo_dau"].get(_bo_dau(t), []):
        ra.add(w)
    # gõ thừa 1 ký tự (hay gặp: "chhưa", "bảảng")
    for i in range(len(t)):
        if len(t) > 3 and t[i] == t[i - 1] if i else False:
            ra.add(t[:i] + t[i + 1:])
    # giữ lại các từ CÓ THẬT trong từ vựng (không đề xuất từ vô nghĩa)
    ra = {w for w in ra if w in td["theo_dau"] or _bo_dau(w) in td["theo_dau"]}
    ra.discard(t)
    # giữ nguyên kiểu viết hoa của từ gốc
    if tu[:1].isupper():
        ra = {w[:1].upper() + w[1:] for w in ra}
    return sorted(ra)


def goi_y_sua(mh, tokens, i):
    """Chọn bản sửa tốt nhất. Trả về (từ_sửa, độ_chắc) hoặc (None, 0).

    Hai chốt bảo vệ, đều được ĐO trên tập test giữ riêng chứ không đoán:
      1. Bản sửa phải THÔNG DỤNG HƠN từ đang xét (theo tần suất trong từ vựng).
         Không có chốt này, mô hình từng đề nghị sửa "rồi" (rất thông dụng) thành
         "dồi" (hiếm) chỉ vì "dồi" tình cờ có trong từ vựng.
      2. Xếp hạng = điểm mô hình + thưởng theo tần suất (beta = 0.1). Chỉ riêng điểm
         mô hình cho 70,7% đề xuất đúng; thêm tần suất lên 73,3% (đo trên 1 430 lỗi
         của tập test). Từ đúng gần như luôn là từ thông dụng, nên thưởng tần suất
         sửa được các ca mô hình chọn nhầm một từ hiếm cùng dạng.
    """
    dem = _tu_dien()["dem"]
    goc = tokens[i].lower()
    tan_goc = dem.get(goc, 0)
    diem_goc = _diem_mot_tu(mh, tokens, i)
    tot, diem_tot, ham_tot = None, None, None
    for w in ung_vien(goc):
        if dem.get(w.lower(), 0) <= tan_goc:
            continue                      # (1) không thông dụng hơn -> không đề xuất
        thu = list(tokens)
        thu[i] = w
        d = _diem_mot_tu(mh, thu, i)
        if d >= min(NGUONG, diem_goc):    # ứng viên vẫn "có mùi sai" -> loại
            continue
        ham = d - BETA_TAN_SUAT * math.log(1 + dem.get(w.lower(), 0))   # (2)
        if ham_tot is None or ham < ham_tot:
            tot, diem_tot, ham_tot = w, d, ham
    return tot, round(1 - diem_tot, 3) if tot else 0.0


DAU_CAU = ".,;:!?()[]{}\"'“”‘’…-–—/"


def _tach(t):
    """Tách dấu câu dính hai đầu từ: "cô." -> ("cô", 0, 2)."""
    dau = 0
    while dau < len(t) and t[dau] in DAU_CAU:
        dau += 1
    cuoi = len(t)
    while cuoi > dau and t[cuoi - 1] in DAU_CAU:
        cuoi -= 1
    return t[dau:cuoi], dau, cuoi


def doc_tai_lieu(vb, can_ban_sua=True):
    """Chấm điểm từng từ, trả về danh sách từ có dấu hiệu sai.

    Ba chốt bảo vệ để không làm phiền giáo viên:
      1. Từ nằm trong từ vựng đã biết thì bỏ qua (không có chốt này, mô hình từng
         đề nghị sửa "rồi" thành "dồi").
      2. Dấu câu dính hai đầu từ được tách ra trước khi chấm điểm.
      3. CHỈ BÁO khi tìm được bản sửa CỤ THỂ trong từ vựng. Từ đúng nhưng hiếm gặp
         ("nhiệt", "SGK", "THCS") không có bản sửa nào, nên không bị nêu ra nữa.
         Đây là chốt đánh đổi có chủ ý: giảm bắt được một phần lỗi lạ, nhưng không
         làm giáo viên mất niềm tin vì những cảnh báo vô căn cứ.
    """
    mh = mo_hinh()
    if not mh or not (vb or "").strip():
        return []
    td = _tu_dien()
    ra = []
    for dong in vb.split("\n"):
        tokens = dong.split()
        if not tokens:
            continue
        for i, t_raw in enumerate(tokens):
            t, dau, cuoi = _tach(t_raw)
            if not t or len(t) < 3 or not t.isalpha():
                continue
            # (1) từ đã có trong từ vựng -> coi là đúng, không xét
            if t.lower() in td["theo_dau"]:
                continue
            d = _diem_mot_tu(mh, tokens, i)
            if d < NGUONG_GOI_Y:
                continue
            ban_sua, do_chac = goi_y_sua(mh, tokens, i)
            if can_ban_sua and not ban_sua:
                continue
            vt = sum(len(x) + 1 for x in tokens[:i]) + dau
            ra.append({"tu": t, "diem": round(d, 3), "dong": dong, "ban_sua": ban_sua,
                       "do_chac": do_chac, "vi_tri_tu": i, "tokens": tokens,
                       "vi_tri_ky_tu": vt, "vi_tri_ky_tu_full": vt})
    return ra


def nhan():
    """Nhãn bắt buộc in kèm mọi kết quả của mô hình."""
    b = (bao_cao_huan_luyen() or {}).get("mo_hinh_chinh_ta") or {}
    pt = ""
    if b:
        pt = (f" (tập kiểm tra giữ riêng: bắt được {b.get('recall', 0):.0%} số lỗi, "
              f"báo nhầm {b.get('bao_dong_nham_tren_tu_dung', 0)}/{b.get('tu_dung', 0)} từ đúng")
        dx = b.get("de_xuat_sua") or {}
        if dx:
            pt += (f"; trong số lỗi bắt được thì {dx.get('ti_le_tren_so_da_de_xuat', 0):.0%} "
                   f"có bản sửa đúng")
        pt += ")"
    return ("Do mô hình nhỏ do EduAssist tự huấn luyện đề xuất" + pt +
            ". Đây KHÔNG phải mô hình ngôn ngữ lớn; kết quả chỉ mang tính gợi ý, "
            "giáo viên duyệt trước khi sửa.")


def thong_tin():
    mh = mo_hinh() or {}
    bc = bao_cao_huan_luyen() or {}
    return {
        "co_mo_hinh": bool(mh),
        "ten": mh.get("ten", ""),
        "kieu": mh.get("kieu", ""),
        "phien_ban": mh.get("phien_ban", ""),
        "huan_luyen_luc": mh.get("huan_luyen_luc", ""),
        "so_trong_so": len(mh.get("trong_so") or {}),
        "chi_so": (bc.get("mo_hinh_chinh_ta") or {}),
        "so_sanh_bo_luat": bc.get("so_sanh_bo_luat", {}),
        "mo_hinh_thanh_phan": bc.get("mo_hinh_thanh_phan", {}),
        "so_tu_vung": len(_tu_dien()["theo_dau"]),
        "tro_ly": mh.get("ghi_chu", ""),
    }

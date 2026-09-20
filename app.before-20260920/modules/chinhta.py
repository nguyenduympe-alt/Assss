"""Kiểm tra lỗi chính tả tiếng Việt — chạy hoàn toàn offline.

Chiến lược ưu tiên ĐỘ CHÍNH XÁC (ít báo nhầm), gồm 4 tầng:
  1. Âm tiết sai cấu trúc  -> chắc chắn sai (vd: "khôngg", "nguoiiw")
  2. Từ điển lỗi thường gặp -> teencode, viết tắt, sai l/n, ch/tr, s/x, d/gi/r
  3. Mất dấu hoàn toàn      -> "khong" -> "không" (chỉ khi ánh xạ duy nhất)
  4. Sai dấu hỏi/ngã        -> cặp từ dễ nhầm trong văn bản giáo dục
"""
import re, unicodedata
from collections import OrderedDict

# ---------------------------------------------------------------- cấu trúc âm tiết
ONSETS = ["", "b", "c", "ch", "d", "đ", "g", "gh", "gi", "h", "k", "kh", "l", "m", "n",
          "ng", "ngh", "nh", "p", "ph", "qu", "r", "s", "t", "th", "tr", "v", "x"]

NUCLEI = ["a", "ă", "â", "e", "ê", "i", "o", "ô", "ơ", "u", "ư", "y",
          "ia", "iê", "ya", "yê", "ua", "uô", "ưa", "ươ",
          "oa", "oă", "oe", "oo", "ôô", "uâ", "uă", "uê", "uy", "uơ",
          "ai", "ao", "au", "ay", "âu", "ây", "eo", "êu", "iu", "oi", "ôi", "ơi",
          "ui", "ưi", "ưu", "uôi", "ươi", "ươu", "iêu", "yêu", "oai", "oay", "uây",
          "uôm", "uya", "uyê", "oao", "oeo", "uyu", "iêc"]

CODAS = ["", "c", "ch", "m", "n", "ng", "nh", "p", "t"]

TONE_MARKS = {
    "a": "àáảãạ", "ă": "ằắẳẵặ", "â": "ầấẩẫậ", "e": "èéẻẽẹ", "ê": "ềếểễệ",
    "i": "ìíỉĩị", "o": "òóỏõọ", "ô": "ồốổỗộ", "ơ": "ờớởỡợ", "u": "ùúủũụ",
    "ư": "ừứửữự", "y": "ỳýỷỹỵ",
}
ALL_VN = set("aăâbcdđeêghiklmnoôơpqrstuưvxy")
for v in TONE_MARKS.values():
    ALL_VN |= set(v)


def strip_tone(s):
    """Bỏ dấu thanh, giữ nguyên ă â ê ô ơ ư đ."""
    out = []
    for ch in s:
        low = ch.lower()
        for base, marks in TONE_MARKS.items():
            if low in marks:
                out.append(base if ch.islower() else base.upper())
                break
        else:
            out.append(ch)
    return "".join(out)


def strip_all(s):
    """Bỏ hết dấu, về ASCII: 'không' -> 'khong'."""
    s = strip_tone(s).replace("đ", "d").replace("Đ", "D")
    return unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()


def _split(sy):
    """Tách âm tiết thành (phụ âm đầu, vần, phụ âm cuối). None nếu không tách được."""
    base = strip_tone(sy)
    onset = ""
    for o in sorted(ONSETS, key=len, reverse=True):
        if o and base.startswith(o):
            onset = o
            break
    rest = base[len(onset):]
    if not rest:
        return None
    for c in sorted(CODAS, key=len, reverse=True):
        if c and rest.endswith(c):
            nuc, coda = rest[:-len(c)], c
            if nuc in NUCLEI:
                return onset, nuc, coda
    return (onset, rest, "") if rest in NUCLEI else None


def is_valid_syllable(sy):
    """Âm tiết có đúng cấu trúc tiếng Việt không?"""
    low = sy.lower()
    if not low or any(c not in ALL_VN for c in low):
        return False
    # không có quá 1 dấu thanh
    n_tone = sum(1 for c in low if any(c in m for m in TONE_MARKS.values()))
    if n_tone > 1:
        return False
    return _split(low) is not None


# ---------------------------------------------------------------- từ điển lỗi
# Lỗi gõ tắt / teencode / sai phụ âm thường gặp trong văn bản nhà trường
COMMON_ERRORS = OrderedDict([
    # teencode & viết tắt
    ("ko", "không"), ("k", "không"), ("kg", "không"), ("khg", "không"), ("hok", "không"),
    ("dc", "được"), ("đc", "được"), ("duoc", "được"), ("bjo", "bây giờ"),
    ("j", "gì"), ("ji", "gì"), ("z", "gì"), ("wa", "quá"), ("qá", "quá"),
    ("vs", "với"), ("vz", "với"), ("nx", "nhận xét"), ("hs", "học sinh"),
    ("ntn", "như thế nào"), ("bt", "bình thường"), ("nhìu", "nhiều"), ("nhiu", "nhiều"),
    ("bik", "biết"), ("bit", "biết"), ("rùi", "rồi"), ("roi", "rồi"), ("r", "rồi"),
    ("mún", "muốn"), ("thik", "thích"), ("iu", "yêu"), ("bn", "bao nhiêu"),
    ("cx", "cũng"), ("cg", "cũng"), ("vc", "việc"), ("trg", "trường"), ("hjhj", "hihi"),
    ("tks", "cảm ơn"), ("ok", "được"), ("okie", "được"),
    # sai phụ âm đầu phổ biến
    ("chuyện cần", "chuyên cần"), ("trân thành", "chân thành"), ("chân trọng", "trân trọng"),
    ("xử lý xố", "xử lý số"), ("sử lý", "xử lý"), ("sử dụng sai", "sử dụng sai"),
    ("dành được", "giành được"), ("giành thời gian", "dành thời gian"),
    ("sáng lạn", "xán lạn"), ("cọ sát", "cọ xát"), ("chín mùi", "chín muồi"),
    ("xúc tích", "súc tích"), ("bàng quang", "bàng quan"), ("chuẩn đoán", "chẩn đoán"),
    ("tựu chung", "tựu trung"), ("nhậm chức", "nhận chức"), ("vô hình chung", "vô hình trung"),
    ("đường xá", "đường sá"), ("xán lạng", "xán lạn"), ("sơ xuất", "sơ suất"),
    ("trau chuốt", "trau chuốt"), ("chỉnh chu", "chu đáo"), ("suôn xẻ", "suôn sẻ"),
    ("thăm quan", "tham quan"), ("tham gia ý kiến", "tham gia ý kiến"),
    ("phong phanh", "phong thanh"), ("che dấu", "che giấu"), ("dấu diếm", "giấu giếm"),
    ("gian dối", "gian dối"), ("rốt ráo", "ráo riết"),
    # sai hỏi / ngã hay gặp
    ("sữa chữa", "sửa chữa"), ("sữa lỗi", "sửa lỗi"), ("cũng cố", "củng cố"),
    ("bổ xung", "bổ sung"), ("kiễm tra", "kiểm tra"), ("tỷ mỷ", "tỉ mỉ"),
    ("mạnh mẻ", "mạnh mẽ"), ("lẻ ra", "lẽ ra"), ("suy nghỉ", "suy nghĩ"),
    ("nghỉ ngơi", "nghỉ ngơi"), ("bảo quản", "bảo quản"), ("hưỡng dẫn", "hướng dẫn"),
    ("giử gìn", "giữ gìn"), ("sẻ chia", "sẻ chia"), ("chia sẽ", "chia sẻ"),
    ("cỗ vũ", "cổ vũ"), ("dổ dành", "dỗ dành"), ("nổ lực", "nỗ lực"),
    ("kỷ niệm", "kỷ niệm"), ("kỹ năng", "kỹ năng"), ("tỉ lệ", "tỉ lệ"),
    ("thỗ lộ", "thổ lộ"), ("bở ngỡ", "bỡ ngỡ"), ("ngỡ ngàng", "ngỡ ngàng"),
    ("lảng phí", "lãng phí"), ("mỉm cười", "mỉm cười"), ("nghiêm khắt", "nghiêm khắc"),
    ("hoàn thành tôt", "hoàn thành tốt"),
    # lỗi gõ lặp / thiếu
    ("nhưng mà là", "nhưng"), ("thì là", "thì"),
])

# Cặp hỏi/ngã dễ nhầm: dạng SAI -> dạng ĐÚNG (chỉ 1 âm tiết, xét theo ngữ cảnh từ ghép)
HOI_NGA = {
    "sữa": ("sửa", ["chữa", "lỗi", "bài", "sai", "đổi"]),      # sữa chữa -> sửa chữa
    "cũng": ("củng", ["cố"]),
    "nghỉ": ("nghĩ", ["suy", "ngợi"]),
    "nghĩ": ("nghỉ", ["ngơi", "hè", "phép", "học"]),
    "chia": (None, []),
    "sẽ": ("sẻ", ["chia"]),
    "giả": ("giã", ["từ"]),
}

# Từ thông dụng trong nhận xét học sinh (để gợi ý khi mất dấu)
COMMON_WORDS = """
không được học sinh giáo viên nhà trường lớp học bài tập kiểm tra đánh giá nhận xét
hoàn thành tốt chưa đạt yêu cầu cần cố gắng tiến bộ chăm chỉ ngoan ngoãn lễ phép
tích cực phát biểu xây dựng bài viết chữ đẹp cẩn thận sạch sẽ trình bày rõ ràng
tiếp thu nhanh vận dụng kiến thức kỹ năng thái độ năng lực phẩm chất rèn luyện
tham gia hoạt động tập thể đoàn kết giúp đỡ bạn bè thầy cô gia đình phụ huynh
môn toán tiếng việt khoa học lịch sử địa lý âm nhạc mỹ thuật thể dục công nghệ
tuần tháng học kỳ năm học phân phối chương trình thời khóa biểu báo giảng
đầy đủ nghiêm túc trật tự chú ý lắng nghe ghi chép thường xuyên đôi khi
kết quả điểm số xếp loại giỏi khá trung bình yếu kém xuất sắc
phát triển khả năng tư duy sáng tạo độc lập tự giác trách nhiệm
""".split()

# bản đồ: dạng không dấu -> từ có dấu (chỉ giữ khi duy nhất)
_NO_TONE_MAP = {}
for w in COMMON_WORDS:
    k = strip_all(w)
    _NO_TONE_MAP.setdefault(k, set()).add(w)
NO_TONE_MAP = {k: list(v)[0] for k, v in _NO_TONE_MAP.items() if len(v) == 1 and k != list(v)[0]}

WORD_SET = set(COMMON_WORDS)
TOKEN_RE = re.compile(r"[0-9]+|[^\W\d_]+", re.UNICODE)


# ---------------------------------------------------------------- bộ kiểm tra
class Issue:
    __slots__ = ("para", "start", "end", "word", "suggest", "kind", "note")

    def __init__(self, para, start, end, word, suggest, kind, note):
        self.para, self.start, self.end = para, start, end
        self.word, self.suggest, self.kind, self.note = word, suggest, kind, note

    def as_dict(self, idx):
        return {"id": idx, "para": self.para, "start": self.start, "end": self.end,
                "word": self.word, "suggest": self.suggest, "kind": self.kind, "note": self.note}


KIND_LABEL = {
    "teencode": ("Viết tắt / teencode", "#f59e0b"),
    "sai_cautruc": ("Sai cấu trúc âm tiết", "#f43f5e"),
    "mat_dau": ("Thiếu dấu tiếng Việt", "#06b6d4"),
    "tu_sai": ("Dùng từ sai", "#8b5cf6"),
    "lap_tu": ("Lặp từ", "#0d9488"),
    "hoa_dau": ("Viết hoa đầu câu", "#64748b"),
}


def _keep_case(src, rep):
    if src.isupper() and len(src) > 1:
        return rep.upper()
    if src[:1].isupper():
        return rep[:1].upper() + rep[1:]
    return rep


def check_paragraph(text, pidx, opts=None):
    """Trả về danh sách Issue trong 1 đoạn văn."""
    opts = opts or {}
    issues = []
    low_text = text.lower()

    # --- tầng 2a: cụm từ sai (nhiều âm tiết) ---
    for wrong, right in COMMON_ERRORS.items():
        if " " not in wrong:
            continue
        for m in re.finditer(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", low_text):
            if wrong == right:
                continue
            issues.append(Issue(pidx, m.start(), m.end(), text[m.start():m.end()],
                                _keep_case(text[m.start():m.end()], right), "tu_sai",
                                f"“{wrong}” nên viết là “{right}”"))

    taken = {(i.start, i.end) for i in issues}
    prev_tok = None
    for m in TOKEN_RE.finditer(text):
        w = m.group()
        if w.isdigit() or any((m.start() >= s and m.end() <= e) for s, e in taken):
            prev_tok = w.lower()
            continue
        lw = w.lower()

        # --- lặp từ liền nhau ---
        if opts.get("lap_tu", True) and prev_tok == lw and len(lw) > 1 and lw not in ("rất",):
            issues.append(Issue(pidx, m.start(), m.end(), w, "", "lap_tu",
                                f"Lặp lại từ “{w}”, nên xoá bớt"))
            prev_tok = lw
            continue
        prev_tok = lw

        # --- tầng 2b: từ đơn sai ---
        if lw in COMMON_ERRORS and COMMON_ERRORS[lw] != lw:
            rep = COMMON_ERRORS[lw]
            kind = "teencode" if len(lw) <= 4 else "tu_sai"
            issues.append(Issue(pidx, m.start(), m.end(), w, _keep_case(w, rep), kind,
                                f"“{w}” nên viết đầy đủ là “{rep}”"))
            continue

        if lw in WORD_SET:
            continue

        # --- tầng 3: mất dấu hoàn toàn ---
        if opts.get("mat_dau", True) and lw.isascii() and len(lw) >= 3:
            cand = NO_TONE_MAP.get(lw)
            if cand:
                issues.append(Issue(pidx, m.start(), m.end(), w, _keep_case(w, cand), "mat_dau",
                                    f"Thiếu dấu: “{w}” → “{cand}”"))
                continue

        # --- tầng 1: sai cấu trúc âm tiết ---
        if not lw.isascii() and not is_valid_syllable(lw):
            sug = _suggest(lw)
            issues.append(Issue(pidx, m.start(), m.end(), w,
                                _keep_case(w, sug) if sug else "", "sai_cautruc",
                                f"“{w}” không phải âm tiết tiếng Việt hợp lệ"))
    return issues


def _suggest(w):
    """Gợi ý sửa cho âm tiết sai: thử bỏ ký tự lặp, thử từ gần giống."""
    d = re.sub(r"(.)\1{1,}", r"\1", w)          # khôngg -> không
    if d != w and is_valid_syllable(d):
        return d
    base = strip_all(w)
    if base in NO_TONE_MAP:
        return NO_TONE_MAP[base]
    best, bd = None, 3
    for cand in WORD_SET:
        if abs(len(cand) - len(w)) > 2:
            continue
        dist = _lev(w, cand)
        if dist < bd:
            best, bd = cand, dist
    return best


def _lev(a, b):
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def check_text(paragraphs, opts=None):
    """paragraphs: list[str] -> (list[dict] issues, thống kê)"""
    out, idx = [], 0
    for pi, para in enumerate(paragraphs):
        if not para or not para.strip():
            continue
        for iss in sorted(check_paragraph(para, pi, opts), key=lambda x: x.start):
            out.append(iss.as_dict(idx))
            idx += 1
    stats = {}
    for o in out:
        stats[o["kind"]] = stats.get(o["kind"], 0) + 1
    n_words = sum(len(TOKEN_RE.findall(p or "")) for p in paragraphs)
    return out, {"tong": len(out), "theo_loai": stats, "so_tu": n_words,
                 "so_doan": sum(1 for p in paragraphs if p and p.strip())}


def apply_fixes(paragraphs, issues, chosen_ids):
    """Áp dụng các sửa lỗi đã chọn, trả về danh sách đoạn văn mới."""
    chosen = {int(c) for c in chosen_ids}
    by_para = {}
    for iss in issues:
        if iss["id"] in chosen and iss["suggest"] != "" or (
                iss["id"] in chosen and iss["kind"] == "lap_tu"):
            by_para.setdefault(iss["para"], []).append(iss)
    out = list(paragraphs)
    for pi, lst in by_para.items():
        text = out[pi]
        for iss in sorted(lst, key=lambda x: -x["start"]):
            rep = iss["suggest"]
            s, e = iss["start"], iss["end"]
            if iss["kind"] == "lap_tu":
                while s > 0 and text[s - 1] == " ":
                    s -= 1
                rep = ""
            text = text[:s] + rep + text[e:]
        out[pi] = text
    return out

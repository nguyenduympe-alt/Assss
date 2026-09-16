"""Bộ máy sinh nhận xét học sinh (AI nội bộ, chạy offline).

Kiến trúc mở rộng: mỗi "provider" là 1 hàm nhận (ctx) -> str.
Muốn gắn LLM thật (OpenAI/Gemini) chỉ cần thêm provider mới và đăng ký ở PROVIDERS.
"""
import random, re, unicodedata

MUC_DO = ["CHT", "HT", "HTT"]

NGAN_HANG = {
    "HTT": {
        "mo": ["Em {ten} có {kn} rất tốt", "{ten} nắm vững kiến thức môn {mon}",
               "Em {ten} học tập tích cực, {kn} nổi bật", "{ten} thể hiện năng lực {mon} vượt trội"],
        "than": ["hoàn thành xuất sắc các nhiệm vụ học tập", "vận dụng kiến thức linh hoạt vào bài tập thực tế",
                 "tiếp thu bài nhanh và biết giúp đỡ bạn trong nhóm", "trình bày bài sạch đẹp, lập luận chặt chẽ"],
        "ket": ["Tiếp tục phát huy em nhé!", "Cô/thầy mong em giữ vững phong độ này.",
                "Hãy thử sức với các bài nâng cao để tiến xa hơn.", "Em là tấm gương cho các bạn noi theo."],
    },
    "HT": {
        "mo": ["Em {ten} đạt yêu cầu môn {mon}", "{ten} có tiến bộ trong học tập",
               "Em {ten} nắm được kiến thức cơ bản của môn {mon}", "{ten} chăm chỉ, có ý thức học tập"],
        "than": ["hoàn thành các nhiệm vụ học tập được giao", "làm được phần lớn bài tập ở mức cơ bản",
                 "có cố gắng nhưng đôi lúc còn thiếu tập trung", "kỹ năng trình bày đã rõ ràng hơn trước"],
        "ket": ["Cần luyện tập thêm dạng bài nâng cao.", "Nếu chủ động phát biểu hơn em sẽ tiến bộ nhanh.",
                "Hãy dành thêm thời gian ôn bài ở nhà.", "Cố gắng thêm một chút nữa em nhé!"],
    },
    "CHT": {
        "mo": ["Em {ten} chưa hoàn thành yêu cầu môn {mon}", "{ten} còn gặp khó khăn với môn {mon}",
               "Em {ten} cần cố gắng nhiều hơn ở môn {mon}"],
        "than": ["chưa nắm chắc kiến thức nền tảng", "còn nhầm lẫn ở các bài tập cơ bản",
                 "chưa hoàn thành bài tập về nhà đều đặn", "tốc độ làm bài còn chậm, hay bỏ sót yêu cầu"],
        "ket": ["Thầy/cô sẽ hỗ trợ thêm, em đừng nản nhé.", "Em nên ôn lại kiến thức cũ và hỏi bài khi chưa hiểu.",
                "Gia đình cần phối hợp nhắc nhở em học bài ở nhà.", "Hãy bắt đầu từ những bài dễ để lấy lại tự tin."],
    },
}

# Thang điểm -> mức độ
def diem_to_mucdo(diem, thang=10.0):
    if diem is None:
        return None
    d = float(diem) * (10.0 / thang)
    if d >= 8: return "HTT"
    if d >= 5: return "HT"
    return "CHT"


def diem_to_xeploai(diem, thang=10.0):
    d = float(diem) * (10.0 / thang)
    if d >= 9: return "Xuất sắc"
    if d >= 8: return "Giỏi"
    if d >= 6.5: return "Khá"
    if d >= 5: return "Đạt"
    return "Chưa đạt"


KEYWORDS = {
    "tư duy logic": ["toán", "tin", "lý", "vật lý"],
    "khả năng diễn đạt": ["văn", "ngữ văn", "tiếng việt", "anh", "tiếng anh"],
    "tinh thần tìm tòi": ["khoa học", "tnxh", "sử", "địa", "lịch sử", "địa lí"],
    "năng khiếu thực hành": ["mĩ thuật", "âm nhạc", "thể dục", "công nghệ"],
}


def _kynang(mon):
    m = (mon or "").lower()
    for k, vs in KEYWORDS.items():
        if any(v in m for v in vs):
            return k
    return "kỹ năng học tập"


def _rand(seed_text):
    return random.Random(hash(seed_text) & 0xFFFFFFFF)


def provider_rule(ctx):
    """Sinh nhận xét bằng luật + ngân hàng câu, có yếu tố cá nhân hoá ổn định."""
    md = ctx.get("muc_do") or diem_to_mucdo(ctx.get("diem"), ctx.get("thang", 10)) or "HT"
    md = md.upper()
    if md not in NGAN_HANG:
        md = "HT"
    bank = NGAN_HANG[md]
    ten = ctx.get("ho_ten", "").strip() or "Em"
    ten_ngan = ten.split()[-1] if ten else "Em"
    r = _rand(ten + str(ctx.get("mon")) + md + str(ctx.get("diem")))
    mo = r.choice(bank["mo"]).format(ten=ten_ngan, mon=ctx.get("mon", "này"), kn=_kynang(ctx.get("mon")))
    than = r.choice(bank["than"])
    ket = r.choice(bank["ket"])
    goc = (ctx.get("nhan_xet_goc") or "").strip()
    extra = ""
    if goc:
        extra = " Ghi nhận của giáo viên: " + goc.rstrip(".") + "."
    diem_txt = ""
    if ctx.get("diem") is not None and ctx.get("hien_diem", True):
        diem_txt = f" (Điểm: {ctx['diem']:g} - {diem_to_xeploai(ctx['diem'], ctx.get('thang',10))})"
    return f"{mo}, {than}.{extra} {ket}{diem_txt}"


def provider_ngan(ctx):
    md = (ctx.get("muc_do") or diem_to_mucdo(ctx.get("diem"), ctx.get("thang", 10)) or "HT").upper()
    bank = NGAN_HANG.get(md, NGAN_HANG["HT"])
    ten = (ctx.get("ho_ten") or "Em").split()[-1]
    r = _rand(ten + md)
    return f"{r.choice(bank['mo']).format(ten=ten, mon=ctx.get('mon','này'), kn=_kynang(ctx.get('mon')))}. {r.choice(bank['ket'])}"


PROVIDERS = {
    "rule": ("AI nội bộ - nhận xét đầy đủ", provider_rule),
    "ngan": ("AI nội bộ - nhận xét ngắn gọn", provider_ngan),
}


def sinh_nhan_xet(ctx, provider="rule"):
    fn = PROVIDERS.get(provider, PROVIDERS["rule"])[1]
    try:
        return fn(ctx)
    except Exception as e:
        return f"(Lỗi sinh nhận xét: {e})"

"""Bộ máy sinh nhận xét học sinh (AI nội bộ, chạy offline).

Kiến trúc mở rộng: mỗi "provider" là 1 hàm nhận (ctx) -> str.
Muốn gắn LLM thật (OpenAI/Gemini) chỉ cần thêm provider mới và đăng ký ở PROVIDERS.
"""
import random, re, unicodedata

MUC_DO = ["CHT", "HT", "HTT"]

# Một câu ngắn. Danh xưng "Em". Tích cực. Chỉ điểm + mức đạt.
NGAN_HANG = {
    "HTT": [
        "Em hoàn thành tốt môn {mon}. Cố lên em nhé!",
        "Em học {mon} rất đáng khen. Phát huy nhé!",
        "Em có {kn} tốt. Tiếp tục như vậy nhé!",
        "Em làm bài {mon} chắc và tự tin. Giữ nhịp này nhé!",
        "Em hoàn thành xuất sắc môn {mon}. Thầy/cô rất tự hào về em!",
        "Em tiếp thu bài {mon} nhanh. Giữ vững phong độ nhé!",
    ],
    "HT": [
        "Em đã hoàn thành môn {mon}. Cố lên em nhé!",
        "Em có tiến bộ môn {mon}. Cô/thầy tin em sẽ còn hơn nữa!",
        "Em chăm chỉ môn {mon}. Tiếp tục phát huy nhé!",
        "Em nắm bài {mon} khá tốt. Cố gắng thêm em nhé!",
        "Em cần chú ý hơn khi làm bài {mon}. Cố lên em nhé!",
        "Em nắm được bài {mon}. Rèn thêm để tự tin hơn nhé!",
    ],
    "CHT": [
        "Em đã cố gắng môn {mon}. Cô/thầy tin em làm được!",
        "Em đừng nản nhé, mỗi ngày một chút là tiến bộ rồi!",
        "Em hãy hỏi khi chưa rõ. Cô/thầy luôn hỗ trợ em!",
        "Em đang tiến bộ dần môn {mon}. Cố lên em nhé!",
        "Em cần ôn lại bài {mon} thường xuyên. Thầy/cô đồng hành cùng em!",
        "Em hãy làm bài tập đều đặn mỗi ngày nhé. Cố lên em!",
    ],
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


def _muc_do(ctx):
    """Mức đạt: ưu tiên cột mức do giáo viên chọn, không có thì suy từ điểm."""
    md = str(ctx.get("muc_do") or "").strip().upper()
    if md in NGAN_HANG:
        return md
    return diem_to_mucdo(ctx.get("diem"), ctx.get("thang", 10)) or "HT"


def _cau(ctx):
    """Một câu ngắn: Em + điểm/mức, không tên, giọng khích lệ."""
    md = _muc_do(ctx)
    # seed kèm họ tên để các học sinh cùng mức vẫn có câu khác nhau
    r = _rand(md + str(ctx.get("diem")) + str(ctx.get("mon")) + str(ctx.get("thang"))
              + str(ctx.get("ho_ten") or ""))
    txt = r.choice(NGAN_HANG[md]).format(mon=ctx.get("mon") or "này", kn=_kynang(ctx.get("mon")))
    goc = (ctx.get("nhan_xet_goc") or "").strip()
    if goc:
        txt = txt.rstrip(".!") + ". " + goc.rstrip(".") + "."
    if ctx.get("diem") is not None and ctx.get("hien_diem"):
        txt += f" ({ctx['diem']:g}đ)"
    return txt


def provider_rule(ctx):
    return _cau(ctx)


def provider_ngan(ctx):
    return _cau(ctx)


PROVIDERS = {
    "ngan": ("AI nội bộ — nhận xét ngắn gọn", provider_ngan),
    "rule": ("AI nội bộ — nhận xét ngắn gọn", provider_rule),
}


def sinh_nhan_xet(ctx, provider="ngan"):
    fn = PROVIDERS.get(provider, PROVIDERS["ngan"])[1]
    try:
        return fn(ctx)
    except Exception as e:
        return f"(Lỗi sinh nhận xét: {e})"

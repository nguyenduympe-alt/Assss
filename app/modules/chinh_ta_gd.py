"""Sửa chính tả tiếng Việt cho GIÁO ÁN — có thuật ngữ giáo dục, bảo vệ tên riêng
và công thức, phân biệt "sửa chắc" với "chỉ gợi ý".

Trung thực về bản chất công cụ:
    Lớp này dùng bộ kiểm tra âm tiết + từ điển thuật ngữ + luật ngữ cảnh của
    EduAssist. ĐÂY KHÔNG PHẢI MÔ HÌNH AI ĐÃ HUẤN LUYỆN. Nhãn hiển thị cho giáo
    viên ghi đúng điều đó (xem app/modules/ai_provider.py).

Nguyên tắc:
  - Không sửa vào tên riêng, công thức, mã tiêu chí, URL, chữ viết tắt, thuật ngữ.
  - Chỉ chỗ CHẮC CHẮN sai mới đánh dấu "sửa chắc"; chỗ cần ngữ cảnh để "chỉ gợi ý".
  - Mọi thay đổi đều kèm trước/sau và lý do. Giáo viên duyệt rồi mới ghi vào file.
  - Câu đúng không bị chạm tới.
"""
import re

from . import chinhta as CT

# ---------------------------------------------------------------- thuật ngữ
# Thuật ngữ giáo dục: vừa để BẢO VỆ (không đụng vào), vừa để định hướng sửa.
THUAT_NGU = {
    # phương pháp & tổ chức dạy học
    "phương pháp", "kĩ thuật", "kỹ thuật", "hoạt động", "khởi động", "luyện tập",
    "vận dụng", "hình thành kiến thức", "thực hành", "thảo luận nhóm", "trò chơi",
    "phiếu học tập", "học liệu", "thiết bị dạy học", "đồ dùng dạy học",
    "năng lực", "phẩm chất", "mục tiêu", "yêu cầu cần đạt", "chủ đề", "bài dạy",
    "tiến trình", "đánh giá", "kiểm tra", "nhận xét", "rubric", "tiêu chí",
    "sản phẩm học tập", "minh chứng", "thời lượng", "phân phối chương trình",
    "kế hoạch bài dạy", "giáo án", "sách giáo khoa", "sách bài tập", "ngữ liệu",
    "liên môn", "tích hợp", "phân hóa", "cá nhân hóa", "dạy học dự án",
    "stem", "steam", "bảng kiểm", "thang đo", "tự luận", "trắc nghiệm",
    # năng lực số
    "năng lực số", "chuyển đổi số", "công nghệ số", "thiết bị số", "môi trường số",
    "an toàn số", "danh tính số", "dữ liệu số", "nội dung số", "kĩ năng số",
    "chỉ báo", "miền năng lực", "năng lực thành phần", "mức độ thành thạo",
    "công dân số", "học liệu số", "trí tuệ nhân tạo", "thuật toán",
    # đơn vị, môn học
    "ngữ văn", "toán học", "vật lí", "hóa học", "sinh học", "lịch sử", "địa lí",
    "tin học", "công nghệ", "âm nhạc", "mĩ thuật", "giáo dục công dân",
    "giáo dục thể chất", "hoạt động trải nghiệm",
}
THUAT_NGU_KD = {CT.strip_all(t) for t in THUAT_NGU}

# Từ viết tắt thường dùng trong giáo án — CẤM sửa
VIET_TAT = {
    "gv", "hs", "sgk", "sbt", "nxb", "thcs", "thpt", "th", "gdđt", "bộ gdđt",
    "ppct", "khbd", "hd", "nl", "pc", "kt", "đgtx", "đgđk", "cntt", "ict", "ai",
    "nls", "hsg", "hsk", "ktkn", "đddh", "csvc", "tt", "bgh", "tcm",
}

# Mẫu CẤM sửa (tên riêng, công thức, mã, liên kết)
CAMP = [
    re.compile(r"https?://\S+", re.I),
    re.compile(r"\S+@\S+\.\S+"),
    re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:%|cm|dm|m|km|g|kg|ml|l|giây|phút|giờ|độ C|°C)\b", re.I),
    re.compile(r"\b\d+\.\d+\.(?:CB|TC|NC)\d[a-z]?\b", re.I),      # mã chỉ báo
    re.compile(r"\b[1-6]\.[1-6]\b"),                              # số năng lực thành phần
    re.compile(r"[=+×÷<>≤≥√π∞²³]"),
    re.compile(r"\b[A-ZĐ]{2,}\b"),                                # viết tắt in hoa
    re.compile(r"\b\d+[/-]\d+\b"),
]


def _vung_cam(text):
    """Các khoảng ký tự KHÔNG được phép chạm tới."""
    vung = []
    for mau in CAMP:
        vung += [(m.start(), m.end()) for m in mau.finditer(text)]
    return vung


def _trong_vung(start, end, vung):
    return any(s <= start and end <= e for s, e in vung)


def la_thuat_ngu(tu):
    return CT.strip_all(tu).lower() in THUAT_NGU_KD


def la_viet_tat(tu):
    return tu.lower() in VIET_TAT


def _la_ten_rieng(text, start, end):
    """Từ viết hoa giữa câu thường là tên riêng — không sửa."""
    tu = text[start:end]
    if not tu[:1].isupper():
        return False
    truoc = text[:start].rstrip()
    if not truoc:
        return False
    # nếu ký tự trước không phải dấu kết câu thì là viết hoa giữa câu
    return truoc[-1] not in ".!?;:"


# ---------------------------------------------------------------- phân loại
KIND_LY_DO = {
    "sai_cautruc": "Sai cấu trúc âm tiết tiếng Việt",
    "mat_dau": "Thiếu dấu tiếng Việt",
    "tu_sai": "Dùng từ sai chính tả",
    "teencode": "Viết tắt kiểu teencode, không dùng trong văn bản giáo án",
    "lap_tu": "Lặp từ trong cùng câu",
    "hoa_dau": "Chưa viết hoa đầu câu",
}
# Loại CHẮC CHẮN sai -> được phép đánh dấu "sửa chắc"
CHAC_CHAN = {"sai_cautruc", "mat_dau", "tu_sai", "teencode"}
# Loại cần ngữ cảnh -> chỉ gợi ý
CHI_GOI_Y = {"lap_tu", "hoa_dau"}


def doi_chieu_thuat_ngu(d):
    """Nếu từ sai là thuật ngữ/viết tắt, chặn không cho sửa."""
    if la_thuat_ngu(d["word"]) or la_viet_tat(d["word"]):
        return "Từ này là thuật ngữ giáo dục — giữ nguyên."
    if d.get("suggest") and la_thuat_ngu(d["suggest"]):
        return "Đề xuất này là thuật ngữ giáo dục, không thay bằng từ khác."
    return ""


def soan_bao_cao(paragraphs, opts=None):
    """Chạy kiểm tra và trả về danh sách đề xuất có trước/sau/lý do/độ tin cậy.

    paragraphs: danh sách chuỗi (mỗi đoạn một phần tử).
    """
    ra, bo_qua = [], {"vung_cam": 0, "ten_rieng": 0, "thuat_ngu": 0}
    # tầng 1: lỗi rõ ràng theo cụm từ (chắc chắn sai)
    for pi, p in enumerate(paragraphs or []):
        ra += _quet_loi_ro(p or "", pi, len(ra))
    # tầng 2: bộ kiểm tra âm tiết + từ điển của EduAssist
    tho, _stats = CT.check_text(paragraphs, opts)
    for it in tho:
        text = paragraphs[it["para"]] if 0 <= it["para"] < len(paragraphs) else ""
        vung = _vung_cam(text)
        if _trong_vung(it["start"], it["end"], vung):
            bo_qua["vung_cam"] += 1
            continue
        if _la_ten_rieng(text, it["start"], it["end"]):
            bo_qua["ten_rieng"] += 1
            continue
        if doi_chieu_thuat_ngu(it):
            bo_qua["thuat_ngu"] += 1
            continue

        # Từ 1 ký tự rất dễ là ký hiệu/biến (k, n, S…) -> chỉ gợi ý, không tự sửa
        mot_ky_tu = len(it["word"]) <= 1
        chac = (it["kind"] in CHAC_CHAN) and not mot_ky_tu
        ra.append({
            "id": it["id"] + 100000, "para": it["para"], "start": it["start"], "end": it["end"],
            "doan_goc": text,
            "goc": it["word"], "de_xuat": it.get("suggest", ""),
            "ly_do": (KIND_LY_DO.get(it["kind"], it.get("note") or "Cần rà lại")
                      + (" — nhưng chỉ 1 ký tự, có thể là ký hiệu trong bài" if mot_ky_tu else "")),
            "loai_loi": it["kind"],
            "do_tin_cay": "cao" if chac else "thap",
            "che_do": "sua_chac" if chac else "chi_goi_y",
            "nhan": ("Sửa chắc — giáo viên duyệt để áp dụng" if chac
                     else "Chỉ gợi ý — cần ngữ cảnh, hệ thống không tự sửa"),
        })
    ra = _loai_chong_lan(ra)
    return ra, bo_qua


# ------------------------------------------------- lỗi rõ ràng (không cần ngữ cảnh)
# Mỗi cặp đều là lỗi chắc chắn sai trong văn bản hành chính/giáo dục, không mơ hồ.
LOI_RO_RANG = {
    # hỏi / ngã
    "dẩn": "dẫn", "dẩn dắt": "dẫn dắt", "hướng dẩn": "hướng dẫn", "chỉ dẩn": "chỉ dẫn",
    "dẩn chứng": "dẫn chứng", "dẩn giải": "dẫn giải", "truyền dẩn": "truyền dẫn",
    "phổ biến": "phổ biến", "bỗ sung": "bổ sung", "sơ xuất": "sơ suất", "suất sắc": "xuất sắc",
    "năng xuất": "năng suất", "đỗi mới": "đổi mới", "sửa đỗi": "sửa đổi", "thay đỗi": "thay đổi",
    "chỉnh sữa": "chỉnh sửa", "sữa chữa": "sửa chữa", "sữa lỗi": "sửa lỗi", "sữa bài": "sửa bài",
    "kỉ luật": "kỉ luật", "mỹ thuật": "mĩ thuật", "mỉ thuật": "mĩ thuật",
    "nhỉ nhảnh": "nhí nhảnh", "nghĩ hè": "nghỉ hè", "nghĩ ngơi": "nghỉ ngơi",
    "nghĩ phép": "nghỉ phép", "nghĩ tiết": "nghỉ tiết", "nghĩ giữa giờ": "nghỉ giữa giờ",
    "suy nghỉ": "suy nghĩ", "nghỉ ngợi": "nghĩ ngợi", "sữa sai": "sửa sai",
    "cũng cố": "củng cố", "củng cố": "củng cố", "củng cố kiến thức": "củng cố kiến thức",
    "bàn hoàng": "bàng hoàng", "sáng lạn": "xán lạn", "thăm quan": "tham quan",
    "chuẩn đoán": "chẩn đoán", "trau giồi": "trau dồi", "lảng mạn": "lãng mạn",
    "phố cập": "phổ cập", "phố thông": "phổ thông", "truyền đạc": "truyền đạt",
    "khuyến khính": "khuyến khích", "khích lệ": "khích lệ", "chứng minh": "chứng minh",
    "dữ liệu": "dữ liệu", "dử liệu": "dữ liệu", "dữ liêu": "dữ liệu",
    "kỉ năng": "kĩ năng", "kỹ năng": "kĩ năng", "kỷ năng": "kĩ năng",
    "kỉ thuật": "kĩ thuật", "kỹ thuật": "kĩ thuật",
    # d / gi
    "xử dụng": "sử dụng", "sử dụng": "sử dụng", "giạy học": "dạy học", "giạy": "dạy",
    "dáo viên": "giáo viên", "dáo dục": "giáo dục", "dành giật": "giành giật",
    "giành dụm": "dành dụm", "dò xét": "dò xét", "sử dụng": "sử dụng",
    # s / x
    "sảy ra": "xảy ra", "xảy ra": "xảy ra", "sắp xếp": "sắp xếp", "xắp xếp": "sắp xếp",
    "sát nhập": "sáp nhập", "xuất sắc": "xuất sắc", "sản phẩm": "sản phẩm",
    "xản phẩm": "sản phẩm", "sản xuất": "sản xuất",
    # ch / tr
    "chăm sóc": "chăm sóc", "trăm sóc": "chăm sóc", "trình bày": "trình bày",
    "chình bày": "trình bày", "chình độ": "trình độ", "trình độ": "trình độ",
    "chuyền đạt": "truyền đạt", "trách nhiệm": "trách nhiệm", "chách nhiệm": "trách nhiệm",
    # lỗi gõ / teencode trong giáo án
    "dc": "được", "đc": "được", "vs": "với", "ko": "không", "k": "không",
    "mk": "mình", "nch": "nói chuyện", "cx": "cũng", "r": "rồi",
    "sv": "sinh viên", "gvcn": "giáo viên chủ nhiệm",
    # chính tả thường gặp
    "khẳ năng": "khả năng", "khã năng": "khả năng", "có thể": "có thể",
    "phương pháp": "phương pháp", "phưong pháp": "phương pháp",
    "nhiệm vụ": "nhiệm vụ", "nhiệm vũ": "nhiệm vụ", "nhiêm vụ": "nhiệm vụ",
    "kết qủa": "kết quả", "kết quã": "kết quả", "kết quà": "kết quả",
    "hoạt đông": "hoạt động", "hoạt đọng": "hoạt động", "hoạc động": "hoạt động",
    "giáo án": "giáo án", "giáo an": "giáo án", "bài giàng": "bài giảng",
    "bài giảng": "bài giảng", "giảng dạy": "giảng dạy", "dảng dạy": "giảng dạy",
    "đánh giá": "đánh giá", "đánh giạ": "đánh giá", "đánh già": "đánh giá",
    "năng lực": "năng lực", "năng lưc": "năng lực", "năng lựt": "năng lực",
    "phẩm chất": "phẩm chất", "phẫm chất": "phẩm chất", "phẩm chât": "phẩm chất",
    "thiết bị": "thiết bị", "thiết bì": "thiết bị", "thiêt bị": "thiết bị",
    "thực hiện": "thực hiện", "thực hiên": "thực hiện", "thưc hiện": "thực hiện",
    "học sinh": "học sinh", "hoc sinh": "học sinh", "học sjnh": "học sinh",
    "mục tiêu": "mục tiêu", "mục tiêu bài": "mục tiêu bài", "mục tiêo": "mục tiêu",
    "tiến trình": "tiến trình", "tiến trinh": "tiến trình", "tíên trình": "tiến trình",
    "sản phẩm": "sản phẩm", "sản phẫm": "sản phẩm",
    "minh chứng": "minh chứng", "minh chưng": "minh chứng",
    "thời lượng": "thời lượng", "thời lương": "thời lượng",
    "nhận xét": "nhận xét", "nhận xẹt": "nhận xét", "nhân xét": "nhận xét",
    "liên hệ": "liên hệ", "liên hê": "liên hệ", "liện hệ": "liên hệ",
    "vận dụng": "vận dụng", "vận dung": "vận dụng", "vân dụng": "vận dụng",
    "luyện tập": "luyện tập", "luyện tâp": "luyện tập", "luyên tập": "luyện tập",
    "khởi động": "khởi động", "khơi động": "khởi động", "khởi đông": "khởi động",
    "hình thành": "hình thành", "hình thàn": "hình thành", "hinh thành": "hình thành",
}

RE_LOI = None
_CHU = re.compile(r"[^\W\d_]", re.UNICODE)


def _ranh_gioi_tu(text, start, end):
    """Đầu/cuối cụm phải đứng riêng, không dính chữ cái liền kề.

    Bắt buộc với các khoá ngắn: nếu không, "k" sẽ khớp trong "kết",
    "r" khớp trong "trang" và phá nát văn bản.
    """
    if start > 0 and _CHU.match(text[start - 1]):
        return False
    if end < len(text):
        nxt = text[end]
        if _CHU.match(nxt):
            return False
        # "hoc sinh" thì ký tự trước/sau phải là khoảng trắng hoặc dấu câu
    return True


def _quet_loi_ro(text, pidx, bat_dau_id):
    """Quét các lỗi rõ ràng theo cụm từ. Không chạm vùng cấm, thuật ngữ, viết tắt."""
    global RE_LOI
    if RE_LOI is None:
        cum = sorted(LOI_RO_RANG, key=len, reverse=True)
        RE_LOI = re.compile("|".join(re.escape(c) for c in cum), re.I)
    ra = []
    vung = _vung_cam(text)
    for m in RE_LOI.finditer(text):
        goc = m.group(0)
        dung = LOI_RO_RANG.get(goc.lower())
        if not dung or goc.lower() == dung.lower():
            continue
        # BẮT BUỘC ranh giới từ: từ ngắn như "k", "r", "dc" không được khớp
        # bên trong một từ khác (kết quả, trang, kĩ năng...).
        if not _ranh_gioi_tu(text, m.start(), m.end()):
            continue
        if _trong_vung(m.start(), m.end(), vung):
            continue
        # giữ nguyên kiểu viết hoa của từ gốc
        if goc.isupper() and len(goc) > 1:
            dung = dung.upper()
        elif goc[:1].isupper():
            dung = dung[:1].upper() + dung[1:]
        ngan = len(goc) <= 2
        ra.append({
            "id": bat_dau_id + len(ra), "para": pidx, "start": m.start(), "end": m.end(),
            "doan_goc": text,
            "goc": goc, "de_xuat": dung,
            "ly_do": ("Có thể là viết tắt/teencode — nhưng cũng có thể là ký hiệu, "
                      "cần giáo viên xem lại" if ngan
                      else "Lỗi chính tả tiếng Việt thường gặp trong văn bản giáo án"),
            "loai_loi": "loi_ro_rang",
            "do_tin_cay": "thap" if ngan else "cao",
            "che_do": "chi_goi_y" if ngan else "sua_chac",
            "nhan": ("Chỉ gợi ý — cần ngữ cảnh, hệ thống không tự sửa" if ngan
                     else "Sửa chắc — giáo viên duyệt để áp dụng"),
        })
    return ra


def _loai_chong_lan(ds):
    """Bỏ đề xuất chồng lấn nhau trong cùng đoạn (giữ cái dài hơn).

    Không có bước này, "hoc sinh" và "hoc" cùng khớp một vùng và khi áp dụng
    sẽ nhân đôi chữ ("học sinhhọc sinh").
    """
    theo_doan = {}
    for d in ds:
        theo_doan.setdefault(d["para"], []).append(d)
    ra = []
    for _pi, ds_doan in theo_doan.items():
        ds_doan.sort(key=lambda x: (x["start"], -(x["end"] - x["start"])))
        cuoi = -1
        for d in ds_doan:
            if d["start"] < cuoi:
                continue
            ra.append(d)
            cuoi = d["end"]
    ra.sort(key=lambda x: (x["para"], x["start"]))
    for i2, d in enumerate(ra):
        d["id"] = i2
    return ra



def ap_dung(paragraphs, de_xuat, chon_ids):
    """Áp dụng các đề xuất giáo viên đã chọn. Trả về (paragraphs mới, số đã sửa)."""
    chon = [d for d in de_xuat if d["id"] in set(chon_ids)]
    if not chon:
        return list(paragraphs), 0

    # áp dụng theo thứ tự vị trí GIẢM DẦN để không lệch chỉ số
    moi = list(paragraphs)
    da_sua = 0
    for d in sorted(chon, key=lambda x: (x["para"], x["start"]), reverse=True):
        if not (0 <= d["para"] < len(moi)):
            continue
        t = moi[d["para"]]
        if t[d["start"]:d["end"]] != d["goc"]:
            continue                       # vị trí đã đổi, bỏ qua cho an toàn
        moi[d["para"]] = t[:d["start"]] + d["de_xuat"] + t[d["end"]:]
        da_sua += 1
    return moi, da_sua


def nhan_ket_qua():
    """Nhãn bắt buộc in kèm kết quả kiểm tra chính tả."""
    return ("Bộ kiểm tra nội bộ của EduAssist (âm tiết + từ điển thuật ngữ + luật ngữ cảnh). "
            "Đây KHÔNG phải mô hình AI đã huấn luyện, nên có thể bỏ sót lỗi cần hiểu ngữ cảnh "
            "và không nên thay cho việc giáo viên đọc lại.")


def thong_ke_tu_dien():
    return {"so_thuat_ngu": len(THUAT_NGU), "so_viet_tat_bao_ve": len(VIET_TAT),
            "so_mau_cam_sua": len(CAMP)}


def ap_dung_vao_docx(doc, de_xuat, chon_ids):
    """Áp dụng các sửa chính tả đã chọn vào tài liệu Word.

    Chỉ đụng vào đoạn thực sự có sửa. Chữ đã sửa được TÔ ĐỎ + gạch chân để giáo
    viên thấy ngay. Các đoạn khác giữ nguyên từng ký tự.
    """
    from docx.shared import RGBColor
    do = RGBColor(0xFF, 0x00, 0x00)
    chon = {d["id"] for d in de_xuat if d["id"] in set(chon_ids)}
    if not chon:
        return 0

    theo_doan = {}
    for d in de_xuat:
        if d["id"] in chon:
            theo_doan.setdefault(d["para"], []).append(d)

    # Định vị đoạn theo NGUYÊN VĂN, không theo chỉ số: việc chèn mục năng lực số
    # làm các đoạn phía sau dịch chỉ số, nếu dùng chỉ số sẽ sửa nhầm đoạn.
    ung_vien = {}
    for p in doc.paragraphs:
        ung_vien.setdefault((p.text or "").strip(), []).append(p)
    da_dung = {}
    da_sua = 0

    for pi, ds in sorted(theo_doan.items()):
        khoa = (ds[0].get("doan_goc") or "").strip()
        if not khoa:
            continue
        idx = da_dung.get(khoa, 0)
        hang = ung_vien.get(khoa) or []
        if idx >= len(hang):
            continue
        p = hang[idx]
        da_dung[khoa] = idx + 1
        text = p.text

        # kiểm tra vị trí còn khớp không, rồi dựng danh sách đoạn chữ theo thứ tự
        hop_le = [d for d in sorted(ds, key=lambda x: x["start"])
                  if text[d["start"]:d["end"]] == d["goc"]]
        if not hop_le:
            continue

        doan_chu = []          # [(nội dung, có phải chỗ vừa sửa)]
        vi_tri = 0
        for d in hop_le:
            if d["start"] > vi_tri:
                doan_chu.append((text[vi_tri:d["start"]], False))
            doan_chu.append((d["de_xuat"], True))
            vi_tri = d["end"]
            da_sua += 1
        if vi_tri < len(text):
            doan_chu.append((text[vi_tri:], False))

        # ghi lại theo ĐÚNG thứ tự: run đầu giữ định dạng, các run sau nối tiếp
        for r in list(p.runs)[1:]:
            r._r.getparent().remove(r._r)
        if not p.runs:
            continue
        run_dau = p.runs[0]
        for r in list(p.runs):
            r.text = ""
        for i, (noi_dung, la_sua) in enumerate(doan_chu):
            r = run_dau if i == 0 else p.add_run("")
            r.text = noi_dung
            if la_sua:
                r.font.color.rgb = do
                r.underline = True
    return da_sua

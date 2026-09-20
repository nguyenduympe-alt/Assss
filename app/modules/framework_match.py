"""Đối chiếu nội dung bài với KHO CHỈ BÁO ĐÃ KIỂM CHỨNG (assets/khung-nld-so.json).

KHÁC BẢN CŨ: bản cũ tự ghép mã bằng `thành_phần + mức + "a"`, có thể sinh ra mã
không tồn tại trong văn bản của Bộ. Bản này chỉ trả về bản ghi CÓ THẬT trong kho
(tra qua modules/nld.py), kèm nguyên văn chỉ báo và nguồn; nếu mức của lớp không
có chỉ báo tương ứng thì bỏ qua và ghi rõ lý do, không bịa mã.

Đây là đối chiếu bằng luật + từ khoá ngữ cảnh. KHÔNG phải mô hình AI sinh nội dung.
"""
from . import nld

# Ngữ cảnh dạy học -> thành phần năng lực số liên quan.
# Khoá là các cụm từ đã bỏ dấu, tìm trong nội dung văn bản của giáo án/bài học.
CONTEXTS = [
    (("tim kiem thong tin", "tim thong tin", "tra cuu tren internet", "tim kiem va danh gia"),
     ("1.1", "1.2"),
     "Tìm thông tin phục vụ bài học, so sánh nguồn và ghi lại căn cứ lựa chọn; "
     "đánh giá qua kết quả tìm kiếm và nguồn trích dẫn."),
    (("danh gia thong tin", "kiem chung thong tin", "tin gia", "nguon tin cay"),
     ("1.2", "1.3"),
     "Kiểm chứng một thông tin bằng hai nguồn, ghi lại căn cứ và nêu điểm chưa chắc chắn."),
    (("tep va thu muc", "quan ly tep", "luu tru du lieu", "sap xep tep", "luu tep"),
     ("1.3",),
     "Tạo, đặt tên, sắp xếp và mở lại tệp/thư mục của bài học; "
     "kiểm tra bằng nhiệm vụ truy xuất sản phẩm."),
    (("thu dien tu", "email", "giao tiep truc tuyen", "tin nhan"),
     ("2.1", "2.2"),
     "Soạn thông điệp cho tình huống học tập, chọn kênh phù hợp và dùng ngôn ngữ lịch sự; "
     "đánh giá bằng bảng kiểm."),
    (("chia se thong tin", "chia se tep", "chia se noi dung", "chia se hoc lieu"),
     ("2.2", "2.3"),
     "Chia sẻ học liệu đúng người nhận, ghi nguồn và kiểm tra dữ liệu cá nhân trước khi gửi."),
    (("hop tac truc tuyen", "lam viec nhom truc tuyen", "cong tac", "lam viec nhom tren mang"),
     ("2.4", "2.5"),
     "Cùng tạo một sản phẩm trên công cụ số được giáo viên chọn, phân công nhiệm vụ "
     "và ghi nhận đóng góp."),
    (("soan thao van ban", "word", "trinh chieu", "powerpoint", "ve tren may tinh",
      "tao bai trinh chieu", "thiet ke thiep", "bang tinh"),
     ("3.1", "3.2"),
     "Tạo sản phẩm số phục vụ bài học, ghi nguồn học liệu; "
     "đánh giá theo nội dung, khả năng trình bày và sử dụng tư liệu hợp lệ."),
    (("ban quyen", "giay phep", "trich dan nguon", "tai su dung", "dao van"),
     ("3.3",),
     "Nhận diện tư liệu được phép sử dụng và bổ sung thông tin nguồn vào sản phẩm học tập."),
    (("lap trinh", "scratch", "thuat toan", "robot", "code", "chuong trinh"),
     ("3.4", "5.3"),
     "Xây dựng chuỗi lệnh cho nhiệm vụ, chạy thử và sửa lỗi; "
     "đánh giá qua chương trình và mô tả cách kiểm thử."),
    (("an toan tren mang", "mat khau", "thong tin ca nhan", "bao mat", "an toan so"),
     ("4.1", "4.2"),
     "Phân loại thông tin được phép chia sẻ, nhận biết tình huống rủi ro "
     "và thực hành phản hồi an toàn."),
    (("thiet bi so", "may tinh", "may chieu", "dien thoai", "su dung thiet bi"),
     ("4.3", "4.4"),
     "Thực hành thao tác thiết bị đúng cách và xử lý một lỗi đơn giản; "
     "giáo viên quan sát theo bảng kiểm."),
    (("rac thai dien tu", "tiet kiem dien", "bao quan may tinh", "moi truong"),
     ("4.4",),
     "Xác định tác động môi trường của thiết bị số, đề xuất và thực hành một việc "
     "giảm tác động đó."),
    (("tri tue nhan tao", "ai", "chatbot", "hoc may"),
     ("6.1", "6.3"),
     "Giáo viên minh họa đầu ra của AI, học sinh đối chiếu với học liệu và nêu giới hạn; "
     "không nhập dữ liệu cá nhân."),
]


def _bo_dau(s):
    import unicodedata
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


def _khop_cum(van_ban, cum):
    """Khớp cụm từ theo RANH GIỚI TỪ.

    Bắt buộc với cụm ngắn: nếu khớp chuỗi con thì "ai" sẽ khớp trong "bài"
    và bài Ngữ văn bị gán nhầm chỉ báo về trí tuệ nhân tạo.
    """
    import re
    return re.search(r"(?<![a-z0-9])" + re.escape(cum) + r"(?![a-z0-9])", van_ban) is not None


def _muc(lop):
    return nld.muc_do_theo_lop(str(lop or ""))


def match(text, grade, toi_da=3):
    """Trả về tối đa `toi_da` chỉ báo CÓ THẬT trong kho, phù hợp nội dung và mức lớp."""
    level = _muc(grade)
    if not level:
        return []
    van_ban = _bo_dau(text)
    ra, da_dung = [], set()
    for cum, comps, hoat_dong in CONTEXTS:
        khop = next((c for c in cum if _khop_cum(van_ban, c)), None)
        if not khop:
            continue
        for comp in comps:
            if len(ra) >= toi_da:
                break
            for ung_vien in nld.tra_theo_thanh_phan(comp, level):
                if ung_vien["code"] in da_dung:
                    continue
                da_dung.add(ung_vien["code"])
                ra.append({
                    "code": ung_vien["code"],
                    "name": "%s — %s" % (ung_vien["domain"], ung_vien["name"]),
                    "description": ung_vien.get("verbatim") or ung_vien.get("verbatim_full_muc", ""),
                    "evidence": khop,
                    "activity": hoat_dong,
                    "level": ung_vien["level"],
                    "source": "https://vanban.chinhphu.vn/?pageid=27160&docid=213553",
                    "nguon_van_ban": ung_vien.get("source", ""),
                    "vi_tri_nguon": ung_vien.get("source_location", ""),
                    "status": "Đề xuất tự động từ kho chỉ báo đã kiểm chứng — giáo viên xác nhận",
                })
                break
        if len(ra) >= toi_da:
            break
    return ra[:toi_da]


def mo_ta_nguon():
    """Thông tin nguồn của kho, để hiển thị cho giáo viên."""
    k = nld.thong_ke()
    kho = nld.kho()
    return {"can_cu": k.get("can_cu", ""), "cong_van": k.get("cong_van", ""),
            "phien_ban": k.get("phien_ban", ""), "ghi_chu": (kho.get("nguon") or {}).get("ghi_chu", "")}

"""Tích hợp năng lực số vào giáo án: chọn tiêu chí CÓ NGUỒN, sinh mục tiêu và
hoạt động, chèn đúng chỗ trong Word, tô đỏ nội dung mới, kiểm tra đầu ra.

PHÂN BIỆT RÕ HAI LOẠI NỘI DUNG:
  [QUY ĐỊNH] — nguyên văn tiêu chí/chỉ báo lấy từ kho đã kiểm chứng, không sửa một chữ.
  [ĐỀ XUẤT]  — phần hệ thống soạn cho bài học cụ thể (mục tiêu riêng, hoạt động,
               minh chứng). Là gợi ý, giáo viên duyệt trước khi dùng.

Hệ thống CHỈ dùng mã có thật trong kho. Tra không thấy thì bỏ qua và báo thiếu —
tuyệt đối không ghép mã mới hay gán bừa quy định.
"""
import copy
import re

from docx.oxml.ns import qn

from . import ai_giao_duc as AIGD
from . import nld
from .giao_an import (DO, MAU_MOI, NHAN_AI, RE_DONG_DO_HE_THONG, RE_HOAT_DONG_HE_THONG, RE_TIEU_DE_AI,
                       XANH,
                       doan_mau, gon, khong_dau, la_tieu_de_ai,
                       la_tieu_de_nld, phan_tich, _xoa_muc_nld_cu)

NHAN_QD = "[QUY ĐỊNH]"
# So khớp trên văn bản ĐÃ BỎ DẤU (khong_dau) nên mẫu cũng phải viết không dấu.
RE_HOAT_DONG_BANG = re.compile(r"^\s*hoat\s*dong\s*tich\s*hop\s*nang\s*luc\s*so\b", re.I)
# Dòng hoạt động GIÁO DỤC AI do hệ thống chèn (khác dòng hoạt động năng lực số).
RE_HOAT_DONG_AI_BANG = re.compile(
    r"^\s*hoat\s*dong\s*tich\s*hop\s*giao\s*duc\s*ai\b", re.I)
NHAN_AI_TIEU_DE = "Tích hợp giáo dục trí tuệ nhân tạo (AI)"
NHAN_DX = "[ĐỀ XUẤT]"

# ---------------------------------------------------------------- ánh xạ nội dung
# (từ khoá trong bài — danh sách mã năng lực thành phần CÓ THẬT trong kho,
#  tên hoạt động gợi ý, sản phẩm học tập, minh chứng đánh giá)
# ------------------------------------------------------------------ ngữ cảnh theo cấp học
# Mỗi mục: (từ khoá, thành phần năng lực, tên hoạt động, sản phẩm, minh chứng).
# Từ khoá được khớp theo RANH GIỚI TỪ (xem _khop), nên "ai" không khớp trong
# "bài", "ve" không khớp trong "vẻ". Cụm càng dài càng được ưu tiên.
NGU_CANH_TIEU_HOC = [
    # Chỉ giữ các ngữ cảnh CÓ DẤU HIỆU SỐ thật sự. Bài thuần giấy (đọc, viết, làm
    # toán trên bảng con) sẽ rơi vào nhánh “cần giáo viên duyệt” thay vì bị gán bừa.
    (("xem video", "bang tuong tac", "hoc lieu so", "bai giang dien tu", "nghe nhac",
      "xem phim", "nghe co", "tivi", "man hinh", "may tinh bang", "tranh anh so",
      "sach dien tu", "quan sat tren man hinh"),
     ("3.1", "1.1"),
     "Quan sát học liệu số do giáo viên trình chiếu và nói lại điều quan sát được",
     "Câu trả lời của học sinh về nội dung đã quan sát",
     "Kể lại được nội dung chính và nhận ra hình ảnh/âm thanh do thiết bị số mang lại"),
    (("tro choi hoc tap", "tro choi tren may", "luyen tap tren may", "phan mem hoc tap",
      "cham diem", "thi dau", "do vui", "ung dung hoc tap", "phan mem toan", "hoc toan tren may"),
     ("5.1", "5.2"),
     "Tham gia trò chơi/luyện tập trên thiết bị do giáo viên điều khiển",
     "Kết quả lượt chơi của nhóm / câu trả lời của học sinh",
     "Tham gia đúng lượt, nêu được vì sao chọn đáp án đó"),
    (("chon hinh anh", "tim hinh anh", "in tranh", "lam the", "trang tri", "ve tren may",
      "to mau tren may", "tao san pham so"),
     ("3.1", "3.2"),
     "Chọn và sắp xếp hình ảnh số theo yêu cầu của bài với sự hướng dẫn của giáo viên",
     "Phiếu bài tập hoặc sản phẩm có hình ảnh do học sinh chọn",
     "Chọn đúng hình theo yêu cầu và nói được hình đó minh hoạ cho phần nào của bài"),
    (("may tinh", "may tinh bang", "dien thoai", "thiet bi so", "chuot", "ban phim",
      "man hinh", "loa", "tai nghe", "phan mem", "cai dat", "khoi dong may", "tat may",
      "bao quan may", "tiet kiem dien", "rac thai dien tu"),
     ("4.1", "4.3"),
     "Nhận biết các bộ phận của thiết bị số và thao tác đúng cách theo hướng dẫn",
     "Bảng kiểm thao tác đúng do học sinh tự đánh dấu",
     "Chỉ đúng bộ phận thiết bị, thao tác đúng bước và nêu được một việc giữ an toàn"),
    (("thong tin ca nhan", "quyen rieng tu", "mat khau", "an toan tren mang", "bi bat nat",
      "tro chuyen voi nguoi la", "du lieu ca nhan", "khong chia se thong tin"),
     ("4.2", "4.3"),
     "Trao đổi về việc giữ an toàn thông tin cá nhân khi dùng thiết bị",
     "Bản cam kết ngắn của học sinh về quy tắc an toàn",
     "Nêu được việc không nên làm và việc cần hỏi người lớn"),
    (("nguon tin", "tin cay", "kiem tra thong tin", "thong tin dung hay sai", "tin gia"),
     ("1.2", "1.3"),
     "Phân biệt thông tin đúng và thông tin sai trong tình huống quen thuộc",
     "Bảng đúng/sai của nhóm trên phiếu học tập",
     "Giải thích được vì sao chọn đúng hoặc sai"),
]

NGU_CANH_CHUNG = [
    (("tim kiem", "tra cuu", "tim va danh gia", "danh gia thong tin", "nguon tham khao",
      "tim thong tin", "hoc lieu so", "internet", "tu lieu"),
     ("1.1", "1.2"),
     "Tìm và đánh giá học liệu số",
     "Bảng ghi chép kết quả tìm kiếm kèm nguồn tham khảo",
     "Nêu được nguồn đã dùng và lý do chọn nguồn đó"),
    (("luu tru", "quan ly tep", "thu muc", "sap xep tep", "dat ten tep", "luu san pham"),
     ("1.3",),
     "Sắp xếp và lưu trữ sản phẩm học tập",
     "Thư mục sản phẩm của nhóm, đặt tên theo quy ước của lớp",
     "Mở lại được sản phẩm đã lưu, đúng tên và đúng vị trí"),
    (("thu dien tu", "tin nhan", "trao doi truc tuyen", "giao tiep truc tuyen", "hop truc tuyen"),
     ("2.1", "2.2"),
     "Trao đổi và chia sẻ học liệu trong nhóm",
     "Thông điệp hoặc tệp học liệu gửi đúng người nhận",
     "Dùng ngôn ngữ phù hợp, ghi nguồn và không chia sẻ dữ liệu cá nhân"),
    (("lam viec nhom", "hop tac", "san pham chung", "phan cong nhiem vu", "lam viec truc tuyen"),
     ("2.4", "2.5"),
     "Cùng tạo và hoàn thiện sản phẩm chung của nhóm",
     "Phần đóng góp của từng thành viên trong sản phẩm chung",
     "Nêu được việc mình đã làm và việc nhóm cùng làm"),
    (("soan thao van ban", "trinh chieu", "bai trinh chieu", "so do tu duy", "sang tao noi dung",
      "thiet ke", "tao san pham so", "dung phan mem"),
     ("3.1", "3.2"),
     "Tạo sản phẩm số minh hoạ nội dung bài học",
     "Sản phẩm số của nhóm (bài trình bày, sơ đồ, tranh minh hoạ)",
     "Sản phẩm bám nội dung bài, có ghi nguồn tư liệu sử dụng"),
    (("ban quyen", "giay phep", "nguon anh", "trich dan", "dao van", "tai su dung"),
     ("3.3",),
     "Ghi nguồn và sử dụng học liệu hợp lệ",
     "Danh mục tư liệu kèm nguồn in trong sản phẩm",
     "Chỉ ra được tư liệu nào được phép dùng và đã ghi nguồn ở đâu"),
    (("bang tinh", "excel", "google sheets", "xu ly so lieu", "bieu do", "thong ke so lieu"),
     ("3.2", "5.2"),
     "Dùng bảng tính để xử lý số liệu của bài học",
     "Tệp bảng tính có số liệu, công thức và biểu đồ",
     "Kiểm tra lại được kết quả bằng công thức và nhận xét biểu đồ"),
    (("lap trinh", "thuat toan", "scratch", "python", "chuong trinh", "robot", "code",
      "thiet ke thuat toan", "mo phong"),
     ("3.4", "5.3"),
     "Xây dựng chuỗi lệnh/ chương trình cho nhiệm vụ của bài",
     "Chương trình hoặc sản phẩm chạy thử của nhóm",
     "Chạy thử, phát hiện lỗi và mô tả cách sửa"),
    (("thiet bi so", "may tinh", "dien thoai", "may tinh bang", "phan cung", "phan mem",
      "cai dat", "bo nho", "luu tru may"),
     ("4.1", "4.3"),
     "Sử dụng thiết bị số đúng cách và an toàn",
     "Bảng kiểm quy tắc sử dụng thiết bị của nhóm",
     "Thao tác đúng quy trình và nêu được cách xử lý một lỗi đơn giản"),
    (("suc khoe", "tu the", "mat", "thoi gian su dung", "anh sang", "nghi ngoi"),
     ("4.3",),
     "Giữ tư thế và thời lượng dùng thiết bị hợp lý",
     "Bảng tự đánh giá tư thế và thời gian dùng thiết bị",
     "Tự nêu được việc mình cần điều chỉnh khi dùng thiết bị"),
    (("an toan tren mang", "mat khau", "thong tin ca nhan", "bao mat", "quyen rieng tu",
      "lua dao", "tin gia", "bat nat truc tuyen", "an ninh mang"),
     ("4.2", "2.5"),
     "Nhận diện tình huống rủi ro và thực hành phản hồi an toàn",
     "Bảng xử lý tình huống do nhóm xây dựng",
     "Phân loại được thông tin nên và không nên chia sẻ, nêu cách phản hồi phù hợp"),
    (("rac thai dien tu", "tiet kiem dien", "bao quan may", "moi truong"),
     ("4.4",),
     "Đánh giá tác động môi trường của việc dùng thiết bị số và đề xuất việc làm giảm tác động",
     "Danh sách việc làm giảm tác động kèm minh chứng đã thực hiện",
     "Nêu được tác động và một việc đã làm thực tế"),
]

NGU_CANH_THPT = [
    (("tri tue nhan tao", "chatbot", "tro ly ao", "ai tao sinh", "hoc may", "du lieu lon",
      "ung dung ai"),
     ("6.1", "6.3"),
     "Tìm hiểu cách AI tạo ra kết quả và giới hạn của nó trong bài học",
     "Bản so sánh kết quả AI với nguồn học thuật đã kiểm chứng",
     "Nêu được ít nhất hai giới hạn của kết quả AI và không nhập dữ liệu cá nhân"),
    (("nghien cuu", "bao cao", "thuyet trinh", "de tai", "so lieu khao sat", "phan tich so lieu",
      "bai luan", "dan chung"),
     ("1.3", "3.3"),
     "Thu thập, chọn lọc và trích dẫn tư liệu phục vụ bài nghiên cứu/ báo cáo",
     "Danh mục tài liệu tham khảo kèm trích dẫn trong bài",
     "Trích dẫn đúng nguồn, phân biệt được dữ liệu tự thu thập và nguồn có sẵn"),
    (("an ninh mang", "ma hoa", "du lieu ca nhan", "quyen rieng tu", "dao duc so",
      "vi pham ban quyen"),
     ("4.2", "2.6"),
     "Phân tích tình huống đạo đức số và trách nhiệm công dân số",
     "Bài viết ngắn/bảng phân tích tình huống",
     "Lập luận được hậu quả và trách nhiệm của người sử dụng công nghệ"),
]

# Bảng dùng theo cấp học
BO_THEO_CAP = {
    "tieu_hoc": NGU_CANH_TIEU_HOC + NGU_CANH_CHUNG + NGU_CANH_THPT,
    "thcs": NGU_CANH_CHUNG + NGU_CANH_THPT + NGU_CANH_TIEU_HOC,
    "thpt": NGU_CANH_THPT + NGU_CANH_CHUNG,
}
# giữ tên cũ cho phần code đang dùng
NGU_CANH = NGU_CANH_CHUNG

_DON_VI = ("lop", "bai", "phan", "chuong", "tiet", "tuan", "muc", "hoat", "dong", "noi", "dung",
           "va", "cua", "trong", "giua", "tren", "duoi", "theo", "cho", "voi", "khi", "de",
           "thi", "hoc", "sinh", "giao", "vien", "khong", "co", "tao", "su", "dung", "lam",
           "nhu", "cung", "nhung", "cac", "gi", "nao", "ra", "vao", "tu", "den")


def _khop(van_ban_bo_dau, cum):
    """Khớp cụm từ theo ranh giới từ (tránh khớp chuỗi con)."""
    import re as _re
    return _re.search(r"(?<![a-z0-9])" + _re.escape(cum) + r"(?![a-z0-9])", van_ban_bo_dau) is not None


def cap_hoc(lop):
    """1–5: tiểu học; 6–9: THCS; 10–12: THPT; chưa rõ thì để trống."""
    try:
        n = int(str(lop or "").strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= n <= 5:
        return "tieu_hoc"
    if 6 <= n <= 9:
        return "thcs"
    if 10 <= n <= 12:
        return "thpt"
    return ""


TEN_CAP = {"tieu_hoc": "tiểu học", "thcs": "THCS", "thpt": "THPT"}


def _hoat_dong_theo_ma(ma):
    """Tên hoạt động / sản phẩm / minh chứng theo THÀNH PHẦN của một mã chỉ báo.

    Dùng khi giáo viên tự chọn mã ở bước duyệt: vẫn lấy đúng hoạt động thật trong bảng
    ngữ cảnh (không ghép câu kiểu “hoạt động gắn với chỉ báo …”).
    """
    comp = ".".join(str(ma).split(".")[:2])
    for bang in list(BO_THEO_CAP.values()) + [NGU_CANH_CHUNG, NGU_CANH_THPT]:
        for _tk, comps, ten_hd, san_pham, minh_chung in bang:
            if comp in comps:
                return ten_hd, san_pham, minh_chung
    return "", "", ""


def _chon_tu_bang(van_ban, bang, level, toi_da):
    """Chọn tiêu chí từ một bảng ngữ cảnh, ưu tiên cụm từ khoá dài (đặc thù hơn)."""
    ung_vien = []
    for tu_khoa, comps, ten_hd, san_pham, minh_chung in bang:
        khop = [k for k in tu_khoa if _khop(van_ban, k)]
        if not khop:
            continue
        do_dac_thu = max(len(k) for k in khop)
        ung_vien.append((do_dac_thu, comps, ten_hd, san_pham, minh_chung, max(khop, key=len)))
    ung_vien.sort(key=lambda x: -x[0])

    ra, da_dung = [], set()
    for _dac_thu, comps, ten_hd, san_pham, minh_chung, tu_khoa in ung_vien:
        if len(ra) >= toi_da:
            break
        for c in comps:
            if len(ra) >= toi_da:
                break
            for cb in nld.tra_theo_thanh_phan(c, level):
                if cb["code"] in da_dung:
                    continue
                da_dung.add(cb["code"])
                ra.append({"chi_bao": cb, "ten_hoat_dong": ten_hd, "san_pham": san_pham,
                           "minh_chung": minh_chung, "tu_khoa_khop": tu_khoa})
                break
    return ra



def lay_ten_bai(doc):
    """Tìm tên bài dạy trong giáo án."""
    mau = re.compile(r"^\s*(?:tên\s*bài(?:\s*dạy)?|bài(?:\s*số)?\s*[:：]?|tiêu\s*đề)\s*[:：]?\s*(.+)$", re.I)
    for p in doc.paragraphs[:40]:
        m = mau.match(gon(p.text))
        if m and len(gon(m.group(1))) >= 3:
            return gon(m.group(1))[:200]
    return ""


RE_HEAD_THIET_BI = re.compile(
    r"^\s*[ivx\d]+\s*[.)]?\s*(thiet\s*bi|do\s*dung|hoc\s*lieu|chuan\s*bi)", re.I)
RE_HEAD_KHAC = re.compile(r"^\s*(?:[ivx]+|\d+)\s*[.)]\s*\S", re.I)


def noi_dung_bai(doc, bo_thiet_bi=True):
    """Gom văn bản đầu tài liệu để dò chủ đề bài học.

    Mặc định BỎ phần liệt kê thiết bị/đồ dùng dạy học: đó là danh mục phương tiện,
    nếu tính vào thì bài nào cũng khớp “máy chiếu, tranh ảnh” và tiêu chí chọn ra
    không còn phản ánh nội dung bài. Điều kiện thiết bị được hỏi riêng ở biểu mẫu.
    """
    doan = [gon(p.text) for p in doc.paragraphs[:60]]
    if bo_thiet_bi:
        giu, dang_bo = [], False
        for t in doan:
            if RE_HEAD_THIET_BI.match(khong_dau(t)):
                dang_bo = True
                continue
            if dang_bo:
                if RE_HEAD_KHAC.match(t):
                    dang_bo = False
                else:
                    continue
            giu.append(t)
        doan = giu
    phan = list(doan)
    for tb in doc.tables[:2]:
        for r in tb.rows[:6]:
            phan.append(" ".join(gon(c.text) for c in r.cells))
    return khong_dau(" ".join(phan))


# ------------------------------------------------------------------ chọn tiêu chí
# Gợi ý theo cấp học khi bài KHÔNG có hoạt động số nào để đối chiếu.
GOI_Y_CAN_DUYET = {
    "tieu_hoc": [("4.1", "Nhận biết thiết bị số có trong lớp và cách giữ an toàn khi dùng",
                  "Nêu tên thiết bị số của lớp và một việc cần làm để giữ an toàn",
                  "Học sinh chỉ được thiết bị và nói đúng một quy tắc an toàn"),
                 ("3.1", "Quan sát một sản phẩm số đơn giản do giáo viên chuẩn bị",
                  "Câu trả lời của học sinh về sản phẩm số đã xem",
                  "Nói được sản phẩm số đó dùng để làm gì")],
    "thcs": [("4.1", "Nhận diện thiết bị số dùng trong bài và thao tác đúng cách",
              "Bảng kiểm thao tác an toàn của nhóm",
              "Thao tác đúng quy trình và nêu cách xử lý một lỗi đơn giản"),
             ("3.1", "Tạo một sản phẩm số đơn giản minh hoạ nội dung bài",
              "Sản phẩm số của nhóm (sơ đồ, ảnh, đoạn văn bản)",
              "Sản phẩm bám nội dung bài và có ghi nguồn tư liệu dùng")],
    "thpt": [("1.3", "Quản lý tệp và dữ liệu học tập của bài trên máy tính/điện thoại",
              "Thư mục sản phẩm của cá nhân, đặt tên theo quy ước",
              "Mở lại được sản phẩm đúng tên, đúng vị trí"),
             ("2.4", "Phối hợp làm việc nhóm bằng công cụ số",
              "Biên bản phân công và phần đóng góp của từng thành viên",
              "Nêu được việc mình làm và việc nhóm cùng làm")],
}


def goi_y_can_duyet(level, cap, thiet_bi="co", toi_da=2):
    """Trả các gợi ý ở trạng thái “cần giáo viên duyệt” cho bài chưa có dấu hiệu số.

    Không gán tràn lan: mỗi gợi ý đều ghi rõ `can_duyet: True` để giao diện và
    báo cáo hiển thị đúng là đề xuất chưa có căn cứ trong bài.
    """
    ra = []
    for comp, ten_hd, san_pham, minh_chung in GOI_Y_CAN_DUYET.get(cap or "", []):
        if len(ra) >= toi_da:
            break
        for cb in nld.tra_theo_thanh_phan(comp, level):
            ra.append({"chi_bao": cb, "ten_hoat_dong": ten_hd, "san_pham": san_pham,
                       "minh_chung": minh_chung, "tu_khoa_khop": "chưa có trong bài",
                       "can_duyet": True, "cap_hoc": cap})
            break
    return ra


def chon_tieu_chi(doc, pt, thiet_bi="", toi_da=3, chon_ma=None):
    """Chọn tiêu chí phù hợp từ kho. Trả về (danh sách, cảnh báo).

    Chỉ lấy mã có trong kho ứng với đúng mức độ của lớp. Không gán tràn lan:
    tối đa `toi_da` tiêu chí, ưu tiên theo mức độ khớp nội dung bài.
    """
    canh_bao = []
    lop = str(pt.get("lop") or "").strip()
    level = nld.muc_do_theo_lop(lop) if lop else ""
    if not level:
        return [], ["Chưa xác định được lớp của giáo án nên không xác định được mức độ "
                    "năng lực số. Hãy ghi rõ “Lớp: …” trong giáo án hoặc chọn lớp trước khi chạy."]

    # Nếu giáo viên đã tự chọn mã ở bước duyệt: chỉ dùng đúng các mã đó,
    # vẫn kiểm tra mã có thật trong kho và đúng mức của lớp.
    if chon_ma:
        ra, canh_bao2 = [], []
        for ma in chon_ma:
            cb = nld.tra_ma(ma)
            if not cb:
                canh_bao2.append(f"Mã “{ma}” không có trong kho tra cứu — đã bỏ qua.")
                continue
            if level and cb.get("level") != level:
                canh_bao2.append(f"Mã “{ma}” thuộc mức {cb.get('level')}, không đúng mức "
                                 f"{level} của lớp {lop} — đã bỏ qua.")
                continue
            _hd, _sp, _mc = _hoat_dong_theo_ma(ma)
            ra.append({"chi_bao": cb,
                       "ten_hoat_dong": _hd or ("Thực hiện nhiệm vụ học tập có sử dụng thiết bị số, "
                                                "học liệu số theo hướng dẫn của giáo viên"),
                       "san_pham": _sp or "Sản phẩm học tập của học sinh (phiếu học tập/bản trình bày).",
                       "minh_chung": _mc or "Kết quả nhiệm vụ của học sinh trong hoạt động.",
                       "tu_khoa_khop": "giáo viên tự chọn"})
        return ra, canh_bao + canh_bao2

    van_ban = noi_dung_bai(doc)
    if thiet_bi == "khong_co":
        canh_bao.append("Lớp không có thiết bị số tại chỗ: hoạt động được thiết kế theo "
                        "phương án thay thế (phiếu giấy/thiết bị của giáo viên), "
                        "giáo viên cần duyệt lại.")

    van_ban_nd = noi_dung_bai(doc)
    bang = BO_THEO_CAP.get(cap_hoc(lop), NGU_CANH_CHUNG)
    ra = _chon_tu_bang(van_ban_nd, bang, level, toi_da)
    for x in ra:
        x["cap_hoc"] = cap_hoc(lop)

    if not ra:
        ra = goi_y_can_duyet(level, cap_hoc(lop), thiet_bi, toi_da=min(2, toi_da))
        if ra:
            canh_bao.append("Bài này không nêu hoạt động số nào, nên hệ thống KHÔNG tự gán tiêu chí. "
                            "Các gợi ý dưới đây ở trạng thái “cần giáo viên duyệt”: chỉ giữ lại "
                            "nếu thầy/cô thật sự tổ chức hoạt động đó trong tiết học.")
        else:
            canh_bao.append("Không tìm thấy tiêu chí nào thật sự phù hợp với nội dung bài. "
                            "Hãy bổ sung mô tả nội dung/hoạt động của bài rồi chạy lại, "
                            "hoặc tự chọn mã trong kho tra cứu.")
    if cap := cap_hoc(lop):
        canh_bao.append(f"Đã đối chiếu theo chương trình {TEN_CAP[cap]} (lớp {lop}, mức {level}).")
    return ra, canh_bao


def soan_muc_tieu(ten_bai, lop, mon, chon):
    """Soạn các dòng cho mục 'Tích hợp năng lực số' trong phần MỤC TIÊU.

    Chỉ nêu mã tiêu chí, mục tiêu và minh chứng — KHÔNG đưa khối “[QUY ĐỊNH]/[ĐỀ XUẤT]”
    vào tài liệu; nguồn văn bản ghi ngắn ngay trên dòng tiêu chí.
    """
    dong = []
    for i, x in enumerate(chon, 1):
        cb = x["chi_bao"]
        if x.get("can_duyet"):
            dong.append((f"{i}. Tiêu chí {cb['code']} — “cần giáo viên duyệt”: bài học chưa có "
                         f"hoạt động số để đối chiếu.", "can_duyet"))
        # Chỉ ghi mã + miền + tên tiêu chí; KHÔNG ghi mức/L1-L2-L3/nguồn và không ghi
        # dòng “Minh chứng đánh giá” (theo yêu cầu của giáo viên: giữ mục gọn, dễ đọc).
        dong.append((f"{i}. Tiêu chí {cb['code']} — {cb['domain']} — {cb['name']}", "tieuchi"))
        muc_tieu = (f"Học sinh {_rut_gon(cb['verbatim'])} gắn với nội dung “{ten_bai or 'bài học'}” "
                    f"môn {mon or '…'} lớp {lop or '…'}."
                    if ten_bai else
                    f"Học sinh vận dụng tiêu chí {cb['code']} vào nội dung bài học.")
        if x.get("can_duyet"):
            dong.append(("   · CẦN GIÁO VIÊN DUYỆT — bài chưa nêu hoạt động số nào; "
                         "chỉ giữ nếu thầy/cô thật sự tổ chức hoạt động này.", "can_duyet"))
        dong.append((f"   · Mục tiêu: {muc_tieu}", "dexuat"))
    return dong


def _rut_gon(nguyen_van):
    """Chuyển nguyên văn tiêu chí thành cụm mở đầu cho mục tiêu, không đổi ý nghĩa."""
    t = nguyen_van.strip()
    t = t[0].lower() + t[1:] if t else t
    return t.rstrip(".") + ","


def soan_hoat_dong(ten_bai, lop, mon, chon, thoi_luong=6, thiet_bi="co"):
    """Soạn hoạt động tích hợp để chèn vào tiến trình bài dạy."""
    if not chon:
        return None
    ma = ", ".join(x["chi_bao"]["code"] for x in chon)
    # Thiết kế hoạt động chỉ ghi HOẠT ĐỘNG (việc học sinh làm), không ghi chi tiết năng lực
    # như “1.1.CB1a”, “3.1.CB1a” — mã tiêu chí đã nêu ở mục “Tích hợp năng lực số”.
    ten = "Hoạt động tích hợp năng lực số"
    muc_tieu = "; ".join(dict.fromkeys(x["ten_hoat_dong"] for x in chon))
    return {
        "ten": ten,
        "muc_tieu": muc_tieu,
        "ma": ma,
        "thoi_luong": thoi_luong,
        "gv": _gv(chon, thiet_bi, lop),
        "hs": _hs(chon, thiet_bi, lop),
        "cong_cu": _cong_cu(chon, thiet_bi, lop),
        "cac_buoc": _cac_buoc(chon, thiet_bi, lop),
        "san_pham": "; ".join(dict.fromkeys(x["san_pham"] for x in chon)),
        "danh_gia": "; ".join(dict.fromkeys(x["minh_chung"] for x in chon)),
        "cap_hoc": _ten_cap(lop),
    }


def _ten_cap(lop):
    return TEN_CAP.get(cap_hoc(lop), "")


def _cong_cu(chon, thiet_bi, lop=""):
    can = set()
    for x in chon:
        can.add(x["chi_bao"]["component"].split(".")[0])
    cap = cap_hoc(lop)
    if thiet_bi == "khong_co":
        if cap == "tieu_hoc":
            return ("Không cần thiết bị cho học sinh: phiếu học tập giấy, tranh ảnh in sẵn, "
                    "bảng con; giáo viên dùng máy tính và máy chiếu của trường để minh hoạ chung.")
        return ("Phương án không cần thiết bị học sinh: phiếu học tập giấy, tranh ảnh in sẵn; "
                "giáo viên dùng máy tính và máy chiếu của trường để minh hoạ chung.")
    if "6" in can or "3" in can:
        return "Máy tính/điện thoại của giáo viên, máy chiếu; công cụ được chọn sẵn trước giờ học."
    if cap == "tieu_hoc":
        return ("Thiết bị do giáo viên chuẩn bị và điều khiển (máy tính, máy chiếu, máy tính bảng); "
                "học sinh không tự đăng nhập tài khoản.")
    return "Máy tính hoặc điện thoại có kết nối; phần mềm/ứng dụng giáo viên đã chọn trước."


def _gv(chon, thiet_bi, lop=""):
    cap = cap_hoc(lop)
    ra = ["Nêu nhiệm vụ và tiêu chí đánh giá trước khi học sinh làm.",
          "Chọn sẵn công cụ số và kiểm tra hoạt động được trước giờ học."]
    if cap == "tieu_hoc":
        ra = ["Nêu nhiệm vụ bằng lời ngắn gọn, làm mẫu từng bước trên máy chiếu cho cả lớp xem.",
              "Chọn sẵn học liệu số (tranh ảnh, video, phần mềm) và kiểm tra trước giờ học.",
              "Điều khiển thiết bị hoặc chia theo bàn; không để học sinh tự đăng nhập tài khoản."]
    if thiet_bi == "khong_co":
        ra.append("Chuẩn bị phiếu giấy thay thế cho lớp không có thiết bị.")
    ra.append("Quan sát, nhắc học sinh ghi lại nguồn và không nhập dữ liệu cá nhân.")
    ra.append("Chốt lại phần đã làm được và phần còn cần điều chỉnh.")
    return " ".join(ra)


def _hs(chon, thiet_bi, lop=""):
    cap = cap_hoc(lop)
    if thiet_bi == "khong_co":
        if cap == "tieu_hoc":
            return ("Quan sát phần giáo viên làm mẫu, làm nhiệm vụ trên phiếu học tập hoặc bảng con; "
                    "nói lại kết quả cho cô/thầy và các bạn nghe.")
        return ("Thực hiện nhiệm vụ trên phiếu học tập; quan sát phần minh hoạ của giáo viên; "
                "trình bày kết quả trước lớp.")
    if cap == "tieu_hoc":
        return ("Quan sát giáo viên làm mẫu, thực hiện theo từng bước với sự hướng dẫn; "
                "nói lại điều mình quan sát được và kết quả trước lớp.")
    if cap == "thpt":
        return ("Thực hiện nhiệm vụ theo nhóm hoặc cá nhân; ghi lại minh chứng và cách kiểm chứng "
                "kết quả; trình bày sản phẩm, phản biện phần làm của nhóm khác.")
    return ("Thực hiện nhiệm vụ theo nhóm hoặc cá nhân trên thiết bị; ghi lại kết quả; "
            "trình bày sản phẩm và nhận xét phần làm của nhóm khác.")


def _cac_buoc(chon, thiet_bi, lop=""):
    cap = cap_hoc(lop)
    if cap == "tieu_hoc":
        if thiet_bi == "khong_co":
            return ("1) Giáo viên cho cả lớp quan sát tranh/vật thật và nêu câu hỏi (1 phút). "
                    "2) Học sinh làm phiếu học tập hoặc bảng con (2 phút). "
                    "3) Một vài học sinh nói kết quả, cả lớp nghe và nhận xét (2 phút). "
                    "4) Giáo viên chốt lại điều cần nhớ (1 phút).")
        return ("1) Giáo viên làm mẫu trên máy chiếu, cả lớp quan sát (1 phút). "
                "2) Học sinh thực hiện theo từng bước cùng giáo viên (2 phút). "
                "3) Học sinh nói lại kết quả quan sát được (2 phút). "
                "4) Giáo viên chốt lại điều cần nhớ và nhắc quy tắc an toàn (1 phút).")
    if thiet_bi == "khong_co":
        return ("1) Giáo viên minh hoạ hoặc nêu tình huống (1 phút). "
                "2) Học sinh làm phiếu học tập theo yêu cầu (2 phút). "
                "3) Hai nhóm trình bày, cả lớp đối chiếu với tiêu chí (2 phút). "
                "4) Giáo viên chốt và liên hệ bài học (1 phút).")
    return ("1) Giáo viên nêu nhiệm vụ gắn với nội dung bài (1 phút). "
            "2) Học sinh thực hiện trên thiết bị theo nhóm (3 phút). "
            "3) Đại diện nhóm trình bày sản phẩm (1–2 phút). "
            "4) Cả lớp đối chiếu với tiêu chí và giáo viên chốt (1 phút).")


# ------------------------------------------------------------------ chèn vào Word
def _nhan_muc_tich_hop(mt, nl, doc):
    """Nhãn tiêu đề mục mới, hợp với cách đánh số mà giáo án đang dùng."""
    con = [str(x).lower() for x in (nl.get("cac_muc_con") or [])]
    chu = [x for x in con if len(x) == 1 and x.isalpha() and x not in ("i", "v")]
    if chu:                                   # đang dùng a, b, … -> tiếp là c
        cuoi = max(chu)
        if cuoi < "z":
            return f"{chr(ord(cuoi) + 1)}. Tích hợp năng lực số"
    if nl.get("cach_chen") == "cuoi_muc_tieu":   # không có mục Năng lực/Phẩm chất -> đánh số tiếp
        return f"{_so_tiep_theo(mt, doc)}. Tích hợp năng lực số"
    return "Tích hợp năng lực số"                 # nằm trong mục Năng lực, không thêm số


def chen_muc_tieu(doc, pt, chon, ten_bai="", mon=""):
    """Chèn mục 'Tích hợp năng lực số' vào CUỐI PHẦN NĂNG LỰC (trong MỤC TIÊU).

    Thứ tự ưu tiên vị trí:
      1. Ngay cuối mục con “Năng lực” — tức trước mục “Phẩm chất” (Công văn 5512 hay dùng).
      2. Nếu bài không có mục “Năng lực” nhưng có “Phẩm chất” → chèn ngay trước “Phẩm chất”.
      3. Không có cả hai → chèn cuối phần MỤC TIÊU như trước.
    Toàn bộ nội dung mới tô đỏ để giáo viên thấy ngay.
    """
    mt = pt["muc_tieu"]
    if not mt.get("co") or not chon:
        return {"da_chen": False, "ly_do": "Không có phần MỤC TIÊU hoặc không có tiêu chí nào."}

    nl = mt.get("nang_luc") or {}
    cach = nl.get("cach_chen") or "cuoi_muc_tieu"
    vi_tri_chen = int(nl.get("ket_thuc", mt["ket_thuc"]))
    vi_tri_chen = max(mt["vi_tri"] + 1, min(vi_tri_chen, len(doc.paragraphs)))

    so = _nhan_muc_tich_hop(mt, nl, doc)
    mau = doc.paragraphs[vi_tri_chen - 1] if vi_tri_chen > 0 else None
    neo = doc.paragraphs[vi_tri_chen - 1] if vi_tri_chen > 0 else None

    # chèn ngược từ dưới lên để giữ đúng thứ tự
    dong = soan_muc_tieu(ten_bai, pt.get("lop"), mon, chon)
    ds = [(f"{so}", "tieude")] + dong

    for text, loai in reversed(ds):
        p = doan_mau(doc, mau, text, do=True, in_dam=(loai == "tieude"), mau_chu=DO)
        if neo is not None:
            neo._p.addnext(p._p)     # đưa đoạn mới ra sau neo, giữ thứ tự

    _nhan = (mt.get("nhan") or "MỤC TIÊU")
    diem = {"trong_muc_nang_luc": f"cuối phần Năng lực (ngay trước mục Phẩm chất) trong “{_nhan}”",
            "truoc_pham_chat": f"ngay trước mục Phẩm chất trong “{_nhan}” "
                               f"(bài không có mục Năng lực riêng)",
            "cuoi_muc_tieu": f"cuối phần “{_nhan}”"}[cach]
    return {"da_chen": True, "so_muc": so, "so_tieu_chi": len(chon),
            "cach_chen": cach, "diem_chèn": diem,
            "trong_muc_nang_luc": cach == "trong_muc_nang_luc"}


def _so_tiep_theo(mt, doc):
    """Số thứ tự tiếp nối đúng kiểu đánh số đang dùng trong tài liệu."""
    kieu = mt.get("kieu_so") or ""
    if kieu == "I":
        so_la = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
        dem = 0
        for p in doc.paragraphs[max(0, mt["vi_tri"] - 12):mt["ket_thuc"]]:
            m = re.match(r"^\s*(?:PHẦN\s+)?([IVX]+)\s*[.)]", gon(p.text))
            if m and m.group(1) in so_la:
                dem = max(dem, so_la.index(m.group(1)) + 1)
        return so_la[dem] if dem < len(so_la) else "XI"
    if kieu == "A":
        return chr(ord("A") + len(mt.get("cac_muc_con") or []))
    return str(len(mt.get("cac_muc_con") or []) + 1)


# ------------------------------------------------------- GIÁO DỤC AI (QĐ 2422)
def _nhan_muc_ai(so_nld):
    """Nhãn tiêu đề mục AI: đứng ngay sau mục năng lực số (c. → d.)."""
    t = gon(so_nld or "")
    m = re.match(r"^\s*([a-z])\s*[.)]", t, re.I)
    if m:
        sau = chr(ord(m.group(1).lower()) + 1)
        if sau <= "z":
            return f"{sau}. {NHAN_AI_TIEU_DE}"
    return NHAN_AI_TIEU_DE


def soan_muc_tieu_ai(ten_bai, lop, mon, chon_ai):
    """Soạn các dòng cho mục “Tích hợp giáo dục trí tuệ nhân tạo (AI)”.

    Ghi TIÊU CHÍ theo mã yêu cầu cần đạt AI của đúng lớp (mã do văn bản QĐ 2422/QĐ-BGDĐT quy
    định — hệ thống KHÔNG tự đặt mã), kèm mạch/chủ đề, nội dung lớp, mục tiêu và minh chứng —
    song song với cách mục “Tích hợp năng lực số” ghi tiêu chí. Không đưa khối “[QUY ĐỊNH]/[ĐỀ XUẤT]” vào tài liệu.
    """
    dong = []
    for i, x in enumerate(chon_ai, 1):
        dx = x.get("de_xuat") or {}
        ds_ma = x.get("ma_goi_y") or []
        if ds_ma:
            # Ghi MÃ yêu cầu cần đạt AI của đúng lớp — giống cách mục năng lực số ghi mã
            # tiêu chí (mã do văn bản của Bộ quy định, hệ thống không tự đặt).
            _m0 = ds_ma[0]
            dong.append((f"{i}. Tiêu chí {_m0['ma']} — {_m0.get('mach_ten', x['ten_mach'])} "
                         f"({(x.get('ten_cap') or '').lower()}, lớp {lop or '…'}) — "
                         f"“{_m0['yccd'].rstrip('.')}”"
                         f"{' (nội dung mở rộng)' if _m0.get('mo_rong') else ''}", "tieuchi"))
            for _m in ds_ma[1:]:
                dong.append((f"   · Tiêu chí {_m['ma']} — {_m.get('chu_de_ten', '')} — "
                             f"“{_m['yccd'].rstrip('.')}”"
                             f"{' (nội dung mở rộng)' if _m.get('mo_rong') else ''}", "tieuchi"))
        else:
            # Không có mã nào sát bài: KHÔNG tự đặt mã — ghi rõ để giáo viên tự chọn.
            dong.append((f"{i}. Mạch “{x['ten_mach']}” — {x.get('ten_cap', '')}, "
                         f"lớp {lop or '…'} (chưa có mã nào trong kho sát bài này — "
                         f"thầy/cô tự chọn mã của lớp {lop or '…'})", "tieuchi"))
        if x.get("can_duyet"):
            dong.append(("   · CẦN GIÁO VIÊN DUYỆT — bài học chưa nêu hoạt động nào liên quan "
                         "tới AI; chỉ giữ nếu thầy/cô thật sự tổ chức hoạt động này.", "can_duyet"))
        if x.get("noi_dung_theo_lop"):
            dong.append((f"   · Nội dung lớp {lop}: {x['noi_dung_theo_lop']}", "dexuat"))
        if dx.get("muc_tieu"):
            dong.append((f"   · Mục tiêu: {dx['muc_tieu']}", "dexuat"))
        if dx.get("minh_chung"):
            _mc = dx["minh_chung"].rstrip()
            if _mc[-1:] not in ".!?…:":
                _mc += "."
            dong.append((f"   · Minh chứng đánh giá: {_mc}", "dexuat"))
        # KHÔNG ghi dòng “Căn cứ chọn mạch: …” và dòng “Nguồn: …” trong file Word
        # (nguồn văn bản vẫn hiển thị ở trang duyệt trên web và ở tên dòng hoạt động AI).
    return dong


def _het_toan_do(p):
    """Đoạn do hệ thống chèn: mọi run có chữ đều đỏ FF0000 (năng lực số) hoặc xanh dương
    0000FF (giáo dục AI) — dùng để nhận diện khối nội dung mới, không phải nội dung gốc."""
    chu = [r for r in p.runs if (r.text or "").strip()]
    return bool(chu) and all(r.font.color is not None and r.font.color.rgb in MAU_MOI for r in chu)


def _neo_cuoi_muc_nld(doc):
    """Đoạn CUỐI của mục năng lực số đã chèn trong tài liệu (nếu có).

    Dùng neo thật trong file thay vì chỉ số đoạn, vì chèn mục năng lực số làm
    dịch chỉ số và số thứ tự mục con có thể khiến hệ thống đoán sai vị trí.
    """
    i = next((k for k, p in enumerate(doc.paragraphs) if la_tieu_de_nld(p.text)), None)
    if i is None:
        return None, ""
    cuoi = i
    for k in range(i + 1, len(doc.paragraphs)):
        p = doc.paragraphs[k]
        if (p.text or "").strip() and not _het_toan_do(p):
            break
        cuoi = k
    return doc.paragraphs[cuoi], doc.paragraphs[i].text


def chen_muc_ai(doc, pt, chon_ai, ten_bai="", mon="", so_nld="", thoi_luong=5):
    """Chèn mục “Tích hợp giáo dục trí tuệ nhân tạo (AI)” ngay SAU mục năng lực số,
    vẫn ở cuối phần Năng lực (trước mục Phẩm chất). Toàn bộ nội dung mới tô đỏ.
    """
    mt = pt["muc_tieu"]
    if not mt.get("co") or not chon_ai:
        return {"da_chen": False,
                "ly_do": "Không có phần mục tiêu hoặc không có nội dung giáo dục AI."}
    nl = mt.get("nang_luc") or {}
    cach = nl.get("cach_chen") or "cuoi_muc_tieu"
    vi_tri_chen = int(nl.get("ket_thuc", mt["ket_thuc"]))
    vi_tri_chen = max(mt["vi_tri"] + 1, min(vi_tri_chen, len(doc.paragraphs)))
    mau = doc.paragraphs[vi_tri_chen - 1] if vi_tri_chen > 0 else None
    # neo ưu tiên: đoạn cuối của mục năng lực số (nội dung AI đứng NGAY SAU mục đó)
    neo_nld, tieu_de_nld = _neo_cuoi_muc_nld(doc)
    if neo_nld is not None:
        neo, cach = neo_nld, "sau_muc_nld"
        diem = ("ngay sau toàn bộ nội dung mục năng lực số, cuối phần Năng lực "
                "(trước mục Phẩm chất)")
    else:
        neo = mau
        diem = "cuối phần Năng lực (trước mục Phẩm chất)"

    so = _nhan_muc_ai(so_nld or tieu_de_nld)
    ds = [(so, "tieude")] + soan_muc_tieu_ai(ten_bai, pt.get("lop"), mon, chon_ai)
    for text, loai in reversed(ds):
        p = doan_mau(doc, mau, text, do=True, in_dam=(loai == "tieude"), mau_chu=XANH)
        if neo is not None:
            neo._p.addnext(p._p)
    _nhan = (mt.get("nhan") or "MỤC TIÊU")
    return {"da_chen": True, "so_muc": so, "so_mach": len(chon_ai), "cach_chen": cach,
            "diem_chèn": f"{diem} trong “{_nhan}”"}


def _neo_khoi_hoat_dong(doc):
    """Đoạn cuối khối hoạt động hệ thống đã chèn (nếu có) — để chèn hoạt động AI sau đó."""
    cuoi = None
    for p in doc.paragraphs:
        if RE_HOAT_DONG_HE_THONG.match(gon(p.text) or ""):
            cuoi = p
    if cuoi is None:
        return None
    j = list(doc.paragraphs).index(cuoi)
    while j + 1 < len(doc.paragraphs):
        t = gon(doc.paragraphs[j + 1].text)
        if t and not RE_DONG_DO_HE_THONG.match(t):
            break
        j += 1
    return doc.paragraphs[j]


def _chen_doan_sau(doc, neo, hd, ghi_chu="", mau_chu=DO):
    dong = [
        (hd["ten"], "tieude"),
        (f"Mục tiêu: {hd['muc_tieu']}", "n"),
        (f"Thời lượng: {hd['thoi_luong']} phút", "n"),
        (f"Công cụ: {hd['cong_cu']}", "n"),
        (f"Các bước: {hd['cac_buoc']}", "n"),
        (f"Nhiệm vụ của giáo viên: {hd['gv']}", "n"),
        (f"Nhiệm vụ của học sinh: {hd['hs']}", "n"),
        (f"Sản phẩm học tập: {hd['san_pham']}", "n"),
        (f"Tiêu chí đánh giá: {hd['danh_gia']}", "n"),
        (f"({ghi_chu or NHAN_AI})", "ghichu"),
    ]
    for text, loai in reversed(dong):
        p = doan_mau(doc, neo, text, do=True, in_dam=(loai == "tieude"), mau_chu=mau_chu)
        neo._p.addnext(p._p)


def chen_hoat_dong_ai(doc, pt, hd):
    """Chèn hoạt động giáo dục AI vào tiến trình — ngay sau hoạt động năng lực số nếu có.

    Toàn bộ nội dung AI tô XANH DƯƠNG 0000FF (phân biệt với phần năng lực số tô đỏ FF0000).
    """
    tt = pt["tien_trinh"]
    if tt.get("kieu") == "bang":
        return _chen_vao_bang(doc, tt, hd, mau=None, neo_mau=RE_HOAT_DONG_BANG, mau_chu=XANH)
    neo = _neo_khoi_hoat_dong(doc)
    if neo is not None:
        _chen_doan_sau(doc, neo, hd, mau_chu=XANH)
        return {"da_chen": True, "kieu": "doan",
                "diem_chèn": "ngay sau khối hoạt động năng lực số"}
    if tt.get("kieu") == "doan" and tt.get("hoat_dong"):
        return _chen_sau_doan(doc, tt, hd, mau_chu=XANH)
    return _chen_duoi_muc_tieu(doc, pt, hd, mau_chu=XANH)


def chon_muc_ai(doc, pt, mach_chon=None, toi_da=2):
    """Chọn mạch nội dung giáo dục AI cho bài (dữ liệu có nguồn, xem ai_giao_duc)."""
    return AIGD.goi_y(pt.get("lop"), mon=pt.get("mon"), ten_bai=lay_ten_bai(doc),
                      van_ban=noi_dung_bai(doc), toi_da=toi_da, mach_chon=mach_chon)


def chen_hoat_dong(doc, pt, hd, mau=RE_HOAT_DONG_BANG, mau_chu=DO):
    """Chèn hoạt động vào đúng chỗ trong TIẾN TRÌNH BÀI DẠY, tô đỏ nội dung mới."""
    if not hd:
        return {"da_chen": False, "ly_do": "Chưa soạn được hoạt động."}
    tt = pt["tien_trinh"]

    if tt["kieu"] == "bang":
        return _chen_vao_bang(doc, tt, hd, mau=mau, mau_chu=mau_chu)
    if tt["kieu"] == "doan" and tt["hoat_dong"]:
        return _chen_sau_doan(doc, tt, hd, mau_chu=mau_chu)
    return _chen_duoi_muc_tieu(doc, pt, hd, mau_chu=mau_chu)


def _dong_gop(row):
    """Dòng có ô bị gộp (các ô trỏ về cùng một ô thật) hay không."""
    return len({id(c._tc) for c in row.cells}) < len(row.cells)


def _la_tieu_de_hoat_dong(row):
    """Dòng mở đầu một hoạt động lớn, ví dụ “4. VẬN DỤNG (5’)”.

    Loại trừ mục con “2.1.” bằng cách bắt buộc sau dấu chấm là ký tự KHÔNG phải số.
    """
    o_dau = gon(row.cells[0].text) if row.cells else ""
    return bool(re.match(r"^\s*\d+\.\s*(?!\d)\S", o_dau))


def _dong_mau_bang(table, tu_dong):
    """Chọn dòng làm mẫu để chèn: phải là dòng KHÔNG gộp ô.

    Giáo án thật hay gộp ô cho các dòng tiêu đề hoạt động (“4. VẬN DỤNG (5’)” trải rộng
    3 cột). Nếu chép nguyên dòng gộp rồi ghi nội dung vào từng cột thì mọi nội dung dồn
    vào một ô, hoạt động mới hiện sai chỗ.
    """
    n = len(table.rows)
    for d in range(0, n):
        for i in (tu_dong + d, tu_dong - d):
            if 0 <= i < n and not _dong_gop(table.rows[i]):
                return table.rows[i]
    return table.rows[tu_dong]


def _xoa_dong_bang(doc, tt, *mau):
    """Xoá các dòng do hệ thống chèn trong bảng tiến trình (theo từng loại dòng)."""
    if not mau or tt.get("kieu") != "bang":
        return 0
    table = doc.tables[tt["vi_tri"]]
    n = 0
    for row in list(table.rows):
        if any(any(m.match(khong_dau(gon(c.text)) or "") for m in mau) for c in row.cells):
            row._tr.getparent().remove(row._tr)
            n += 1
    return n


def _chen_vao_bang(doc, tt, hd, mau=RE_HOAT_DONG_BANG, neo_mau=None, mau_chu=DO):
    """Chèn một dòng hoạt động vào bảng tiến trình, sau hoạt động phù hợp nhất.

    Nếu lần chạy trước đã chèn dòng hoạt động tích hợp thì XOÁ dòng cũ trước khi chèn
    dòng mới — chạy lại nhiều lần không được làm bảng dài thêm.
    """
    table = doc.tables[tt["vi_tri"]]
    cot = tt["cot"]
    da_xoa = _xoa_dong_bang(doc, tt, mau) if mau else 0
    hang = table.rows
    if len(hang) < 2:
        return {"da_chen": False, "ly_do": "Bảng tiến trình chưa có dòng dữ liệu nào."}

    # NEO: chèn ngay sau dòng đã chỉ định (dùng khi ghép hoạt động AI ngay sau hoạt động
    # năng lực số), miễn là tìm thấy dòng đó trong bảng.
    if neo_mau is not None:
        for ri, row in enumerate(hang):
            if any(neo_mau.match(khong_dau(gon(c.text)) or "") for c in row.cells):
                mau_tr = row._tr
                moi_tr = copy.deepcopy(_dong_mau_bang(table, ri)._tr)
                mau_tr.addnext(moi_tr)
                from docx.table import _Row
                row_moi = _Row(moi_tr, table)
                da_ghi = set()
                for ci, cell in enumerate(row_moi.cells):
                    if id(cell._tc) in da_ghi:
                        continue
                    da_ghi.add(id(cell._tc))
                    _dat_o(cell, _noi_dung_o(ci, cot, hd), mau_chu=mau_chu)
                return {"da_chen": True, "kieu": "bang", "vi_tri_dong": ri + 1,
                        "da_thay_dong_cu": da_xoa, "so_dong": len(table.rows),
                        "diem_chèn": f"ngay sau dòng {ri} (hoạt động năng lực số) trong bảng tiến trình"}

    # chọn vị trí: ưu tiên hoạt động có nội dung khớp từ khoá;
    # nếu không khớp thì đặt trước dòng cuối (thường là vận dụng/tổng kết)
    vitri = None
    for ri in range(len(hang) - 1, 0, -1):
        noi = khong_dau(" ".join(gon(c.text) for c in hang[ri].cells))
        if any(k in noi for k in ("tim", "tra cuu", "thuc hanh", "luyen tap", "van dung",
                                  "hinh thanh", "kham pha")):
            vitri = ri
            break
    if vitri is None:
        vitri = len(hang) - 2 if len(hang) > 2 else 1
    vitri = max(1, vitri)

    # Không được cắt ngang khối hoạt động của giáo viên: nếu vị trí chọn được là DÒNG TIÊU ĐỀ
    # hoạt động ("4. VẬN DỤNG") thì phải chèn SAU toàn bộ nội dung của hoạt động đó.
    sau = vitri
    while sau + 1 < len(hang) and not _la_tieu_de_hoat_dong(hang[sau + 1]):
        sau += 1

    mau = _dong_mau_bang(table, sau)
    moi_tr = copy.deepcopy(mau._tr)
    hang[sau]._tr.addnext(moi_tr)
    from docx.table import _Row
    row = _Row(moi_tr, table)

    da_ghi = set()          # ô gộp: chỉ ghi một lần cho mỗi ô thật
    for ci, cell in enumerate(row.cells):
        if id(cell._tc) in da_ghi:
            continue
        da_ghi.add(id(cell._tc))
        _dat_o(cell, _noi_dung_o(ci, cot, hd), mau_chu=mau_chu)
    for ci, cell in enumerate(row.cells):
        if id(cell._tc) in da_ghi and ci not in (cot.get("ho_tro") or []):
            continue
    return {"da_chen": True, "kieu": "bang", "vi_tri_dong": sau, "da_thay_dong_cu": da_xoa,
            "so_dong": len(table.rows),
            "diem_chèn": f"sau dòng {sau} của bảng tiến trình (cuối hoạt động đã chọn)"}


def _noi_dung_o(ci, cot, hd):
    if cot.get("thoi_gian") == ci:
        return [f"{hd['thoi_luong']} phút"]
    if cot.get("hoat_dong") == ci:
        return [hd["ten"], f"Mục tiêu: {hd['muc_tieu']}"]
    if cot.get("gv") == ci:
        dong = [hd["gv"]]
        # Bảng không có cột "Hoạt động" riêng (ví dụ bảng GV | HS | Hỗ trợ HSKT):
        # ghi tên hoạt động ngay đầu cột GV, đúng như cách giáo án vẫn trình bày.
        if cot.get("hoat_dong") is None:
            dong = [hd["ten"], f"Mục tiêu: {hd['muc_tieu']}"] + dong
        return dong
    if cot.get("hs") == ci:
        return [hd["hs"]]
    if ci in (cot.get("ho_tro") or []):
        return ["Giáo viên quan sát, gợi ý thêm cho học sinh cần hỗ trợ."]
    return [hd["ten"]] if ci == 0 else [""]


def _dat_o(cell, dong, mau_chu=DO):
    """Ghi nội dung vào ô bảng, tô màu toàn bộ (đỏ: năng lực số, xanh dương: AI).

    Xoá nội dung mẫu chép từ dòng gốc trước khi ghi.
    """
    p = cell.paragraphs[0]
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    for i, t in enumerate(dong):
        if i == 0:
            run = p.add_run(t)
            run.font.color.rgb = mau_chu
        else:
            run = p.add_run("\n" + t)
            run.font.color.rgb = mau_chu
    for extra in cell.paragraphs[1:]:
        for r in list(extra.runs):
            r._r.getparent().remove(r._r)


def _chen_sau_doan(doc, tt, hd, mau_chu=DO):
    """Chèn hoạt động dạng đoạn văn, sau hoạt động phù hợp nhất."""
    ds = tt["hoat_dong"]
    chon_i = len(ds) - 1
    for i in range(len(ds) - 1, -1, -1):
        if any(k in khong_dau(ds[i]["ten"]) for k in ("luyen tap", "van dung", "thuc hanh")):
            chon_i = i
            break
    neo = doc.paragraphs[ds[chon_i]["vi_tri"]]
    mau = neo
    dong = [
        (hd["ten"], "tieude"),
        (f"Mục tiêu: {hd['muc_tieu']}", "n"),
        (f"Thời lượng: {hd['thoi_luong']} phút", "n"),
        (f"Công cụ: {hd['cong_cu']}", "n"),
        (f"Các bước: {hd['cac_buoc']}", "n"),
        (f"Nhiệm vụ của giáo viên: {hd['gv']}", "n"),
        (f"Nhiệm vụ của học sinh: {hd['hs']}", "n"),
        (f"Sản phẩm học tập: {hd['san_pham']}", "n"),
        (f"Tiêu chí đánh giá: {hd['danh_gia']}", "n"),
        (f"({NHAN_AI})", "ghichu"),
    ]
    # tìm cuối khối hoạt động để chèn sau
    cuoi = doc.paragraphs[-1]
    for j in range(ds[chon_i]["vi_tri"] + 1, len(doc.paragraphs)):
        if re.match(r"^\s*(?:hoạt\s*động|hoat\s*dong)\s*\d+", gon(doc.paragraphs[j].text), re.I):
            cuoi = doc.paragraphs[j - 1]
            break
        cuoi = doc.paragraphs[j]
    for text, loai in reversed(dong):
        p = doan_mau(doc, mau, text, do=True, in_dam=(loai == "tieude"), mau_chu=mau_chu)
        cuoi._p.addnext(p._p)
    return {"da_chen": True, "kieu": "doan", "diem_chèn": f"sau {ds[chon_i]['ten'][:50]}"}


def _chen_duoi_muc_tieu(doc, pt, hd, them_dong=None, mau_chu=DO):
    """Không có tiến trình nhận diện được: đặt hoạt động ngay sau phần MỤC TIÊU và báo rõ.

    Phân tích lại tài liệu tại đây vì mục “Tích hợp năng lực số” vừa được chèn vào
    GIỮA phần MỤC TIÊU, làm chỉ số đoạn phía sau dịch đi — dùng chỉ số cũ sẽ chèn sai.
    """
    pt = phan_tich(doc)
    neo = doc.paragraphs[min(pt["muc_tieu"].get("ket_thuc", len(doc.paragraphs)) - 1,
                             len(doc.paragraphs) - 1)]
    dong = [
        (hd["ten"], "tieude"),
        (f"Mục tiêu: {hd['muc_tieu']}", "n"),
        (f"Thời lượng: {hd['thoi_luong']} phút", "n"),
        (f"Công cụ: {hd['cong_cu']}", "n"),
        (f"Các bước: {hd['cac_buoc']}", "n"),
        (f"Nhiệm vụ của giáo viên: {hd['gv']}", "n"),
        (f"Nhiệm vụ của học sinh: {hd['hs']}", "n"),
        (f"Sản phẩm học tập: {hd['san_pham']}", "n"),
        (f"Tiêu chí đánh giá: {hd['danh_gia']}", "n"),
        (f"({NHAN_AI} Không nhận diện được phần TIẾN TRÌNH BÀI DẠY nên hoạt động được đặt ngay "
         f"sau phần “{pt['muc_tieu'].get('nhan') or 'MỤC TIÊU'}” — "
         f"giáo viên vui lòng chuyển vào đúng vị trí.)", "ghichu"),
    ]
    for text, loai in reversed(dong):
        p = doan_mau(doc, neo, text, do=True, in_dam=(loai == "tieude"), mau_chu=mau_chu)
        neo._p.addnext(p._p)
    return {"da_chen": True, "kieu": "du_phong",
            "diem_chèn": "ngay sau phần MỤC TIÊU (cần giáo viên chuyển vào tiến trình)"}


# ------------------------------------------------------------------ kiểm tra đầu ra
def kiem_tra_dau_ra(doc, pt, chon, ket_qua, goc_doan=None):
    """Bộ kiểm tra có cấu trúc: xác thực mã, mức, nguồn, vị trí chèn, màu đỏ.

    Tách 2 mức:
      - `loi_cung`: sai mã/mức/nguồn, chèn trùng, tô đỏ nội dung gốc, không tô đỏ
        nội dung mới -> CHẶN xuất file, giáo viên phải sửa.
      - `canh_bao`: vấn đề cần giáo viên rà (thời lượng vượt tiết, hoạt động tạm
        chưa nằm trong tiến trình) -> vẫn xuất được nhưng hiển thị rõ.
    """
    loi, dat, cung, canh_bao = [], [], [], []

    # 1. mã dùng có thật trong kho, đúng mức của lớp
    level = nld.muc_do_theo_lop(pt.get("lop") or "")
    for x in chon:
        cb = x["chi_bao"]
        kq = nld.kiem_tra_ma(cb["code"])
        if not kq["hop_le"]:
            loi.append(f"Mã {cb['code']} không có trong kho: {kq['ly_do']}"); cung.append(loi[-1])
            continue
        if level and cb["level"] != level:
            loi.append(f"Mã {cb['code']} ở mức {cb['level']} nhưng lớp {pt.get('lop')} "
                       f"cần mức {level}."); cung.append(loi[-1])
            continue
        if not cb.get("source") or not cb.get("source_location"):
            loi.append(f"Mã {cb['code']} thiếu nguồn hoặc vị trí nguồn."); cung.append(loi[-1])
            continue
        dat.append(f"Mã {cb['code']} hợp lệ, đúng mức {cb['level']}, có nguồn và vị trí.")

    # 2. đã chèn vào đúng chỗ chưa
    _chi_ai = bool(ket_qua.get("chi_ai"))
    if _chi_ai:
        if chon:
            loi.append("Giáo viên chọn chỉ chèn phần giáo dục AI nhưng hệ thống vẫn chọn "
                       "tiêu chí năng lực số — hãy bỏ tích các tiêu chí đó.")
            cung.append(loi[-1])
        dat.append("Giáo viên chọn chỉ chèn phần giáo dục AI: không chèn mục năng lực số.")
    elif ket_qua.get("muc_tieu", {}).get("da_chen"):
        dat.append("Đã chèn mục “Tích hợp năng lực số” ở %s."
                   % ket_qua["muc_tieu"].get("diem_chèn", "trong phần mục tiêu"))
    else:
        _ten_muc = (pt.get("muc_tieu") or {}).get("nhan") or "mục tiêu"
        loi.append(f"Chưa chèn được mục năng lực số vào phần “{_ten_muc}” ({ket_qua['muc_tieu'].get('ly_do', '')}).")
        cung.append(loi[-1])
    if not _chi_ai:
        if ket_qua.get("hoat_dong", {}).get("da_chen"):
            dat.append(f"Đã chèn hoạt động: {ket_qua['hoat_dong'].get('diem_chèn', '')}")
            if ket_qua["hoat_dong"].get("kieu") == "du_phong":
                loi.append("Hoạt động chưa nằm trong tiến trình bài dạy — cần giáo viên chuyển vào.")
        else:
            loi.append("Chưa chèn được hoạt động."); cung.append(loi[-1])

    # 2b. mục GIÁO DỤC AI (Quyết định 2422/QĐ-BGDĐT + Công văn 5588/BGDĐT-GDPT)
    kq_ai = (ket_qua or {}).get("ai") or {}
    if kq_ai.get("chon"):
        ai_mt = kq_ai.get("muc_tieu") or {}
        if ai_mt.get("da_chen"):
            dat.append("Đã chèn mục “Tích hợp giáo dục trí tuệ nhân tạo (AI)” ở %s."
                       % ai_mt.get("diem_chèn", "trong phần mục tiêu"))
        else:
            loi.append("Chưa chèn được mục giáo dục AI: %s." % ai_mt.get("ly_do", ""))
            cung.append(loi[-1])
        ai_hd = kq_ai.get("hoat_dong") or {}
        if ai_hd.get("da_chen"):
            dat.append(f"Đã chèn hoạt động giáo dục AI: {ai_hd.get('diem_chèn', '')}")
        else:
            loi.append("Chưa chèn được hoạt động giáo dục AI (hoạt động năng lực số vẫn giữ nguyên).")
        dem_ai = sum(1 for p in doc.paragraphs if la_tieu_de_ai(p.text))
        if dem_ai > 1:
            loi.append(f"Phát hiện {dem_ai} tiêu đề “Tích hợp giáo dục trí tuệ nhân tạo (AI)” "
                       f"— bị chèn trùng, cần xoá bớt.")
            cung.append(loi[-1])
        elif dem_ai == 1:
            dat.append("Mục giáo dục AI chèn đúng một lần.")
        # vị trí: SAU mục năng lực số và TRƯỚC mục Phẩm chất
        i_nld = next((i for i, p in enumerate(doc.paragraphs) if la_tieu_de_nld(p.text)), None)
        i_ai = next((i for i, p in enumerate(doc.paragraphs) if la_tieu_de_ai(p.text)), None)
        i_pc = next((i for i, p in enumerate(doc.paragraphs)
                     if re.match(r"^\s*(?:\d+|[ivx]+|[a-z])\s*[.)]?\s*pham chat",
                                 khong_dau(gon(p.text)))), None)
        if i_ai is not None and i_nld is not None and i_ai < i_nld:
            loi.append("Mục giáo dục AI bị đặt TRƯỚC mục năng lực số — sai thứ tự.")
            cung.append(loi[-1])
        if i_ai is not None and i_pc is not None and i_ai > i_pc:
            loi.append("Mục giáo dục AI bị đặt SAU mục Phẩm chất — sai vị trí.")
            cung.append(loi[-1])
        if i_ai is not None and (i_nld is None or i_ai > i_nld) and (i_pc is None or i_ai < i_pc):
            dat.append("Mục giáo dục AI nằm sau mục năng lực số và trước mục Phẩm chất."
                       if i_nld is not None else
                       "Mục giáo dục AI nằm ở cuối phần Năng lực, ngay trước mục Phẩm chất.")
        # mọi nội dung AI phải ghi rõ nguồn văn bản (không tự bịa căn cứ) — nguồn có thể nằm
        # ở dòng hoạt động AI trong bảng tiến trình hoặc ở phần mục tiêu
        _co_nguon = any("2422/QĐ-BGDĐT" in p.text for p in doc.paragraphs) or any(
            "2422/QĐ-BGDĐT" in c.text for t in doc.tables for r in t.rows for c in r.cells)
        if _co_nguon:
            dat.append("Nội dung giáo dục AI có ghi nguồn văn bản (Quyết định 2422/QĐ-BGDĐT) "
                       "và Công văn 5588/BGDĐT-GDPT ngay trong mục tiêu.")
        else:
            loi.append("Nội dung giáo dục AI thiếu ghi nguồn văn bản — không được xuất.")
            cung.append(loi[-1])

    # 2b2. mã yêu cầu cần đạt AI in trong mục phải CÓ THẬT, đúng lớp và đúng mạch đã chọn
    if kq_ai.get("chon"):
        _mau_ma_ai = re.compile(r"\b(\d{1,2})\.([A-D]\d)(?:\.(MR))?\.(\d+)\b")
        _blk_ai = []
        if i_ai is not None:
            for p in doc.paragraphs[i_ai:]:
                if p.text.strip() and not _het_toan_do(p):
                    break
                _blk_ai.append(p.text)
        _ma_trong_muc = []
        for _t in _blk_ai:
            for _m in _mau_ma_ai.finditer(_t):
                _m_full = _m.group(0)
                if _m_full not in _ma_trong_muc:
                    _ma_trong_muc.append(_m_full)
        _ma_mong_doi = [z["ma"] for x in (kq_ai.get("chon") or [])
                        for z in (x.get("ma_goi_y") or [])]
        for _m in _ma_trong_muc:
            _k = AIGD.tra_ma(_m)
            if not _k:
                loi.append(f"Mã giáo dục AI {_m} không có trong kho mã của văn bản — không được xuất.")
                cung.append(loi[-1])
                continue
            if str(_k.get("ma", "")).split(".")[0] != str(pt.get("lop") or "").strip():
                if str(pt.get("lop") or "").strip():
                    loi.append(f"Mã giáo dục AI {_m} không thuộc lớp {pt.get('lop')} — sai lớp.")
                    cung.append(loi[-1])
                    continue
            _mach_hop_le = {AIGD.MACH_SANG_MA.get(x.get("id")) for x in (kq_ai.get("chon") or [])}
            if _k.get("mach") not in _mach_hop_le:
                loi.append(f"Mã giáo dục AI {_m} không thuộc mạch nội dung nào đã chọn — sai mạch.")
                cung.append(loi[-1])
                continue
            dat.append(f"Mã giáo dục AI {_m} hợp lệ: có trong kho, đúng lớp "
                       f"{pt.get('lop')}, đúng mạch “{_k.get('mach_ten', '')}”.")
        if _ma_mong_doi and not _ma_trong_muc:
            loi.append("Mục giáo dục AI chưa ghi tiêu chí (mã yêu cầu cần đạt) nào dù kho có mã "
                       "của lớp — mục AI phải ghi tiêu chí như mục năng lực số.")
            cung.append(loi[-1])
        if _ma_trong_muc:
            dat.append(f"Mục giáo dục AI có ghi {len(_ma_trong_muc)} tiêu chí (mã yêu cầu cần đạt) "
                       f"của đúng lớp do Quyết định 2422/QĐ-BGDĐT quy định.")

    # 2c. thiết kế hoạt động chỉ ghi hoạt động, KHÔNG ghi mã chỉ báo trong dòng hoạt động
    _mau_ma = re.compile(r"\b\d\.\d\.(?:CB|TC|NC)\d[a-z]?\b")
    _dong_hd = [r for t in doc.tables for r in t.rows
                if any(("tích hợp năng lực số" in (c.text or "").lower()
                        or "tích hợp giáo dục ai" in (c.text or "").lower()) for c in r.cells)]
    for dong in _dong_hd:
        for o in dong.cells:
            if _mau_ma.search(o.text or "") or re.search(r"\b\d{1,2}\.[A-D]\d(?:\.MR)?\.\d+\b",
                                                         o.text or "", re.I):
                loi.append("Dòng hoạt động trong bảng còn ghi mã năng lực số — thiết kế hoạt động "
                           "chỉ ghi hoạt động, không ghi chi tiết năng lực.")
                cung.append(loi[-1])
                break
        else:
            continue
        break
    else:
        dat.append("Dòng hoạt động trong bảng chỉ ghi hoạt động, không ghi mã chỉ báo.")

    # 3. không chèn trùng mục (chỉ tính TIÊU ĐỀ mục, không tính câu có nhắc tới)
    dem = sum(1 for p in doc.paragraphs if la_tieu_de_nld(p.text))
    if _chi_ai:
        if dem:
            loi.append(f"Còn {dem} mục “Tích hợp năng lực số” trong file nhưng giáo viên chọn "
                       f"chỉ chèn phần giáo dục AI — hãy kiểm tra lại.")
    elif dem > 1:
        loi.append(f"Phát hiện {dem} tiêu đề “Tích hợp năng lực số” — bị chèn trùng, cần xoá bớt.")
        cung.append(loi[-1])
    else:
        dat.append("Không chèn trùng mục.")

    # 4. màu chỉ ở nội dung mới — đỏ cho năng lực số, xanh dương cho giáo dục AI
    do_moi, xanh_moi, tong = _dem_mau(doc)
    if do_moi + xanh_moi == 0:
        loi.append("Không tìm thấy nội dung mới nào được tô màu (đỏ/xanh)."); cung.append(loi[-1])
    else:
        dat.append(f"Có {do_moi} đoạn chữ đỏ FF0000 (năng lực số) và {xanh_moi} đoạn chữ "
                   f"xanh dương 0000FF (giáo dục AI) trên tổng {tong} đoạn.")
    if kq_ai.get("chon"):
        if xanh_moi:
            dat.append("Nội dung giáo dục AI được tô xanh dương 0000FF — phân biệt với phần "
                       "năng lực số tô đỏ FF0000.")
        else:
            loi.append("Nội dung giáo dục AI chưa được tô xanh dương — kiểm tra lại màu chèn.")
            cung.append(loi[-1])
    bi_do = _doan_goc_bi_to_do(doc, goc_doan)
    if bi_do:
        loi.append(f"Có {len(bi_do)} đoạn NỘI DUNG GỐC bị tô đỏ (ví dụ: “{bi_do[0][:50]}”).")
        cung.append(loi[-1])
    else:
        dat.append("Không đoạn nội dung gốc nào bị tô đỏ.")

    # 5. tổng thời lượng
    them = ((ket_qua.get("hoat_dong") or {}).get("thoi_luong", 0)
            + ((ket_qua.get("ai") or {}).get("hoat_dong") or {}).get("thoi_luong", 0))
    tong_phut = pt["thoi_luong"]["tong_phut"]
    if tong_phut:
        if tong_phut + them > 50:
            loi.append(f"Tổng thời lượng sau khi thêm là {tong_phut + them} phút, "
                       f"vượt 45 phút của một tiết. Hãy giảm thời lượng hoạt động mới "
                       f"hoặc lồng vào hoạt động có sẵn.")
        else:
            dat.append(f"Thời lượng hợp lý: {tong_phut} phút + {them} phút = {tong_phut + them} phút.")
    else:
        dat.append("Chưa đọc được tổng thời lượng bài học — giáo viên tự kiểm tra thời lượng.")

    for l in loi:
        if l not in canh_bao and l not in cung:
            canh_bao.append(l)
    return {"dat": dat, "loi": loi, "loi_cung": cung, "canh_bao": canh_bao,
            "so_loi": len(loi), "xuat_duoc": not cung,
            "ket_luan": ("Đạt kiểm tra" if not loi else
                         ("Cần giáo viên rà lại" if not cung else "Không đạt — phải sửa trước khi xuất"))}


def _doan_goc_bi_to_do(doc, goc_doan):
    """Đoạn vốn có trong giáo án gốc mà bị tô đỏ -> vi phạm yêu cầu.

    `goc_doan` có thể là danh sách chuỗi (lần chạy đầu) hoặc danh sách
    (chuỗi, vốn_đã_đỏ) — dạng thứ hai cần thiết khi tài liệu đưa vào đã có sẵn
    phần tô đỏ do lần chạy trước, nếu không sẽ bị báo lỗi oan.
    """
    if not goc_doan:
        return []
    goc, da_do_san = set(), set()
    for item in goc_doan:
        if isinstance(item, (list, tuple)):
            t, do_san = gon(item[0]), bool(item[1])
        else:
            t, do_san = gon(item), False
        if not t:
            continue
        goc.add(t)
        if do_san:
            da_do_san.add(t)
    ra = []
    for p in doc.paragraphs:
        t = gon(p.text)
        if not t or t not in goc or t in da_do_san:
            continue
        if any((r.font.color and r.font.color.rgb in MAU_MOI) for r in p.runs if r.font.color):
            ra.append(t)
    return ra


def trang_thai_mau_goc(doc):
    """Ghi lại từng đoạn và việc đoạn đó VỐN ĐÃ có chữ đỏ hay chưa.

    Dùng để lần chạy sau không báo oan phần đỏ do chính hệ thống tạo ra trước đó.
    """
    ra = []
    for p in doc.paragraphs:
        t = gon(p.text)
        if not t:
            continue
        do = any((r.font.color and r.font.color.rgb in MAU_MOI) for r in p.runs if r.font.color)
        ra.append([t, do])
    return ra


def _cac_doan_moi(doc):
    """Mọi đoạn văn cần soi màu: đoạn thân bài VÀ đoạn trong ô bảng.

    Không được chỉ soi doc.paragraphs: hoạt động mới được chèn vào BẢNG tiến trình,
    nếu bỏ qua bảng thì hệ thống tưởng "không có nội dung mới nào được tô đỏ"
    và chặn xuất file oan (đã gặp với giáo án tiểu học thật).
    """
    ds = list(doc.paragraphs)
    for t in doc.tables:
        for row in t.rows:
            for o in row.cells:
                ds.extend(o.paragraphs)
    # chữ trong hộp văn bản (textbox) — một số giáo án dùng mẫu có khung
    try:
        from docx.text.paragraph import Paragraph
        for box in doc.element.body.iter(qn("w:txbxContent")):
            for pel in box.iter(qn("w:p")):
                ds.append(Paragraph(pel, doc))
    except Exception:  # noqa: BLE001
        pass
    return ds


def _dem_mau(doc):
    """Đếm số đoạn có chữ đỏ (năng lực số), chữ xanh dương (giáo dục AI) và tổng số đoạn.

    Tính cả chữ trong bảng và trong hộp văn bản.
    """
    do_moi = xanh_moi = tong = 0
    for p in _cac_doan_moi(doc):
        co_do = co_xanh = False
        for r in p.runs:
            try:
                if r.font.color and r.font.color.rgb == DO:
                    co_do = True
                elif r.font.color and r.font.color.rgb == XANH:
                    co_xanh = True
            except (AttributeError, ValueError):
                pass
        if gon(p.text):
            tong += 1
        if co_do:
            do_moi += 1
        if co_xanh:
            xanh_moi += 1
    return do_moi, xanh_moi, tong


# ------------------------------------------------------------------ pipeline
def xu_ly(doc, thiet_bi="co", toi_da=3, thoi_luong=6, lop_ghi_de="", mon_ghi_de="",
          goc_doan=None, chon_ma=None, sua_chinh_ta=None, chon_ai=None, ai_thoi_luong=5,
          chi_ai=False):
    # chi_ai=True: giáo viên chọn CHỈ chèn phần giáo dục AI (không chèn mục năng lực số).
    # sua_chinh_ta: {"de_xuat": [...], "chon": [id, ...]} — chỉ áp dụng mục đã duyệt
    """Chạy trọn quy trình trên một tài liệu Word đã đọc sẵn.

    Trả về (doc đã chèn, báo cáo). Không ném lỗi cho giáo viên thấy thô;
    mọi bước đều ghi vào báo cáo để hiển thị ở trang duyệt.
    """
    bao_cao = {"buoc": [], "canh_bao": [], "chon": [], "ket_qua": {}}

    pt = phan_tich_an_toan(doc)
    bao_cao["canh_bao"].extend(pt.get("canh_bao", []))
    if lop_ghi_de:
        pt["lop"] = lop_ghi_de
    if mon_ghi_de:
        pt["mon"] = mon_ghi_de
    bao_cao["buoc"].append(
        f"Phân tích xong: {pt['so_doan']} đoạn, {pt['so_bang']} bảng; "
        f"môn “{pt['mon'] or 'chưa rõ'}”, lớp “{pt['lop'] or 'chưa rõ'}”; "
        f"tiến trình dạng {pt['tien_trinh']['kieu']}; "
        f"tổng thời lượng đọc được {pt['thoi_luong']['tong_phut'] or '?'} phút.")

    # xoá mục do lần chạy trước để không chèn trùng
    da_xoa = xoa_muc_nld_cu_an_toan(doc, pt)
    if da_xoa:
        bao_cao["buoc"].append(f"Đã xoá {da_xoa} đoạn của mục năng lực số do lần chạy trước "
                               "để tránh trùng nội dung.")
        pt = phan_tich_an_toan(doc)      # phân tích lại vì tài liệu đã đổi
        # PHẢI điền lại lớp/môn giáo viên đã chọn: nhiều giáo án thật không ghi “Lớp:” trong
        # văn bản, phân tích lại sẽ xoá mất lớp và hệ thống không chọn được tiêu chí nào.
        if lop_ghi_de:
            pt["lop"] = lop_ghi_de
        if mon_ghi_de:
            pt["mon"] = mon_ghi_de

    # dọn DÒNG HOẠT ĐỘNG do lần chạy trước (cả năng lực số lẫn giáo dục AI)
    if pt["tien_trinh"].get("kieu") == "bang":
        _xoa = _xoa_dong_bang(doc, pt["tien_trinh"], RE_HOAT_DONG_BANG, RE_HOAT_DONG_AI_BANG)
        if _xoa:
            bao_cao["buoc"].append(f"Đã xoá {_xoa} dòng hoạt động của lần chạy trước để không trùng.")

    ten_bai = lay_ten_bai(doc)
    if chi_ai:
        chon, canh_bao = [], []
        bao_cao["canh_bao"].append("Giáo viên chọn CHỈ chèn phần giáo dục AI cho bài này — "
                                   "hệ thống không chèn mục “Tích hợp năng lực số”.")
    else:
        chon, canh_bao = chon_tieu_chi(doc, pt, thiet_bi=thiet_bi, toi_da=toi_da,
                                       chon_ma=chon_ma)
        bao_cao["canh_bao"].extend(canh_bao)
    bao_cao["chon"] = [{"code": x["chi_bao"]["code"], "domain": x["chi_bao"]["domain"],
                        "name": x["chi_bao"]["name"], "level": x["chi_bao"]["level"],
                        "grades": x["chi_bao"]["grades"],
                        "verbatim": x["chi_bao"]["verbatim"],
                        "source": x["chi_bao"]["source"],
                        "source_location": x["chi_bao"]["source_location"],
                        "hoat_dong": x["ten_hoat_dong"], "san_pham": x["san_pham"],
                        "minh_chung": x["minh_chung"]} for x in chon]
    if not chon and not (chi_ai and chon_ai):
        bao_cao["thong_diep"] = ("Chưa chọn được tiêu chí nào. Cần bổ sung thông tin: "
                                 "lớp, môn, tên bài và nội dung chính của bài — hoặc tích "
                                 "“chỉ chèn phần giáo dục AI” và chọn ít nhất một mạch AI.")
        bao_cao["kiem_tra"] = {
            "xuat_duoc": False, "dat": [], "loi": list(canh_bao) or [bao_cao["thong_diep"]],
            "loi_cung": ["Chưa có nội dung nào để chèn: chưa chọn được tiêu chí năng lực số "
                         "và cũng chưa chọn mạch giáo dục AI nào."]}
        return doc, bao_cao

    if chon:
        kq_mt = chen_muc_tieu(doc, pt, chon, ten_bai=ten_bai, mon=pt["mon"])
        hd = soan_hoat_dong(ten_bai, pt["lop"], pt["mon"], chon,
                            thoi_luong=thoi_luong, thiet_bi=thiet_bi)
        kq_hd = chen_hoat_dong(doc, pt, hd, mau=None) if hd else {"da_chen": False}
        kq_hd["thoi_luong"] = thoi_luong if kq_hd.get("da_chen") else 0
    else:
        hd = None
        kq_mt = {"da_chen": False, "ly_do": "giáo viên chọn chỉ chèn phần giáo dục AI"}
        kq_hd = {"da_chen": False, "thoi_luong": 0,
                 "ly_do": "giáo viên chọn chỉ chèn phần giáo dục AI"}
    bao_cao["ket_qua"] = {"muc_tieu": kq_mt, "hoat_dong": kq_hd, "hoat_dong_chi_tiet": hd,
                          "chi_ai": bool(chi_ai)}
    bao_cao["buoc"].append("Đã chèn mục mục tiêu và hoạt động, tô đỏ toàn bộ nội dung mới."
                           if chon else
                           "Không chèn phần năng lực số (giáo viên chọn chỉ phần giáo dục AI).")

    # ---- GIÁO DỤC AI (Quyết định 2422/QĐ-BGDĐT + Công văn 5588/BGDĐT-GDPT) ----
    # Chèn NGAY SAU mục năng lực số, vẫn ở cuối phần Năng lực (trước mục Phẩm chất).
    kq_ai_mt = {"da_chen": False, "ly_do": "giáo viên không chọn nội dung giáo dục AI"}
    kq_ai_hd = {"da_chen": False}
    if chon_ai:
        pt_sau = phan_tich_an_toan(doc)      # chỉ số đoạn đã dịch sau khi chèn mục năng lực số
        kq_ai_mt = chen_muc_ai(doc, pt_sau, chon_ai, ten_bai=ten_bai, mon=pt["mon"],
                               so_nld=kq_mt.get("so_muc", ""), thoi_luong=ai_thoi_luong)
        pt_sau2 = phan_tich_an_toan(doc)     # mục AI vừa chèn lại dịch chỉ số đoạn phía sau
        hd_ai = AIGD.soan_hoat_dong(ten_bai, pt["lop"], pt["mon"], chon_ai,
                                    thoi_luong=ai_thoi_luong)
        kq_ai_hd = chen_hoat_dong_ai(doc, pt_sau2, hd_ai) if hd_ai else {"da_chen": False}
        kq_ai_hd["thoi_luong"] = ai_thoi_luong if kq_ai_hd.get("da_chen") else 0
        bao_cao["buoc"].append("Đã chèn mục “Tích hợp giáo dục trí tuệ nhân tạo (AI)” và hoạt động "
                               "lồng ghép theo Quyết định 2422/QĐ-BGDĐT — Công văn 5588/BGDĐT-GDPT.")
    bao_cao["ket_qua"]["ai"] = {"chon": [{"id": x["id"], "ten_mach": x["ten_mach"],
                                          "can_duyet": x["can_duyet"], "co_so": x["co_so"]}
                                         for x in (chon_ai or [])],
                                "muc_tieu": kq_ai_mt, "hoat_dong": kq_ai_hd,
                                "hoat_dong_chi_tiet": (AIGD.soan_hoat_dong(ten_bai, pt["lop"],
                                                                           pt["mon"], chon_ai,
                                                                           thoi_luong=ai_thoi_luong)
                                                       if chon_ai else None)}

    # Sửa chính tả: CHỈ áp dụng những đề xuất giáo viên đã tích chọn ở trang duyệt.
    if sua_chinh_ta:
        from . import chinh_ta_gd as CTG
        de_xuat = sua_chinh_ta.get("de_xuat") or []
        da_chon = sua_chinh_ta.get("chon") or []
        so_sua = CTG.ap_dung_vao_docx(doc, de_xuat, da_chon)
        bao_cao["so_sua_chinh_ta"] = so_sua
        bao_cao["buoc"].append(
            f"Đã áp dụng {so_sua}/{len(da_chon)} sửa chính tả do giáo viên duyệt "
            "(chữ đã sửa được tô đỏ, gạch chân)." if so_sua else
            "Không áp dụng sửa chính tả nào.")

    bao_cao["kiem_tra"] = kiem_tra_dau_ra(doc, pt, chon, bao_cao["ket_qua"], goc_doan=goc_doan)
    return doc, bao_cao


def phan_tich_an_toan(doc):
    """Gọi phan_tich nhưng không để lỗi bất ngờ làm hỏng cả lượt xử lý."""
    try:
        return phan_tich(doc)
    except Exception as exc:  # noqa: BLE001
        return {"muc_tieu": {"co": False}, "tien_trinh": {"kieu": "khong", "so_hoat_dong": 0,
                "hoat_dong": []}, "thoi_luong": {"tong_phut": 0, "nguon": []}, "lop": "", "mon": "",
                "so_doan": len(doc.paragraphs), "so_bang": len(doc.tables),
                "canh_bao": [f"Không phân tích được cấu trúc giáo án ({type(exc).__name__}). "
                             "Hãy kiểm tra lại file Word."]}


def xoa_muc_nld_cu_an_toan(doc, pt):
    try:
        return _xoa_muc_nld_cu(doc, pt["muc_tieu"])
    except Exception:  # noqa: BLE001
        return 0

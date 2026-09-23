"""Khung gợi ý tích hợp giáo dục STEM/STEAM vào PPCT và giáo án.

Căn cứ (không tự đặt hệ mã ngoài văn bản):
  · Công văn 909/BGDĐT-GDTH ngày 08/3/2023 — hướng dẫn tổ chức hoạt động
    giáo dục STEM trong giáo dục Tiểu học: 3 hình thức (bài học STEM,
    trải nghiệm STEM, làm quen nghiên cứu khoa học–kỹ thuật).
  · Công văn hướng dẫn nhiệm vụ GDPT (4555/BGDĐT-GDPT năm học 2025-2026;
    5208 năm học 2026-2027): đẩy mạnh STEM/STEAM, tổ chức thực chất,
    không theo phong trào, không nặng sản phẩm trình diễn.
  · Dự thảo Thông tư (8/2026) quy định tổ chức hoạt động giáo dục STEM
    trong giáo dục phổ thông: cùng 3 hình thức; hai quy trình (khám phá
    khoa học / thiết kế kỹ thuật); có thể tích hợp yếu tố nghệ thuật (STEAM);
    không phát sinh môn học mới, thời lượng, đầu điểm hay hồ sơ riêng.

STEM không có hệ mã tiêu chí như năng lực số / giáo dục AI. Cột PPCT chỉ ghi
MÃ HÌNH THỨC (STEM-BH, STEAM-BH, STEM-TN, STEM-NCKH). Diễn giải, sản phẩm
và 5 bước hiện trên trang rà soát / trong mục giáo án — không nhồi vào cột ghi chú.
"""
import re
import unicodedata

NGUON = ('Công văn 909/BGDĐT-GDTH ngày 08/3/2023; Công văn 4555/BGDĐT-GDPT '
         'và Công văn 5208/BGDĐT-GDPT (STEM/STEAM thực chất, không phong trào).')

# Mã hình thức — ngắn, ghi vào cột STEM của PPCT (giống cách NLS/AI chỉ ghi mã).
HINH_THUC = {
    'STEM-BH': 'Bài học STEM (tích hợp nội môn hoặc liên môn — hình thức chủ yếu)',
    'STEAM-BH': 'Bài học STEAM (STEM + yếu tố nghệ thuật/thiết kế thẩm mỹ)',
    'STEM-TN': 'Hoạt động trải nghiệm STEM (CLB, ngày hội, dự án — tự nguyện)',
    'STEM-NCKH': 'Làm quen nghiên cứu khoa học, kỹ thuật (học sinh có năng khiếu)',
}
QUY_TRINH = {
    'TKKT': 'Thiết kế kỹ thuật (xác định vấn đề → nghiên cứu kiến thức nền → '
            'chọn giải pháp → chế tạo/thử nghiệm → chia sẻ và cải tiến)',
    'KPKH': 'Khám phá khoa học (quan sát → nêu giả thuyết → thí nghiệm/thu thập '
            'số liệu → kết luận và giải thích)',
}

# Năm bước tiến trình bài học STEM (tài liệu tập huấn Bộ / quy trình 8 bước rút gọn 5 HĐ).
NAM_BUOC_TKKT = (
    'Xác định vấn đề thực tiễn và tiêu chí sản phẩm',
    'Nghiên cứu kiến thức nền, đề xuất vài phương án',
    'Chọn giải pháp và phác thảo thiết kế',
    'Chế tạo mẫu, thử nghiệm, ghi kết quả',
    'Trình bày, nhận xét, điều chỉnh thiết kế',
)
NAM_BUOC_KPKH = (
    'Quan sát hiện tượng / đặt câu hỏi',
    'Nêu giả thuyết có thể kiểm chứng',
    'Thiết kế và tiến hành thí nghiệm / đo',
    'Ghi số liệu, nhận xét, rút kết luận',
    'Chia sẻ kết quả và nêu việc làm lại cho chính xác hơn',
)


def _plain(text):
    t = unicodedata.normalize('NFD', (text or '').lower().replace('đ', 'd'))
    return ''.join(c for c in t if not unicodedata.combining(c))


def _khop(t, k):
    return bool(re.search(r'(?<![a-z0-9])' + re.escape(k) + r'(?![a-z0-9])', t))


# Mỗi nhóm: từ khoá tựa bài → hình thức, quy trình, lĩnh vực, sản phẩm, vật liệu sẵn có.
NHOM = [
    {'ten': 'Đo lường, thí nghiệm, quan sát khoa học',
     'tu_khoa': ['thi nghiem', 'do dai', 'do nhiet', 'nhiet do', 'quan sat', 'nang luong',
                 'khong khi', 'nuoc', 'dung dich', 'can nang', 'suc gio', 'thuc vat',
                 'dong vat', 'co the', 'thoi tiet', 'trai dat', 'mat troi', 'luc', 'ma sat',
                 'chuyen dong', 'van toc', 'dien', 'quang hoc', 'am thanh', 'phan ung',
                 'hoa hoc', 'kim loai', 'te bao', 'nam va vi khuan', 'suc khoe'],
     'ma': 'STEM-BH', 'quy_trinh': 'KPKH', 'linh_vuc': 'S-T-E-M',
     'lam_gi': 'Đo, thử, ghi số liệu, giải thích kết quả.',
     'san_pham': 'Bảng số liệu đo/thử và nhận xét của nhóm',
     'van_de': 'Vì sao kết quả các lần đo/thử có thể khác nhau? Làm sao đo cho tin cậy hơn?',
     'vat_lieu': 'thước, cốc, nước, giấy, bảng ghi — đồ dùng sẵn có của lớp'},
    {'ten': 'Thiết kế – chế tạo – thử nghiệm',
     'tu_khoa': ['thiet ke', 'che tao', 'mo hinh', 'lap rap', 'co cau', 'mach dien',
                 'robot', 'cong cu', 'do choi', 'xe', 'cau', 'nha', 'thuyen', 'may'],
     'ma': 'STEM-BH', 'quy_trinh': 'TKKT', 'linh_vuc': 'S-T-E-M',
     'lam_gi': 'Thiết kế – chế tạo mẫu – thử – cải tiến.',
     'san_pham': 'Mẫu thử (mô hình) đã được thử và cải tiến ít nhất một lần',
     'van_de': 'Làm thế nào tạo ra sản phẩm đáp ứng tiêu chí (bền / nhẹ / chạy được) từ vật liệu đơn giản?',
     'vat_lieu': 'giấy, bìa, ống hút, dây, keo, vật liệu tái chế — không phát sinh chi phí'},
    {'ten': 'Số liệu, biểu đồ, thống kê',
     'tu_khoa': ['so lieu', 'bieu do', 'thong ke', 'khao sat', 'thu thap', 'bang tinh',
                 'trung binh', 'phan tram', 'xac suat'],
     'ma': 'STEM-BH', 'quy_trinh': 'KPKH', 'linh_vuc': 'S-T-M',
     'lam_gi': 'Thu thập số liệu, vẽ biểu đồ, nhận xét.',
     'san_pham': 'Bảng số liệu và biểu đồ kèm nhận xét',
     'van_de': 'Thu thập số liệu thực tế rồi đọc kết quả bằng biểu đồ; nêu cách làm lại cho chính xác hơn.',
     'vat_lieu': 'phiếu khảo sát giấy, thước, bảng lớp; máy tính bảng (nếu có) không bắt buộc'},
    {'ten': 'Tạo hình, thẩm mỹ, thiết kế trực quan (STEAM)',
     'tu_khoa': ['ve tranh', 've hinh', 'trang tri', 'thu cong', 'tao hinh', 'poster',
                 'to roi', 'mau sac', 'gap hinh', 'cat dan', 'am nhac', 'hat', 'mua',
                 'kich', 'san khau', 'thiep', 'bo cuc'],
     'ma': 'STEAM-BH', 'quy_trinh': 'TKKT', 'linh_vuc': 'S-T-E-A-M',
     'lam_gi': 'Thiết kế sản phẩm tạo hình, thử vật liệu, chỉnh cho bền và đẹp.',
     'san_pham': 'Sản phẩm tạo hình đã thử vật liệu và chỉnh theo tiêu chí bền + thẩm mỹ',
     'van_de': 'Thiết kế sản phẩm trực quan gắn nội dung bài; kết hợp bố cục/hình học và thẩm mỹ.',
     'vat_lieu': 'giấy, bút màu, bìa, vật liệu tái chế sẵn có'},
    {'ten': 'Lập trình, thuật toán, mô phỏng',
     'tu_khoa': ['lap trinh', 'scratch', 'thuat toan', 'chuong trinh', 'mo phong',
                 'tung buoc', 'quy trinh', 'tu dong'],
     'ma': 'STEM-BH', 'quy_trinh': 'TKKT', 'linh_vuc': 'S-T-E-M',
     'lam_gi': 'Chia bước, chạy thử, sửa lỗi.',
     'san_pham': 'Chuỗi bước / chương trình chạy thử được, có ghi lỗi và cách sửa',
     'van_de': 'Chia nhiệm vụ thành các bước, thử, phát hiện lỗi và điều chỉnh.',
     'vat_lieu': 'phiếu quy trình giấy; máy tính/ Scratch nếu lớp có thiết bị'},
    {'ten': 'Môi trường, năng lượng, tái chế',
     'tu_khoa': ['tai che', 'moi truong', 'rac thai', 'tiet kiem', 'nang luong',
                 'trong cay', 'cay xanh', 'nuoc sach', 'khong khi'],
     'ma': 'STEM-BH', 'quy_trinh': 'TKKT', 'linh_vuc': 'S-T-E-M',
     'lam_gi': 'Làm sản phẩm tái chế/tiết kiệm từ đồ sẵn có, thử rồi cải tiến.',
     'san_pham': 'Mẫu giải pháp (dụng cụ/quy trình) tái chế hoặc tiết kiệm đã thử',
     'van_de': 'Làm sao giảm rác / tiết kiệm nước–điện ngay tại lớp, trường bằng vật liệu sẵn có?',
     'vat_lieu': 'chai nhựa, giấy vụn, thùng carton, cây, nước — ưu tiên đồ tái sử dụng'},
    {'ten': 'Toán hình học, đo đạc, diện tích',
     'tu_khoa': ['hinh hoc', 'dien tich', 'the tich', 'chu vi', 'hinh vuong', 'hinh chu nhat',
                 'hinh tron', 'goc', 'do dai', 'thang', 'khoi'],
     'ma': 'STEM-BH', 'quy_trinh': 'TKKT', 'linh_vuc': 'S-E-M',
     'lam_gi': 'Cắt/gấp mô hình đúng kích thước theo bài.',
     'san_pham': 'Mẫu cắt/gấp hoặc mô hình đúng kích thước theo tiêu chí đề bài',
     'van_de': 'Dùng kiến thức hình học vừa học để thiết kế một vật dụng đúng kích thước.',
     'vat_lieu': 'giấy kẻ ô, thước, kéo, bìa'},
    {'ten': 'Trải nghiệm, ngày hội, câu lạc bộ',
     'tu_khoa': ['ngay hoi', 'cau lac bo', 'trai nghiem', 'du an stem', 'ngoai khoa',
                 'tham quan', 'bao tang'],
     'ma': 'STEM-TN', 'quy_trinh': 'TKKT', 'linh_vuc': 'S-T-E-M',
     'lam_gi': 'Tổ chức trạm trải nghiệm bằng đồ dùng sẵn có.',
     'san_pham': 'Sản phẩm/trạm trải nghiệm của nhóm (tự nguyện, không bắt buộc đại trà)',
     'van_de': 'Tổ chức một trạm trải nghiệm gắn bài học, dùng đồ dùng sẵn có, không phát sinh đóng góp.',
     'vat_lieu': 'đồ dùng lớp + vật liệu địa phương; không bắt buộc phòng STEM riêng'},
    {'ten': 'Nghiên cứu khoa học, kỹ thuật',
     'tu_khoa': ['nghien cuu khoa hoc', 'de tai', 'du an nghien cuu', 'sang kien',
                 'khoa hoc ky thuat'],
     'ma': 'STEM-NCKH', 'quy_trinh': 'KPKH', 'linh_vuc': 'S-T-E-M',
     'san_pham': 'Đề cương đề tài / báo cáo ngắn của cá nhân hoặc nhóm',
     'van_de': 'Chọn một câu hỏi thật sát bài, thiết kế cách kiểm chứng bằng đo/thử đơn giản.',
     'vat_lieu': 'phiếu nghiên cứu, dụng cụ đo sẵn có; dành cho học sinh có năng khiếu'},
]


def _hits(title):
    t = _plain(title)
    ra = []
    for nhom in NHOM:
        khop = [k for k in nhom['tu_khoa'] if _khop(t, k)]
        if khop:
            ra.append((nhom, khop))
    ra.sort(key=lambda x: -max(len(k) for k in x[1]))
    return ra


def goi_y(ten_bai, lop='', mon=''):
    """Đọc tựa bài → một đề xuất STEM/STEAM (hoặc rỗng nếu chưa đủ căn cứ).

    Trả về dict: ma, hinh_thuc, quy_trinh, linh_vuc, san_pham, van_de, vat_lieu,
    nhom, khop, diem, ly_do, buoc. Không bịa mã ngoài bốn mã hình thức trên.
    """
    hits = _hits(ten_bai)
    if not hits:
        return {}
    nhom, khop = hits[0]
    ma = nhom['ma']
    qt = nhom['quy_trinh']
    diem = 4 + 3 * len(khop)
    if ma == 'STEAM-BH':
        diem += 2
    return {
        'ma': ma,
        'hinh_thuc': HINH_THUC[ma],
        'quy_trinh': qt,
        'quy_trinh_ten': QUY_TRINH[qt],
        'linh_vuc': nhom['linh_vuc'],
        'lam_gi': nhom['lam_gi'],
        'san_pham': nhom['san_pham'],
        'van_de': nhom['van_de'],
        'vat_lieu': nhom['vat_lieu'],
        'nhom': nhom['ten'],
        'khop': khop[:4],
        'diem': diem,
        'ly_do': ('Căn cứ tựa bài: có “%s” → nhóm “%s”, hình thức %s (%s).'
                  % ('”, “'.join(khop[:3]), nhom['ten'], ma, NGUON.split(';')[0])),
        'buoc': list(NAM_BUOC_KPKH if qt == 'KPKH' else NAM_BUOC_TKKT),
        'nguon': NGUON,
        'lop': str(lop or ''),
        'mon': mon or '',
        'ten_bai': (ten_bai or '')[:200],
    }


def soan_muc_tieu(dx, ten_bai='', lop='', mon=''):
    """Mục STEM/STEAM trong giáo án: một dòng — mã hình thức + việc làm."""
    if not dx:
        return []
    return [(f"{dx['ma']} — {dx.get('lam_gi') or dx.get('san_pham') or ''}", 'tieuchi')]


def soan_hoat_dong(dx, thoi_luong=8):
    """Hoạt động STEM/STEAM trong tiến trình: ghi ngắn việc học sinh làm."""
    if not dx:
        return None
    lam = dx.get('lam_gi') or dx.get('san_pham') or ''
    phut = max(5, min(12, int(thoi_luong or 8)))
    return {
        'ten': 'Hoạt động tích hợp giáo dục STEM/STEAM',
        'muc_tieu': lam,
        'ma': dx['ma'],
        'thoi_luong': phut,
        'cong_cu': dx.get('vat_lieu') or 'Đồ dùng sẵn có của lớp.',
        'cac_buoc': lam,
        'gv': 'Giao nhiệm vụ, quan sát, chốt.',
        'hs': lam,
        'san_pham': dx.get('san_pham') or lam,
        'danh_gia': 'Sản phẩm đã làm và lời giải thích ngắn.',
        'gan_vao': 'Hoạt động luyện tập / thực hành của bài',
        'ghi_chu_nguon': NGUON,
    }


def la_ma_hop_le(ma):
    return (ma or '').strip() in HINH_THUC

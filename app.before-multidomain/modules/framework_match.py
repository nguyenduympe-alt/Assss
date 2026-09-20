"""Local, auditable matching; not a generative AI model."""
import json
from functools import lru_cache
from pathlib import Path
from .digital_plan import plain


@lru_cache(maxsize=1)
def framework():
    return json.loads((Path(__file__).resolve().parents[1]/'assets/digital-framework.json').read_text(encoding='utf-8'))


# Exact teaching contexts constrain candidate competencies; unsupported subjects abstain.
CONTEXTS = [
    (('go ban phim','su dung ban phim','tu the ngoi'), ('4.3','4.1'), 'Thực hành tư thế, khoảng cách mắt và thao tác thiết bị; giáo viên quan sát theo bảng kiểm an toàn.'),
    (('phan cung','phan mem may tinh','bao quan may tinh'), ('4.1','5.1'), 'Nhận diện thiết bị, thao tác bảo quản; nêu cách xử lý một lỗi đơn giản với sự hướng dẫn của giáo viên.'),
    (('tim kiem thong tin','tim thong tin','tra cuu tren internet'), ('1.1','1.2'), 'Tìm thông tin phục vụ bài học, so sánh nguồn và ghi lại căn cứ lựa chọn; đánh giá qua kết quả tìm kiếm và nguồn trích dẫn.'),
    (('tep va thu muc','quan ly tep','luu tru du lieu','sap xep tep'), ('1.3',), 'Tạo, đặt tên, sắp xếp và mở lại tệp/thư mục của bài học; kiểm tra bằng nhiệm vụ truy xuất sản phẩm.'),
    (('thu dien tu','giao tiep truc tuyen'), ('2.1','2.5'), 'Soạn thông điệp cho tình huống học tập, chọn kênh phù hợp và dùng ngôn ngữ lịch sự; đánh giá bằng bảng kiểm.'),
    (('chia se thong tin','chia se tep','chia se noi dung'), ('2.2','4.2'), 'Chia sẻ học liệu đúng người nhận, ghi nguồn và kiểm tra dữ liệu cá nhân trước khi gửi.'),
    (('hop tac truc tuyen','lam viec nhom truc tuyen'), ('2.4',), 'Cùng tạo một sản phẩm trên công cụ số được giáo viên chọn, phân công nhiệm vụ và ghi nhận đóng góp.'),
    (('an toan tren mang','mat khau','thong tin ca nhan'), ('4.2','2.5'), 'Phân loại thông tin được phép chia sẻ, nhận biết tình huống rủi ro và thực hành phản hồi an toàn.'),
    (('soan thao van ban','trinh chieu','ve tren may tinh','tao bai trinh chieu','thiet ke thiep'), ('3.1','3.3'), 'Tạo sản phẩm số phục vụ bài học, ghi nguồn học liệu; đánh giá theo nội dung, khả năng trình bày và sử dụng tư liệu hợp lệ.'),
    (('ban quyen','giay phep','trich dan nguon'), ('3.3',), 'Nhận diện tư liệu được phép sử dụng và bổ sung thông tin nguồn vào sản phẩm học tập.'),
    (('lap trinh','scratch','thuat toan','robot'), ('3.4','5.1'), 'Xây dựng chuỗi lệnh cho nhiệm vụ, chạy thử và sửa lỗi; đánh giá qua chương trình và mô tả cách kiểm thử.'),
    (('rac thai dien tu','tiet kiem dien cho may tinh'), ('4.4',), 'Xác định tác động môi trường của thiết bị số, đề xuất và thực hành một việc giảm tác động đó.'),
    (('tri tue nhan tao','chatbot'), ('6.1','6.3'), 'Giáo viên minh họa đầu ra AI, học sinh đối chiếu học liệu và nêu giới hạn; không nhập dữ liệu cá nhân.'),
]


def match(text, grade):
    data=framework()
    level=data['grade_levels'].get(str(grade))
    normalized=plain(text)
    results=[]
    for phrases, components, activity in CONTEXTS:
        evidence=next((p for p in phrases if p in normalized),None)
        if not evidence:
            continue
        for component in components:
            code=f'{component}.{level}a'
            item=next((x for x in data['indicators'] if x['code']==code),None)
            if item and not any(x['code']==code for x in results):
                results.append({**item,'evidence':evidence,'activity':activity,'source':data['source'],
                                'status':'Đề xuất tự động — giáo viên xác nhận'})
        if len(results)>=3:
            break
    return results[:3]

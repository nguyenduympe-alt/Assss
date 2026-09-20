"""Trang “Kiểm tra tài liệu có dấu hiệu do AI viết”.

Xử lý hoàn toàn trong bộ nhớ: KHÔNG lưu tệp tải lên ra đĩa, KHÔNG gửi dữ liệu ra ngoài.
Kết quả chỉ mang tính tham khảo — giao diện nói rõ điều này ngay trên đầu trang.
"""
from flask import Blueprint, render_template, request, session, flash

from ..auth import login_required, current_user
from ..modules import doc_ai_check as DA

bp = Blueprint('check_ai', __name__, url_prefix='/check-van-ban-ai')
MENU = {'label': 'Kiểm tra văn bản AI', 'endpoint': 'check_ai.index', 'icon': '🕵️'}

TOI_DA_BYTE = 8 * 1024 * 1024


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    kq = None
    ten_tep = ""
    if request.method == 'POST':
        blob = b""
        f = request.files.get('file')
        dan = (request.form.get('text') or '').strip()
        doan, loi = [], ""
        if f and (f.filename or '').strip():
            ten_tep = f.filename
            blob = f.read(TOI_DA_BYTE + 1)
            if len(blob) > TOI_DA_BYTE:
                loi = 'Tệp lớn hơn 8 MB nên hệ thống chưa xử lý.'
            elif ten_tep.lower().endswith('.docx'):
                try:
                    doan = DA.doc_docx(blob)
                except Exception:
                    loi = 'Không mở được tệp Word này (tệp có thể hỏng hoặc đang được mở ở máy khác).'
            elif ten_tep.lower().endswith('.pdf'):
                doan, loi = DA.doc_pdf(blob)
            elif ten_tep.lower().endswith(('.doc', '.rtf', '.txt', '.png', '.jpg', '.jpeg')):
                loi = ('Chỉ nhận tệp .docx hoặc .pdf. Với tệp .doc thầy/cô mở bằng Word rồi '
                       '“Lưu thành” .docx (hoặc dán văn bản vào ô bên dưới).')
            else:
                loi = 'Định dạng chưa được hỗ trợ. Hệ thống nhận .docx, .pdf, hoặc văn bản dán trực tiếp.'
        elif dan:
            doan = DA.tach_doan(dan)
            ten_tep = 'Văn bản dán trực tiếp'
        else:
            loi = 'Thầy/cô chưa chọn tệp và cũng chưa dán văn bản.'

        if not loi and not doan:
            loi = 'Không đọc được chữ nào trong tài liệu này.'
        if loi:
            flash(loi, 'err')
        else:
            kq = DA.cham(doan)
            kq["ten_tep"] = ten_tep
            kq["so_doan"] = len(doan)
            kq["doan"] = doan if len(doan) <= 60 else doan[:60]
    return render_template('check_ai.html', kq=kq, thong_tin=DA.thong_tin(),
                           nguoi=current_user()['fullname'] or current_user()['username'])

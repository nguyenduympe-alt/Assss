"""Trợ lý giáo án: TÍCH HỢP NĂNG LỰC SỐ và GIÁO DỤC AI, có bước giáo viên duyệt.

Luồng: tải giáo án Word → hệ thống phân tích cấu trúc và đề xuất tiêu chí →
giáo viên tích chọn từng mục → xuất BẢN SAO .docx, nội dung mới tô đỏ FF0000.

PHẠM VI: công cụ này làm 2 phần — (1) tích hợp năng lực số (Thông tư 02/2025/TT-BGDĐT)
và (2) tích hợp giáo dục AI dạng lồng ghép (Quyết định 2422/QĐ-BGDĐT,
Công văn 5588/BGDĐT-GDPT). Giáo viên tích chọn từng phần; bỏ tích là không chèn. Phần dò/sửa chính tả đã
tách thành công cụ riêng (“Kiểm tra chính tả”, app/plugins/chinh_ta.py) để giáo
viên chỉ chạy khi thật sự cần — không tự chạy kèm khi soạn giáo án.

Trung thực về bản chất công cụ:
  - Không gửi nội dung giáo án ra dịch vụ AI bên ngoài (xem modules/ai_provider.py,
    mọi lời gọi ra ngoài đều bị chặn cho tới khi giáo viên đồng ý rõ ràng).
  - Không chạy macro; chỉ đọc/ghi bằng python-docx trên file .docx.
  - Nội dung chèn vào file chỉ gồm mã/mạch, mục tiêu, minh chứng, hoạt động (kèm nguồn văn bản);
    KHÔNG in khối trích dẫn quy định hay phần đề xuất dài vào file Word
    (do hệ thống soạn, giáo viên phải duyệt).
"""
import io

from flask import Blueprint, request, render_template, flash, redirect, url_for, send_file

bp = Blueprint('giao_an_nls', __name__, url_prefix='/giao-an')

from ..auth import login_required, current_user
from ..modules import giao_an as GA
from ..modules import nld as NLD
from ..modules import nld_tich_hop as TH
from ..modules import ai_giao_duc as AIGD
from ..modules import ai_provider as AI
from .digital import folder, load, save  # dùng lại nơi lưu tạm, có kiểm tra chủ sở hữu

MENU = {'label': 'Giáo án, năng lực số & AI', 'endpoint': 'giao_an_nls.index', 'icon': '📝'}
MAX_BYTES = 8 * 1024 * 1024
AI_THOI_LUONG = 5          # phút lồng ghép giáo dục AI đề xuất mỗi tiết
NHAN_NOI_BO = ("Xử lý ngay trên máy chủ của trường, KHÔNG gửi nội dung giáo án ra ngoài; "
               "file Word không chạy macro.")


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not (file.filename or '').lower().endswith('.docx'):
            flash('Vui lòng chọn file Word .docx. File .doc hoặc .docm không được hỗ trợ.', 'err')
            return redirect(url_for('giao_an_nls.index'))
        try:
            lop = (request.form.get('grade') or '').strip()
            mon = (request.form.get('subject') or '').strip()
            thiet_bi = 'khong_co' if request.form.get('thiet_bi') == 'khong_co' else 'co'
            thoi_luong = max(3, min(20, int(request.form.get('thoi_luong') or 6)))
            toi_da = max(1, min(5, int(request.form.get('toi_da') or 3)))

            data = file.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                flash('File vượt quá 8 MB.', 'err')
                return redirect(url_for('giao_an_nls.index'))

            doc = GA.doc_word(data)          # kiểm tra an toàn + đọc .docx
            pt = TH.phan_tich_an_toan(doc)
            if lop:
                pt['lop'] = lop
            if mon:
                pt['mon'] = mon

            chon, canh_bao = TH.chon_tieu_chi(doc, pt, thiet_bi=thiet_bi, toi_da=toi_da)
            # giáo dục AI (Quyết định 2422/QĐ-BGDĐT + Công văn 5588/BGDĐT-GDPT)
            chon_ai, canh_bao_ai = TH.chon_muc_ai(doc, pt, toi_da=2,
                                                  thoi_luong=AI_THOI_LUONG, thiet_bi=thiet_bi)

            token = save(
                name=(file.filename or 'giao-an.docx')[:200],
                blob=data,
                ctx={
                    'ten_bai': TH.lay_ten_bai(doc),
                    'lop': pt['lop'], 'mon': pt['mon'],
                    'so_doan': pt['so_doan'], 'so_bang': pt['so_bang'],
                    'tien_trinh': pt['tien_trinh']['kieu'],
                    'tong_phut': pt['thoi_luong']['tong_phut'],
                    'pt_canh_bao': pt.get('canh_bao', []),
                    'chon': chon, 'canh_bao': canh_bao,
                    'chon_ai': chon_ai, 'canh_bao_ai': canh_bao_ai, 'ai_thoi_luong': AI_THOI_LUONG,
                    'thiet_bi': thiet_bi, 'thoi_luong': thoi_luong, 'toi_da': toi_da,
                    'doan_goc': TH.trang_thai_mau_goc(doc),
                })
            return redirect(url_for('giao_an_nls.duyet', token=token))
        except ValueError as exc:
            flash(str(exc), 'err')
        except Exception:
            flash('Không đọc được file Word này. Hãy mở lại bằng Word và lưu thành .docx rồi thử lại.', 'err')
        return redirect(url_for('giao_an_nls.index'))

    return render_template('giao_an_upload.html', nhan=NHAN_NOI_BO, luat=NLD.thong_ke())


@bp.route('/<token>/duyet', methods=['GET'])
@login_required
def duyet(token):
    ctx = load(token)
    if not ctx:
        flash('Phiên xử lý đã hết hạn hoặc bạn không có quyền truy cập. Vui lòng tải lại file.', 'err')
        return redirect(url_for('giao_an_nls.index'))
    return render_template('giao_an_duyet.html', ctx=ctx['ctx'], token=token,
                           ten_file=ctx['name'], nhan=NHAN_NOI_BO,
                           loi_cu=session_pop_loi_cu())


def session_pop_loi_cu():
    """Lấy cảnh báo chặn xuất của lần bấm trước (nếu có)."""
    from flask import session
    return session.pop('loi_cu', None)


@bp.route('/<token>/xuat', methods=['POST'])
@login_required
def xuat(token):
    ctx = load(token)
    if not ctx:
        flash('Phiên xử lý đã hết hạn. Vui lòng tải lại file.', 'err')
        return redirect(url_for('giao_an_nls.index'))
    c = ctx['ctx']
    chon_ma = [code for code in request.form.getlist('ma')]
    # Giáo viên có thể chọn CHỈ chèn phần giáo dục AI (không chèn mục năng lực số)
    chi_ai = request.form.get('chi_ai') == '1'
    # Nội dung giáo dục AI: CHỈ chèn những mạch giáo viên tích ở trang duyệt
    ma_ai = [x for x in request.form.getlist('ma_ai')]
    chon_ai = [x for x in (c.get('chon_ai') or []) if x.get('id') in ma_ai]
    if not chon_ma and not chi_ai:
        flash('Thầy/cô chưa tích tiêu chí năng lực số nào. Nếu bài này chỉ cần phần giáo dục AI, '
              'hãy tích ô “Chỉ chèn phần giáo dục AI cho bài này”; nếu vẫn cần phần năng lực số, '
              'hãy tích ít nhất một tiêu chí rồi tải lại file.', 'err')
        return redirect(url_for('giao_an_nls.duyet', token=token))
    if chi_ai:
        chon_ma = []
        if not chon_ai:
            flash('Thầy/cô đã chọn “chỉ chèn phần giáo dục AI” nhưng chưa tích mạch nội dung AI nào.', 'err')
            return redirect(url_for('giao_an_nls.duyet', token=token))
        if not (c.get('chon_ai') or []):
            flash('Bài này chưa đề xuất được mạch nội dung giáo dục AI nào.', 'err')
            return redirect(url_for('giao_an_nls.duyet', token=token))

    try:
        doc = GA.doc_word(open(folder() / (token + '.docx'), 'rb').read())
        doc_out, bao_cao = TH.xu_ly(
            doc, thiet_bi=c['thiet_bi'], toi_da=c['toi_da'], thoi_luong=c['thoi_luong'],
            lop_ghi_de=c['lop'] or '', mon_ghi_de=c['mon'] or '',
            goc_doan=c['doan_goc'], chon_ma=chon_ma,
            chon_ai=chon_ai, ai_thoi_luong=c.get('ai_thoi_luong') or AI_THOI_LUONG,
            chi_ai=chi_ai)
    except Exception:
        flash('Không tạo được bản Word. File gốc có thể đã hỏng — hãy lưu lại bằng Word rồi thử lại.', 'err')
        return redirect(url_for('giao_an_nls.duyet', token=token))

    kt = bao_cao.get('kiem_tra') or {}
    if not kt.get('xuat_duoc', True):
        from flask import session
        session['loi_cu'] = kt
        flash('Bộ kiểm tra phát hiện lỗi phải sửa trước khi xuất (xem chi tiết bên dưới).', 'err')
        return redirect(url_for('giao_an_nls.duyet', token=token))

    out = io.BytesIO()
    doc_out.save(out)
    out.seek(0)
    ten = 'Giao-an-tich-hop-%s-%s.docx' % (
        'AI' if chi_ai else ('NLS-va-AI' if chon_ai else 'NLS'), c['lop'] or 'khong-ro-lop')
    return send_file(out, as_attachment=True, download_name=ten,
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

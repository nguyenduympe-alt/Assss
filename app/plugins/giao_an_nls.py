"""Trợ lý giáo án: tích hợp năng lực số + sửa chính tả, có bước giáo viên duyệt.

Luồng: tải giáo án Word → hệ thống phân tích cấu trúc và đề xuất → giáo viên
tích chọn/bỏ từng mục → xuất BẢN SAO .docx, nội dung mới tô đỏ FF0000.

Trung thực về bản chất công cụ:
  - Không gửi nội dung giáo án ra dịch vụ AI bên ngoài (xem modules/ai_provider.py,
    mọi lời gọi ra ngoài đều bị chặn cho tới khi giáo viên đồng ý rõ ràng).
  - Không chạy macro; chỉ đọc/ghi bằng python-docx trên file .docx.
  - Mọi đề xuất đều ghi rõ [QUY ĐỊNH] (nguyên văn văn bản Bộ + nguồn) hay [ĐỀ XUẤT]
    (do hệ thống soạn, giáo viên phải duyệt).
"""
import io
from flask import Blueprint, request, render_template, session, flash, redirect, url_for, send_file

bp = Blueprint('giao_an_nls', __name__, url_prefix='/giao-an')

from ..auth import login_required, current_user
from ..modules import giao_an as GA
from ..modules import nld as NLD
from ..modules import nld_tich_hop as TH
from ..modules import chinh_ta_gd as CTG
from ..modules import ai_provider as AI
from ..modules import ml_noi_bo as ML
from ..modules import hoc_tu_nguoi_dung as HOC
from .digital import folder, load, save  # dùng lại nơi lưu tạm, có kiểm tra chủ sở hữu

MENU = {'label': 'Giáo án & năng lực số', 'endpoint': 'giao_an_nls.index', 'icon': '📝'}
MAX_BYTES = 8 * 1024 * 1024
NHAN_NOI_BO = ("Hệ thống chạy hoàn toàn trên máy chủ của trường: kho chỉ báo đã kiểm chứng, "
               "bộ luật chính tả và MỘT MÔ HÌNH NHỎ DO EDUASSIST TỰ HUẤN LUYỆN (dò lỗi chính tả). "
               "KHÔNG gửi nội dung giáo án ra Google/Gemini hay dịch vụ AI nào. "
               "Mô hình này KHÔNG phải mô hình ngôn ngữ lớn: không sinh nội dung, không hiểu nội dung.")


@bp.route('/hoc-tu-nguoi-dung/bat-tat', methods=['POST'])
@login_required
def bat_tat_hoc():
    """Bật/tắt việc ghi phản hồi để học. Mặc định bật; dữ liệu chỉ nằm trên máy chủ này."""
    HOC.dat_bat(not HOC.bat())
    flash('Đã %s việc học từ quyết định của giáo viên.' % ('BẬT' if HOC.bat() else 'TẮT'), 'ok')
    # Cho phép quay lại đúng trang đã bấm (trang chủ cũng có nút này). Chỉ nhận đường dẫn
    # nội bộ, không nhận địa chỉ ngoài để tránh bị lợi dụng làm trang chuyển hướng giả.
    quay_lai = (request.form.get('next') or '').strip()
    if quay_lai.startswith('/') and not quay_lai.startswith('//'):
        return redirect(quay_lai)
    return redirect(url_for('giao_an_nls.index'))


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
            doan = [p.text for p in CTG.cac_doan_van_ban(doc)]   # gồm cả chữ trong bảng
            de_xuat, bo_qua = CTG.soan_bao_cao(doan)

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
                    'de_xuat': de_xuat, 'bo_qua': bo_qua,
                    'thiet_bi': thiet_bi, 'thoi_luong': thoi_luong, 'toi_da': toi_da,
                    'doan_goc': TH.trang_thai_mau_goc(doc),
                })
            return redirect(url_for('giao_an_nls.duyet', token=token))
        except ValueError as exc:
            flash(str(exc), 'err')
        except Exception:
            flash('Không đọc được file Word này. Hãy mở lại bằng Word và lưu thành .docx rồi thử lại.', 'err')
        return redirect(url_for('giao_an_nls.index'))

    return render_template('giao_an_upload.html', nhan=NHAN_NOI_BO,
                           luat=NLD.thong_ke(), tu_dien=CTG.thong_ke_tu_dien(),
                           mo_hinh=ML.thong_tin(), hoc=HOC.thong_ke())


@bp.route('/<token>/duyet', methods=['GET'])
@login_required
def duyet(token):
    ctx = load(token)
    if not ctx:
        flash('Phiên xử lý đã hết hạn hoặc bạn không có quyền truy cập. Vui lòng tải lại file.', 'err')
        return redirect(url_for('giao_an_nls.index'))
    return render_template('giao_an_duyet.html', ctx=ctx['ctx'], token=token,
                           ten_file=ctx['name'], nhan=NHAN_NOI_BO,
                           nhan_ct=CTG.nhan_ket_qua(), loi_cu=session.pop('loi_cu', None),
                           nhan_mh=ML.nhan(), hoc_nguong_nhan=HOC.NGUONG_NHAN)


@bp.route('/<token>/xuat', methods=['POST'])
@login_required
def xuat(token):
    ctx = load(token)
    if not ctx:
        flash('Phiên xử lý đã hết hạn. Vui lòng tải lại file.', 'err')
        return redirect(url_for('giao_an_nls.index'))
    c = ctx['ctx']

    # Nút "Từ này đúng, đừng bắt nữa": ghi tín hiệu RÕ RÀNG rồi quay lại trang duyệt
    dung_tu = []
    for k in request.form:
        if k.startswith('dung_tu_'):
            try:
                dung_tu.append(int(k[len('dung_tu_'):]))
            except ValueError:
                pass
    if dung_tu:
        try:
            canh_bao = [d for d in c['de_xuat'] if d['id'] in dung_tu]
            HOC.ghi(canh_bao, [], giao_vien=HOC.ten_giao_vien(session.get('uid')),
                    lop=c.get('lop') or '', phien_ban=ML.thong_tin().get('phien_ban', ''),
                    ep_quyet_dinh='dung')
            flash('Đã ghi nhận: %s là từ đúng — lần sau hệ thống sẽ không bắt nữa.' %
                  ', '.join('“%s”' % d['goc'] for d in canh_bao), 'ok')
        except Exception:
            flash('Chưa ghi nhận được, thầy/cô thử lại giúp em.', 'err')
        return redirect(url_for('giao_an_nls.duyet', token=token))

    chon_ma = [code for code in request.form.getlist('ma')]
    chon_ct = []
    for d in c['de_xuat']:
        if request.form.get('ct_%s' % d['id']):
            chon_ct.append(d['id'])

    try:
        doc = GA.doc_word(open(folder() / (token + '.docx'), 'rb').read())
        doc_out, bao_cao = TH.xu_ly(
            doc, thiet_bi=c['thiet_bi'], toi_da=c['toi_da'], thoi_luong=c['thoi_luong'],
            lop_ghi_de=c['lop'] or '', mon_ghi_de=c['mon'] or '',
            goc_doan=c['doan_goc'], chon_ma=chon_ma,
            sua_chinh_ta={'de_xuat': c['de_xuat'], 'chon': chon_ct})
    except Exception:
        flash('Không tạo được bản Word. File gốc có thể đã hỏng — hãy lưu lại bằng Word rồi thử lại.', 'err')
        return redirect(url_for('giao_an_nls.duyet', token=token))

    # GHI PHẢN HỒI: giáo viên nhận hay bỏ qua từng đề xuất — đây là dữ liệu để
    # hệ thống học (xem app/modules/hoc_tu_nguoi_dung.py). Lỗi ghi không được làm
    # hỏng việc xuất tệp của giáo viên.
    try:
        HOC.ghi(c['de_xuat'], chon_ct, giao_vien=HOC.ten_giao_vien(session.get('uid')),
                lop=c.get('lop') or '', phien_ban=ML.thong_tin().get('phien_ban', ''))
    except Exception:
        pass

    kt = bao_cao.get('kiem_tra') or {}
    if not kt.get('xuat_duoc', True):
        session['loi_cu'] = kt
        flash('Bộ kiểm tra phát hiện lỗi phải sửa trước khi xuất (xem chi tiết bên dưới).', 'err')
        return redirect(url_for('giao_an_nls.duyet', token=token))

    out = io.BytesIO()
    doc_out.save(out)
    out.seek(0)
    ten = 'Giao-an-tich-hop-NLS-%s.docx' % (c['lop'] or 'khong-ro-lop')
    return send_file(out, as_attachment=True, download_name=ten,
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

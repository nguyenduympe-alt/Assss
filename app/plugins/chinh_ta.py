"""Kiểm tra chính tả — CÔNG CỤ RIÊNG, giáo viên cần thì mở mới chạy.

Trước đây phần dò lỗi chính tả nằm chung trong công cụ “Giáo án & năng lực số”,
nên giáo viên muốn soạn giáo án là tự nhiên bị chạy cả chính tả. Nay tách hẳn:

  - Công cụ NÀY chỉ làm một việc: dò và sửa lỗi chính tả, có giáo viên duyệt
    từng chỗ, trả về BẢN SAO .docx.
  - Việc tích hợp năng lực số là công cụ riêng “Giáo án & năng lực số”.

Nguyên tắc giữ nguyên:
  - Không gửi nội dung của thầy/cô ra Google/Gemini hay dịch vụ AI nào; mọi thứ
    chạy trên máy chủ này.
  - Không chạy macro; chỉ đọc/ghi .docx bằng python-docx.
  - Mỗi đề xuất đều ghi rõ nguồn: bộ luật nội bộ, mô hình nhỏ đã huấn luyện, hay
    bản sửa mà giáo viên trong trường đã duyệt trước đây.
  - Chữ đã sửa được tô đỏ FF0000 để thầy/cô thấy ngay hệ thống đã đụng vào đâu.
"""
import io

from flask import Blueprint, request, render_template, flash, redirect, url_for, send_file

bp = Blueprint('chinh_ta', __name__, url_prefix='/chinh-ta')
MENU = {'label': 'Kiểm tra chính tả', 'endpoint': 'chinh_ta.index', 'icon': '🔤'}

from ..auth import login_required, current_user
from ..db import get_db
from ..modules import giao_an as GA
from ..modules import chinh_ta_gd as CTG
from ..modules import ml_noi_bo as ML
from ..modules import hoc_tu_nguoi_dung as HOC
from ..modules import billing as BL
from .digital import folder, load, save

MAX_BYTES = 8 * 1024 * 1024
MAX_TEXT = 200_000

NHAN = ("Công cụ chạy hoàn toàn trên máy chủ của trường: bộ luật chính tả, từ điển thuật ngữ "
        "giáo dục và MỘT MÔ HÌNH NHỎ DO EDUASSIST TỰ HUẤN LUYỆN (chấm điểm từng từ). "
        "KHÔNG gửi nội dung ra Google/Gemini hay dịch vụ AI nào. "
        "Mô hình này KHÔNG phải mô hình ngôn ngữ lớn: không sinh nội dung, không hiểu nội dung.")

NGUON = {
    'mo_hinh': 'mô hình nhỏ đã huấn luyện',
    'hoc_tu_nguoi_dung': 'đã được giáo viên duyệt trước đây',
    'luat': 'bộ luật nội bộ',
}


def _nguon_label(d):
    return NGUON.get(d.get('nguon') or 'luat', 'bộ luật nội bộ')


def _docx_tu_text(text):
    """Dựng một tệp .docx tối giản từ nội dung dán tay, để dùng chung một đường xử lý."""
    from docx import Document
    d = Document()
    for dong in (text or '').splitlines():
        d.add_paragraph(dong)
    b = io.BytesIO()
    d.save(b)
    return b.getvalue()


@bp.route('/hoc-tu-nguoi-dung/bat-tat', methods=['POST'])
@login_required
def bat_tat_hoc():
    """Bật/tắt việc ghi phản hồi để học. Mặc định bật; dữ liệu chỉ nằm trên máy chủ này."""
    HOC.dat_bat(not HOC.bat())
    flash('Đã %s việc học từ quyết định của giáo viên.' % ('BẬT' if HOC.bat() else 'TẮT'), 'ok')
    # Chỉ nhận đường dẫn nội bộ, không nhận địa chỉ ngoài để tránh bị lợi dụng
    # làm trang chuyển hướng giả.
    quay_lai = (request.form.get('next') or '').strip()
    if quay_lai.startswith('/') and not quay_lai.startswith('//'):
        return redirect(quay_lai)
    return redirect(url_for('chinh_ta.index'))


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        tep = request.files.get('file')
        dan_tay = (request.form.get('noi_dung') or '').strip()
        lop = (request.form.get('grade') or '').strip()
        mon = (request.form.get('subject') or '').strip()
        if lop and lop not in [str(i) for i in range(1, 13)]:
            lop = ''
        if len(mon) > 100:
            mon = mon[:100]

        try:
            if tep and tep.filename:
                if not (tep.filename or '').lower().endswith('.docx'):
                    flash('Vui lòng chọn file Word .docx. File .doc hoặc .docm không được hỗ trợ.', 'err')
                    return redirect(url_for('chinh_ta.index'))
                data = tep.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    flash('File vượt quá 8 MB.', 'err')
                    return redirect(url_for('chinh_ta.index'))
                ten = (tep.filename or 'van-ban.docx')[:200]
                nguon_vao = 'tệp Word'
            elif dan_tay:
                if len(dan_tay) > MAX_TEXT:
                    flash('Nội dung dán vào quá dài (tối đa 200.000 ký tự).', 'err')
                    return redirect(url_for('chinh_ta.index'))
                data = _docx_tu_text(dan_tay)
                ten = 'Văn bản dán tay'
                nguon_vao = 'nội dung dán tay'
            else:
                flash('Vui lòng chọn file Word .docx hoặc dán nội dung cần kiểm tra.', 'err')
                return redirect(url_for('chinh_ta.index'))

            doc = GA.doc_word(data)                       # kiểm tra an toàn + đọc .docx
            doan = [p.text for p in CTG.cac_doan_van_ban(doc)]
            de_xuat, bo_qua = CTG.soan_bao_cao(doan)
            token = save(name=ten, blob=data, ctx={
                'ten': ten, 'nguon_vao': nguon_vao, 'lop': lop, 'mon': mon,
                'so_doan': len(doan), 'de_xuat': de_xuat, 'bo_qua': bo_qua,
            })
            return redirect(url_for('chinh_ta.duyet', token=token))
        except ValueError as exc:
            flash(str(exc), 'err')
        except Exception:
            flash('Không đọc được file Word này. Hãy mở lại bằng Word và lưu thành .docx rồi thử lại.', 'err')
        return redirect(url_for('chinh_ta.index'))

    return render_template('chinh_ta_upload.html', nhan=NHAN,
                           luat=CTG.thong_ke_tu_dien(), mo_hinh=ML.thong_tin(),
                           hoc=HOC.thong_ke(), nhan_ct=CTG.nhan_ket_qua())


@bp.route('/<token>/duyet')
@login_required
def duyet(token):
    ctx = load(token)
    if not ctx:
        flash('Phiên xử lý đã hết hạn hoặc bạn không có quyền truy cập. Vui lòng tải lại file.', 'err')
        return redirect(url_for('chinh_ta.index'))
    c = ctx['ctx']
    return render_template('chinh_ta_duyet.html', c=c, token=token, ten_file=ctx['name'],
                           nhan=NHAN, nhan_ct=CTG.nhan_ket_qua(), nhan_mh=ML.nhan(),
                           hoc_nguong_nhan=HOC.NGUONG_NHAN, nguon=NGUON)


@bp.route('/<token>/xuat', methods=['POST'])
@login_required
def xuat(token):
    ctx = load(token)
    if not ctx:
        flash('Phiên xử lý đã hết hạn. Vui lòng tải lại file.', 'err')
        return redirect(url_for('chinh_ta.index'))
    c = ctx['ctx']

    # Nút "Từ này đúng, đừng bắt nữa": ghi tín hiệu RÕ RÀNG rồi quay lại trang duyệt.
    # Việc này không tốn lượt và không đụng gì tới tệp của giáo viên.
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
            HOC.ghi(canh_bao, [], giao_vien=HOC.ten_giao_vien(_uid()), lop=c.get('lop') or '',
                    phien_ban=ML.thong_tin().get('phien_ban', ''), ep_quyet_dinh='dung')
            flash('Đã ghi nhận: %s là từ đúng — lần sau hệ thống sẽ không bắt nữa.' %
                  ', '.join('“%s”' % d['goc'] for d in canh_bao), 'ok')
        except Exception:
            flash('Chưa ghi nhận được, thầy/cô thử lại giúp em.', 'err')
        return redirect(url_for('chinh_ta.duyet', token=token))

    chon_ct = [d['id'] for d in c['de_xuat'] if request.form.get('ct_%s' % d['id'])]
    if not chon_ct:
        flash('Thầy/cô chưa tích chỗ nào để sửa, nên chưa có gì thay đổi.', 'err')
        return redirect(url_for('chinh_ta.duyet', token=token))

    # Giữ nguyên chính sách tính lượt như công cụ chính tả trước đây: 1 lượt cho một
    # lần xuất bản đã sửa. Việc bấm “từ này đúng” ở trên KHÔNG tốn lượt.
    db, u = get_db(), current_user()
    if not BL.can_use(u):
        return redirect(url_for('core.nang_cap', need='chinhta'))

    try:
        doc = GA.doc_word(open(folder() / (token + '.docx'), 'rb').read())
        da_sua = CTG.ap_dung_vao_docx(doc, c['de_xuat'], chon_ct)
    except Exception:
        flash('Không tạo được bản Word. File gốc có thể đã hỏng — hãy lưu lại bằng Word rồi thử lại.', 'err')
        return redirect(url_for('chinh_ta.duyet', token=token))

    if not da_sua:
        flash('Không áp dụng được chỗ nào (văn bản có thể đã thay đổi). Thầy/cô tải lại file giúp em.', 'err')
        return redirect(url_for('chinh_ta.duyet', token=token))

    BL.consume(db, u, 'chinhta', 'Sửa %d chỗ — %s' % (da_sua, c.get('ten') or ''))

    # GHI PHẢN HỒI: nhận hay bỏ qua từng đề xuất — dữ liệu để hệ thống học dần
    # (xem app/modules/hoc_tu_nguoi_dung.py). Lỗi ghi không được làm hỏng việc xuất tệp.
    try:
        HOC.ghi(c['de_xuat'], chon_ct, giao_vien=HOC.ten_giao_vien(_uid()),
                lop=c.get('lop') or '', phien_ban=ML.thong_tin().get('phien_ban', ''))
    except Exception:
        pass

    out = io.BytesIO()
    doc.save(out)
    out.seek(0)
    goc = (c.get('ten') or 'van-ban').rsplit('.', 1)[0][:150]
    return send_file(out, as_attachment=True, download_name='%s-da-sua-chinh-ta.docx' % goc,
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')


def _uid():
    from flask import session
    return session.get('uid')

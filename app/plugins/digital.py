import json
import os
import re
import time
import uuid
from pathlib import Path
from flask import Blueprint, request, render_template, session, flash, redirect, url_for, send_file
from ..auth import login_required, current_user
from ..modules import digital_plan as DP

bp = Blueprint('digital', __name__, url_prefix='/nang-luc-so')
MENU = {'label': 'Năng lực số & STEM', 'endpoint': 'digital.index', 'icon': '🧩'}
FIELDS = ('week','topic','title','periods','digital','ai','stem','notes')


def folder():
    root = Path(os.environ.get('DB_DIR', 'data')) / 'digital-tmp'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for path in root.glob('*'):
        if re.fullmatch(r'[0-9a-f]{32}\.(json|docx)', path.name):
            try:
                if time.time() - path.stat().st_mtime > 7200:
                    path.unlink()
            except FileNotFoundError:
                pass
    return root


def save(name, blob, ctx):
    """Lưu file tải lên + ngữ cảnh xử lý, trả về token dùng ở bước xem trước."""
    token = uuid.uuid4().hex
    root = folder()
    (root / (token + '.docx')).write_bytes(blob)
    ctx = {"uid": current_user()['id'], "name": name, "ctx": ctx}
    (root / (token + '.json')).write_text(json.dumps(ctx, ensure_ascii=False), encoding='utf-8')
    return token


def load(token):
    if not re.fullmatch(r'[0-9a-f]{32}', token or ''):
        return None
    root = folder()
    try:
        ctx = json.loads((root / (token + '.json')).read_text(encoding='utf-8'))
        if ctx['uid'] != current_user()['id']:
            return None
        return ctx
    except (OSError, ValueError, KeyError):
        return None


@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method == 'POST':
        file = request.files.get('file')
        mode, grade, subject = (request.form.get(k, '').strip() for k in ('mode','grade','subject'))
        # (M7) số bài cần tích hợp ở phân phối chương trình (để trống = hệ thống tự chọn bài phù hợp)
        so_bai = (request.form.get('so_bai') or '').strip()
        # Giáo viên chọn nội dung cần tích hợp: năng lực số / giáo dục AI / STEM — có thể chọn riêng hoặc cả hai
        chon = tuple('digital' if k == 'nls' else k
                     for k in ('nls', 'ai', 'stem') if request.form.get('chon_' + k))
        if not file or not file.filename.lower().endswith('.docx'):
            flash('Vui lòng chọn file Word .docx (không hỗ trợ .doc hoặc file ảnh).', 'err')
        elif mode not in ('ppct','lesson') or grade not in [str(i) for i in range(1,13)] or not 1 <= len(subject) <= 100:
            flash('Vui lòng chọn loại tài liệu, lớp 1–12 và nhập môn học.', 'err')
        elif so_bai and (not so_bai.isdigit() or not 1 <= int(so_bai) <= 180):
            flash('Số bài cần tích hợp phải là số từ 1 đến 180, hoặc để trống.', 'err')
        elif not chon:
            flash('Hãy chọn ít nhất một nội dung cần tích hợp: năng lực số, giáo dục AI hoặc STEM.', 'err')
        else:
            try:
                data = file.read(8 * 1024 * 1024 + 1)
                rows = DP.preview(data, mode, grade, subject, chon=chon,
                                  so_bai=int(so_bai) if so_bai else None)
                token = uuid.uuid4().hex
                root = folder()
                (root / (token + '.docx')).write_bytes(data)
                ctx = dict(uid=current_user()['id'], rows=rows, mode=mode, grade=grade, subject=subject,
                           name=file.filename[:200], chon=list(chon),
                           so_bai=int(so_bai) if so_bai else None,
                           tom_tat=dict(so_dong=len(rows),
                                        so_de_xuat=sum(1 for r in rows if r.get('de_xuat_tich_hop')),
                                        so_phu_hop=sum(1 for r in rows if (r.get('diem_phu_hop') or 0) > 0),
                                        so_bai=int(so_bai) if so_bai else None,
                                        tin_hoc=DP.la_tin_hoc(subject)))
                (root / (token + '.json')).write_text(json.dumps(ctx, ensure_ascii=False), encoding='utf-8')
                return redirect(url_for('digital.review', token=token))
            except ValueError as exc:
                flash(str(exc), 'err')
            except Exception:
                flash('Không đọc được tài liệu Word. Hãy lưu lại file .docx và thử lại.', 'err')
    return render_template('digital_upload.html', source=DP.SOURCE)


@bp.route('/xem-truoc/<token>', methods=['GET', 'POST'])
@login_required
def review(token):
    ctx = load(token)
    if not ctx:
        flash('Phiên xử lý đã hết hạn hoặc bạn không có quyền truy cập. Vui lòng tải lại file.', 'err')
        return redirect(url_for('digital.index'))
    if request.method == 'POST':
        if not request.form.get('reviewed'):
            flash('Vui lòng xác nhận đã rà soát nội dung trước khi xuất Word.', 'err')
        else:
            rows = []
            for index, original in enumerate(ctx['rows']):
                row = {key: request.form.get(f'{index}_{key}', original.get(key, '')).strip() for key in FIELDS}
                # ô tích “giữ” từng cột: bỏ tích nghĩa là để trống cột đó ở dòng này
                for key in ('digital', 'ai', 'stem'):
                    if not request.form.get(f'{index}_giu_{key}'):
                        row[key] = ''
                if any(len(value) > 5000 for value in row.values()):
                    flash('Một ô nội dung vượt quá 5.000 ký tự.', 'err')
                    return render_template('digital_review.html', ctx=ctx, token=token)
                row['_merge'] = original.get('_merge', {})
                # ô nào do hệ thống đề xuất (file gốc để trống) -> tô màu khi xuất:
                # năng lực số đỏ FF0000, giáo dục AI xanh dương 0000FF
                _goc = original.get('original') or {}      # giá trị THẬT trong file giáo viên tải lên
                row['_themmoi'] = {k: bool(row[k].strip()) and not (_goc.get(k) or '').strip()
                                   for k in ('digital', 'ai', 'stem')}
                rows.append(row)
            data = (folder() / (token + '.docx')).read_bytes()
            output = DP.export(data, ctx['mode'], rows, ctx['grade'], ctx['subject'])
            _phan = []
            if any(r.get('digital') for r in rows):
                _phan.append('NLS')
            if any(r.get('ai') for r in rows):
                _phan.append('AI')
            if any(r.get('stem') for r in rows):
                _phan.append('STEM')
            _ten = ('KHGD' if ctx['mode'] == 'ppct' else 'Giao-an') + '-tich-hop-' + \
                   ('-'.join(_phan) if _phan else 'trong') + '.docx'
            return send_file(output, as_attachment=True, download_name=_ten,
                             mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return render_template('digital_review.html', ctx=ctx, token=token)

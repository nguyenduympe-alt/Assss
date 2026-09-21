import json
import os
import re
import time
import uuid
from pathlib import Path
from flask import Blueprint, request, render_template, session, flash, redirect, url_for, send_file
from ..auth import login_required, current_user
from ..db import get_db
from ..modules import billing as BL
from ..modules import digital_plan as DP
from ..modules import khdh_kho as KHO

bp = Blueprint('digital', __name__, url_prefix='/nang-luc-so')
# (M11) Tên chức năng nói đủ phạm vi: KHDH (kế hoạch dạy học) + NLS + AI + STEM
MENU = {'label': 'KHDH + NLS + AI + STEM', 'endpoint': 'digital.index', 'icon': '🧩'}
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
        # (M10) hạn mức dùng chung cho tất cả chức năng: hết 3 lượt thì phải nâng VIP
        if BL.chan_het(current_user()):
            flash(BL.thong_bao_het(), 'err')
            return redirect(url_for('core.nang_cap', need='khgd'))
        file = request.files.get('file')
        mode, grade, subject = (request.form.get(k, '').strip() for k in ('mode','grade','subject'))
        # (M7) số bài cần tích hợp ở phân phối chương trình (để trống = hệ thống tự chọn bài phù hợp)
        so_bai = (request.form.get('so_bai') or '').strip()
        # (M9) số bài cần tích hợp AI riêng + tùy chọn tích hợp năng lực số và AI cùng bài
        so_bai_ai = (request.form.get('so_bai_ai') or '').strip()
        cung_bai = ('1' in request.form.getlist('cung_bai')) or ('cung_bai' not in request.form)
        # Giáo viên chọn nội dung cần tích hợp: năng lực số / giáo dục AI / STEM — có thể chọn riêng hoặc cả hai
        chon = tuple('digital' if k == 'nls' else k
                     for k in ('nls', 'ai', 'stem') if request.form.get('chon_' + k))
        if not file or not file.filename.lower().endswith('.docx'):
            flash('Vui lòng chọn file Word .docx (không hỗ trợ .doc hoặc file ảnh).', 'err')
        elif mode not in ('ppct','lesson') or grade not in [str(i) for i in range(1,13)] or not 1 <= len(subject) <= 100:
            flash('Vui lòng chọn loại tài liệu, lớp 1–12 và nhập môn học.', 'err')
        elif so_bai and (not so_bai.isdigit() or not 1 <= int(so_bai) <= 180):
            flash('Số bài cần tích hợp năng lực số phải là số từ 1 đến 180, hoặc để trống.', 'err')
        elif so_bai_ai and (not so_bai_ai.isdigit() or not 1 <= int(so_bai_ai) <= 180):
            flash('Số bài cần tích hợp AI phải là số từ 1 đến 180, hoặc để trống.', 'err')
        elif not chon:
            flash('Hãy chọn ít nhất một nội dung cần tích hợp: năng lực số, giáo dục AI hoặc STEM.', 'err')
        else:
            try:
                data = file.read(8 * 1024 * 1024 + 1)
                rows = DP.preview(data, mode, grade, subject, chon=chon,
                                  so_bai=int(so_bai) if so_bai else None,
                                  so_bai_ai=int(so_bai_ai) if so_bai_ai else None,
                                  cung_bai=cung_bai)
                token = luu_phien(data, rows, mode, grade, subject, file.filename[:200], chon,
                                  so_bai, so_bai_ai, cung_bai)
                # tính 1 lượt cho một tài liệu đã xử lý xong (bước tải tệp đã duyệt KHÔNG tính thêm)
                BL.consume(get_db(), current_user(), 'khgd',
                           '%s: %s' % ('KHGD/PPCT' if mode == 'ppct' else 'Giáo án tích hợp',
                                       (file.filename or '')[:120]))
                return redirect(url_for('digital.review', token=token))
            except ValueError as exc:
                flash(str(exc), 'err')
            except Exception:
                flash('Không đọc được tài liệu Word. Hãy lưu lại file .docx và thử lại.', 'err')
    return render_template('digital_upload.html', source=DP.SOURCE,
                           kho=kho_view(get_db(), current_user()['id']),
                           khoi=KHO.KHOI, kho_moi=request.args.get('kho', type=int))


def luu_phien(data, rows, mode, grade, subject, name, chon, so_bai, so_bai_ai, cung_bai):
    """Lưu tệp + bản xem trước vào thư mục tạm, trả về token dùng ở bước rà soát."""
    token = uuid.uuid4().hex
    root = folder()
    (root / (token + '.docx')).write_bytes(data)
    ctx = dict(uid=current_user()['id'], rows=rows, mode=mode, grade=grade, subject=subject,
               name=name, chon=list(chon),
               so_bai=int(so_bai) if so_bai else None,
               so_bai_ai=int(so_bai_ai) if so_bai_ai else None,
               cung_bai=cung_bai,
               tom_tat=dict(so_dong=len(rows),
                            so_de_xuat=sum(1 for r in rows if r.get('de_xuat_tich_hop')),
                            so_de_xuat_nls=sum(1 for r in rows if r.get('chon_nls')),
                            so_de_xuat_ai=sum(1 for r in rows if r.get('chon_ai')),
                            so_phu_hop=sum(1 for r in rows if (r.get('diem_phu_hop') or 0) > 0),
                            so_bai=int(so_bai) if so_bai else None,
                            so_bai_ai=int(so_bai_ai) if so_bai_ai else None,
                            cung_bai=bool(cung_bai),
                            tin_hoc=DP.la_tin_hoc(subject)))
    (root / (token + '.json')).write_text(json.dumps(ctx, ensure_ascii=False), encoding='utf-8')
    return token


# ---------------- (M12) Kho KHDH theo môn ----------------
def kho_view(db, uid):
    """Danh sách môn trong kho + các phiên bản cũ của từng môn (hiện ở trang tải lên)."""
    tat_ca = db.execute('SELECT * FROM khdh WHERE teacher_id=?'
                        ' ORDER BY mon COLLATE NOCASE, CAST(khoi AS INTEGER), dang_dung DESC,'
                        ' phien_ban DESC, id DESC', (uid,)).fetchall()
    ds = []
    for k in tat_ca:
        if not k['dang_dung']:
            continue
        khac = [r for r in tat_ca if not r['dang_dung'] and r['mon_chuan'] == k['mon_chuan']
                and r['khoi'] == k['khoi']]
        ds.append({'r': k, 'ban': 1 + len(khac), 'khac': khac})
    return ds


def _doc_chon():
    """Đọc các ô chọn nội dung tích hợp + số bài từ form."""
    chon = tuple('digital' if k == 'nls' else k
                 for k in ('nls', 'ai', 'stem') if request.form.get('chon_' + k))
    so_bai = (request.form.get('so_bai') or '').strip()
    so_bai_ai = (request.form.get('so_bai_ai') or '').strip()
    cung_bai = ('1' in request.form.getlist('cung_bai')) or ('cung_bai' not in request.form)
    return chon, so_bai, so_bai_ai, cung_bai


def _loi_so_bai(so_bai, so_bai_ai):
    if so_bai and (not so_bai.isdigit() or not 1 <= int(so_bai) <= 180):
        return 'Số bài cần tích hợp năng lực số phải là số từ 1 đến 180, hoặc để trống.'
    if so_bai_ai and (not so_bai_ai.isdigit() or not 1 <= int(so_bai_ai) <= 180):
        return 'Số bài cần tích hợp AI phải là số từ 1 đến 180, hoặc để trống.'
    return ''


@bp.route('/kho/them', methods=['POST'])
@login_required
def kho_them():
    """Thêm một môn + KHDH vào kho. Mỗi môn + khối giữ 1 KHDH đang dùng.

    Trùng môn + khối thì chuyển sang trang hỏi: thay thế bản cũ hay giữ cả hai bản
    (xem `kho_xac_nhan`). Lưu kho KHÔNG trừ lượt — lượt chỉ trừ khi tạo bản tích hợp NLS/AI/STEM.
    """
    db, uid = get_db(), current_user()['id']
    mon = (request.form.get('mon') or '').strip()
    khoi = (request.form.get('khoi') or '').strip()
    loai = (request.form.get('loai') or 'ppct').strip()
    tiet = (request.form.get('tiet_tuan') or '').strip()
    file = request.files.get('file')
    if not mon or len(mon) > 100:
        flash('Vui lòng nhập tên môn (ví dụ: Toán).', 'err')
    elif khoi not in KHO.KHOI:
        flash('Vui lòng chọn khối từ 1 đến 12.', 'err')
    elif loai not in ('ppct', 'lesson'):
        flash('Vui lòng chọn loại tài liệu KHDH.', 'err')
    elif tiet and (not tiet.isdigit() or not 1 <= int(tiet) <= 40):
        flash('Số tiết mỗi tuần phải là số từ 1 đến 40, hoặc để trống để hệ thống tự suy ra.', 'err')
    elif not file or not file.filename.lower().endswith('.docx'):
        flash('Vui lòng chọn file KHDH Word .docx.', 'err')
    else:
        try:
            data = file.read(8 * 1024 * 1024 + 1)
            rows = KHO.rows_tu_tep(data)
        except ValueError as exc:
            flash(str(exc), 'err')
        except Exception:
            flash('Không đọc được tài liệu Word. Hãy lưu lại file .docx và thử lại.', 'err')
        else:
            tiet_tu_dong = int(tiet) if tiet else KHO.so_tiet_tuan(rows)
            cu = KHO.ban_dang_dung(db, uid, mon, khoi)
            if cu and (cu['ten_file'] or cu['luu']):
                token = uuid.uuid4().hex
                root = folder()
                (root / (token + '.docx')).write_bytes(data)
                ctx = dict(uid=uid, kho=True, name=file.filename[:200], mon=mon, khoi=khoi, loai=loai,
                           tiet_tuan=tiet_tu_dong, tiet_tay=bool(tiet), so_dong=len(rows),
                           tom_tat=KHO.tom_tat(rows))
                (root / (token + '.json')).write_text(json.dumps(ctx, ensure_ascii=False),
                                                      encoding='utf-8')
                return render_template('digital_kho_hoi.html', ctx=ctx, token=token, cu=cu,
                                       so_dong=len(rows), tom_tat=KHO.tom_tat(rows))
            kid = KHO.luu(db, uid, mon, khoi, file.filename, data, rows, loai=loai,
                          tiet_tuan=tiet_tu_dong, so_tiet_tay=(int(tiet) if tiet else None))
            flash('Đã thêm môn %s với KHDH “%s”.' % (KHO.ten_mon(mon, khoi), file.filename[:80]), 'ok')
            return redirect(url_for('digital.index', kho=kid))
    return redirect(url_for('digital.index'))


@bp.route('/kho/<int:kid>/xac-nhan', methods=['GET', 'POST'])
@login_required
def kho_xac_nhan(kid):
    """Bước 2 khi thêm KHDH trùng môn + khối: lưu theo quyết định của giáo viên."""
    db, uid = get_db(), current_user()['id']
    token = (request.form.get('token') or '').strip()
    quyet = request.form.get('quyet_dinh')
    ctx = load(token)
    if not ctx or not ctx.get('kho'):
        flash('Phiên xử lý đã hết hạn. Vui lòng gửi lại tệp KHDH.', 'err')
        return redirect(url_for('digital.index'))
    cu = KHO.ban_dang_dung(db, uid, ctx['mon'], ctx['khoi'])
    if quyet not in ('thay', 'giu'):
        flash('Hãy chọn thay thế bản cũ hoặc giữ cả hai bản.', 'err')
        return render_template('digital_kho_hoi.html', ctx=ctx, token=token, cu=cu,
                               so_dong=ctx.get('so_dong'), tom_tat=ctx.get('tom_tat'))
    try:
        data = (folder() / (token + '.docx')).read_bytes()
    except OSError:
        flash('Không đọc lại được tệp vừa tải lên. Vui lòng gửi lại KHDH.', 'err')
        return redirect(url_for('digital.index'))
    kid = KHO.luu(db, uid, ctx['mon'], ctx['khoi'], ctx['name'], data, loai=ctx.get('loai') or 'ppct',
                  tiet_tuan=ctx.get('tiet_tuan'), thay_the=(quyet == 'thay'))
    if quyet == 'thay':
        flash('Đã thay KHDH của môn %s bằng bản mới.' % KHO.ten_mon(ctx['mon'], ctx['khoi']), 'ok')
    else:
        flash('Đã thêm bản mới cho môn %s; bản cũ vẫn giữ trong kho (xem phần “phiên bản trước”).'
              % KHO.ten_mon(ctx['mon'], ctx['khoi']), 'ok')
    return redirect(url_for('digital.index', kho=kid))


@bp.route('/kho/<int:kid>/tich-hop', methods=['POST'])
@login_required
def kho_tich_hop(kid):
    """Tích hợp NLS/AI/STEM cho KHDH đã có trong kho — không cần tải tệp lên lại."""
    db, uid = get_db(), current_user()['id']
    row = KHO.tim(db, uid, kid)
    if not row:
        flash('Không tìm thấy môn này trong kho KHDH.', 'err')
        return redirect(url_for('digital.index'))
    if BL.chan_het(current_user()):
        flash(BL.thong_bao_het(), 'err')
        return redirect(url_for('core.nang_cap', need='khgd'))
    chon, so_bai, so_bai_ai, cung_bai = _doc_chon()
    loi = _loi_so_bai(so_bai, so_bai_ai)
    data = KHO.doc_tep(uid, row)
    if not chon:
        flash('Hãy chọn ít nhất một nội dung cần tích hợp: năng lực số, giáo dục AI hoặc STEM.', 'err')
    elif loi:
        flash(loi, 'err')
    elif not data:
        flash('Tệp KHDH của môn này không còn trong kho — thầy/cô tải lên lại giúp.', 'err')
    else:
        try:
            rows = DP.preview(data, row['loai'] or 'ppct', row['khoi'], row['mon'], chon=chon,
                              so_bai=int(so_bai) if so_bai else None,
                              so_bai_ai=int(so_bai_ai) if so_bai_ai else None, cung_bai=cung_bai)
        except ValueError as exc:
            flash(str(exc), 'err')
        except Exception:
            flash('Không đọc được tài liệu Word trong kho. Hãy tải KHDH lên lại.', 'err')
        else:
            ten = (row['ten_file'] or 'KHDH')[:200]
            token = luu_phien(data, rows, row['loai'] or 'ppct', row['khoi'], row['mon'], ten,
                              chon, so_bai, so_bai_ai, cung_bai)
            BL.consume(db, current_user(), 'khgd', 'KHDH trong kho — %s: %s'
                       % (KHO.ten_mon(row['mon'], row['khoi']), ten[:100]))
            return redirect(url_for('digital.review', token=token))
    return redirect(url_for('digital.index', kho=kid))


@bp.route('/kho/<int:kid>/tiet-tuan', methods=['POST'])
@login_required
def kho_tiet_tuan(kid):
    """Giáo viên nhập tay số tiết mỗi tuần (để trống → hệ thống suy ra lại từ KHDH)."""
    db, uid = get_db(), current_user()['id']
    so = (request.form.get('so_tiet_tuan') or '').strip()
    row = KHO.tim(db, uid, kid)
    if not row:
        flash('Không tìm thấy môn này trong kho KHDH.', 'err')
    elif so and (not so.isdigit() or not 1 <= int(so) <= 40):
        flash('Số tiết mỗi tuần phải là số từ 1 đến 40 (để trống thì hệ thống suy ra từ KHDH).', 'err')
    else:
        KHO.dat_tiet_tuan(db, uid, kid, int(so) if so else None)
        flash('Đã cập nhật số tiết mỗi tuần của môn %s.' % KHO.ten_mon(row['mon'], row['khoi']), 'ok')
    return redirect(url_for('digital.index', kho=kid))


@bp.route('/kho/<int:kid>/doi-ban', methods=['POST'])
@login_required
def kho_doi_ban(kid):
    """Chọn bản KHDH đang dùng khi một môn có nhiều phiên bản."""
    db, uid = get_db(), current_user()['id']
    row = KHO.tim(db, uid, kid)
    if not row:
        flash('Không tìm thấy bản KHDH này.', 'err')
    else:
        KHO.doi_ban(db, uid, kid)
        flash('Đã chuyển môn %s sang dùng bản “%s”.'
              % (KHO.ten_mon(row['mon'], row['khoi']), (row['ten_file'] or 'không tên')[:80]), 'ok')
    return redirect(url_for('digital.index', kho=kid))


@bp.route('/kho/<int:kid>/xoa-ban', methods=['POST'])
@login_required
def kho_xoa_ban(kid):
    """Xoá một phiên bản KHDH cũ (không xoá được bản đang dùng)."""
    db, uid = get_db(), current_user()['id']
    if not KHO.xoa_ban(db, uid, kid):
        flash('Chỉ xoá được bản KHDH cũ (không xoá bản đang dùng).', 'err')
    else:
        flash('Đã xoá một phiên bản KHDH cũ.', 'ok')
    return redirect(url_for('digital.index'))


@bp.route('/kho/<int:kid>/xoa', methods=['POST'])
@login_required
def kho_xoa(kid):
    """Xoá môn khỏi kho KHDH (kèm mọi phiên bản và tệp)."""
    db, uid = get_db(), current_user()['id']
    row = KHO.tim(db, uid, kid)
    if not row or not KHO.xoa(db, uid, kid):
        flash('Không tìm thấy môn này trong kho KHDH.', 'err')
    else:
        flash('Đã xoá môn %s khỏi kho KHDH.' % KHO.ten_mon(row['mon'], row['khoi']), 'ok')
    return redirect(url_for('digital.index'))


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
            _ten = ('KHDH' if ctx['mode'] == 'ppct' else 'Giao-an') + '-tich-hop-' + \
                   ('-'.join(_phan) if _phan else 'trong') + '.docx'
            return send_file(output, as_attachment=True, download_name=_ten,
                             mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return render_template('digital_review.html', ctx=ctx, token=token)

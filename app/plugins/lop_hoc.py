"""Lớp học lấy từ thời khoá biểu + bài kiểm tra trắc nghiệm.

Lớp = DISTINCT tên lớp trong TKB (sau khi AI/hệ thống đọc TKB).
Đề: tải Word/PDF — file câu hỏi thì đáp án in đậm/gạch chân; tài liệu thì sinh đề nội bộ.
Học sinh mở link, ghi họ tên, làm bài. Kết quả xuất Excel (sắp tên, lót, họ) + nhận xét AI ngắn.
Không gửi file giáo viên ra ngoài.
"""
import json
import os
import re
import secrets
from pathlib import Path

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   send_file, url_for)

from ..auth import current_user, login_required
from ..db import get_db
from ..modules import de_kiem_tra as DE
from ..security import allow_request

bp = Blueprint('lop_hoc', __name__)
MAX_BYTES = 8 * 1024 * 1024
ANH_DIR_NAME = 'de-anh'


def ensure_schema(db):
    db.executescript(
        "CREATE TABLE IF NOT EXISTS bai_kt("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, teacher_id INTEGER NOT NULL,"
        " lop_id INTEGER NOT NULL, tieu_de TEXT, mon TEXT, ma TEXT UNIQUE NOT NULL,"
        " cau_hoi TEXT, nguon TEXT, dang_mo INTEGER DEFAULT 1, created TEXT);"
        "CREATE INDEX IF NOT EXISTS idx_bai_kt_lop ON bai_kt(teacher_id, lop_id);"
        "CREATE TABLE IF NOT EXISTS bai_kt_nop("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, bai_kt_id INTEGER NOT NULL,"
        " ho_ten TEXT NOT NULL, ten_chuan TEXT, ho TEXT, lot TEXT, ten TEXT,"
        " tra_loi TEXT, diem REAL, muc_do TEXT, nhan_xet TEXT, created TEXT);"
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bai_kt_nop_ten ON bai_kt_nop(bai_kt_id, ten_chuan);"
    )
    db.commit()


def dong_bo_lop(db, uid):
    """Tạo/cập nhật lớp từ TKB của giáo viên — không xoá lớp đã có bài kiểm tra."""
    ensure_schema(db)
    rows = db.execute(
        "SELECT lop, khoi, COUNT(*) n FROM tkb WHERE teacher_id=? AND TRIM(COALESCE(lop,''))<>'' "
        "GROUP BY lop, khoi ORDER BY n DESC", (uid,)).fetchall()
    tot = {}
    for r in rows:
        ten = (r['lop'] or '').strip()
        if not ten:
            continue
        if ten not in tot:
            tot[ten] = (r['khoi'] or '').strip()
    for ten, khoi in tot.items():
        cu = db.execute("SELECT id FROM lop WHERE teacher_id=? AND ten=?", (uid, ten)).fetchone()
        if cu:
            if khoi:
                db.execute("UPDATE lop SET khoi=? WHERE id=? AND (khoi IS NULL OR TRIM(khoi)='')",
                           (khoi, cu['id']))
        else:
            db.execute("INSERT INTO lop(teacher_id, ten, khoi) VALUES(?,?,?)", (uid, ten, khoi))
    db.commit()
    return tot


def _lop_cua_gv(db, uid, lop_id):
    return db.execute("SELECT * FROM lop WHERE id=? AND teacher_id=?", (lop_id, uid)).fetchone()


def _de_cua_gv(db, uid, de_id):
    return db.execute("SELECT * FROM bai_kt WHERE id=? AND teacher_id=?", (de_id, uid)).fetchone()


def _anh_dir():
    root = Path(os.environ.get('DB_DIR', 'data')) / ANH_DIR_NAME
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def _luu_file_anh(blob, ten):
    ext, loi = DE.kiem_anh(blob, ten)
    if loi:
        return '', loi
    token = secrets.token_hex(12) + ext
    (_anh_dir() / token).write_bytes(blob)
    try:
        os.chmod(_anh_dir() / token, 0o600)
    except Exception:
        pass
    return token, ''


def _pv_path(uid):
    root = Path(os.environ.get('DB_DIR', 'data')) / 'de-tmp'
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root / ('%s.json' % uid)


def _luu_preview(uid, data):
    _pv_path(uid).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')


def _doc_preview(uid, lop_id):
    p = _pv_path(uid)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None
    if d.get('lop_id') != lop_id:
        return None
    return d


def _xoa_preview(uid):
    p = _pv_path(uid)
    try:
        p.unlink()
    except FileNotFoundError:
        pass


def _anh_form(req, name):
    """Lấy 1 file ảnh từ form. Trả (token, lỗi). Trống → ('', '')."""
    f = req.files.get(name) if req.files else None
    if not f or not (f.filename or '').strip():
        return '', ''
    blob = f.read(DE.ANH_MAX + 1)
    token, err = _luu_file_anh(blob, f.filename or 'anh.jpg')
    return token, err


def _doc_soan_tay(req):
    """Đọc form soạn tay + ảnh câu / ảnh đáp án. Trả (ds, lỗi)."""
    try:
        n = int(req.form.get('so_cau_tay') or 0)
    except (TypeError, ValueError):
        n = 0
    n = max(0, min(40, n))
    ds = []
    for i in range(1, n + 1):
        cau = (req.form.get('cau_%d' % i) or '').strip()
        loai = (req.form.get('loai_%d' % i) or 'tn').strip()
        anh, err = _anh_form(req, 'anh_%d' % i)
        if err:
            return [], 'Câu %d: %s' % (i, err)
        if loai != 'gc' and not cau and not anh:
            continue
        q = {'id': i, 'loai': loai, 'cau': cau, 'anh': anh,
             'lua_chon': {}, 'dap_an': req.form.get('da_%d' % i) or ''}
        if loai == 'gc':
            cot_a, ghep, anh_a = [], [], []
            for j in range(1, 9):
                va = (req.form.get('cotA_%d_%d' % (i, j)) or '').strip()[:200]
                ta, err = _anh_form(req, 'anhA_%d_%d' % (i, j))
                if err:
                    return [], 'Câu %d, cột A ý %d: %s' % (i, j, err)
                if not va and not ta:
                    continue
                cot_a.append(va)
                anh_a.append(ta)
                ghep.append((req.form.get('da_gc_%d_%d' % (i, j)) or '').strip().lower()[:1])
            cot_b, anh_b = [], []
            for j in range(1, 9):
                vb = (req.form.get('cotB_%d_%d' % (i, j)) or '').strip()[:200]
                tb, err = _anh_form(req, 'anhB_%d_%d' % (i, j))
                if err:
                    return [], 'Câu %d, cột B ý %d: %s' % (i, j, err)
                if not vb and not tb:
                    continue
                cot_b.append(vb)
                anh_b.append(tb)
            q['cot_a'] = cot_a
            q['cot_b'] = cot_b
            q['anh_a'] = anh_a
            q['anh_b'] = anh_b
            q['dap_an'] = ','.join('%d%s' % (k, ghep[k - 1])
                                   for k in range(1, len(cot_a) + 1) if ghep[k - 1])
            if not cot_a and not cot_b and not cau and not anh:
                continue
        elif loai == 'tn' or loai not in DE.LOAI_CAU:
            lc, anh_pa = {}, {}
            for chu in DE.CHU:
                v = (req.form.get('pa_%d_%s' % (i, chu)) or '').strip()[:300]
                ta, err = _anh_form(req, 'anh_pa_%d_%s' % (i, chu))
                if err:
                    return [], 'Câu %d, ý %s: %s' % (i, chu, err)
                if v or ta:
                    lc[chu] = v
                if ta:
                    anh_pa[chu] = ta
            q['lua_chon'] = lc
            q['anh_pa'] = anh_pa
        cq, loi = DE.chuan_cau_soan(q, len(ds) + 1)
        if loi:
            return [], loi
        ds.append(cq)
    if not ds:
        return [], 'Hãy nhập ít nhất một câu hỏi.'
    return ds, ''


def _ma_moi(db):
    for _ in range(12):
        ma = secrets.token_urlsafe(8).replace('-', '').replace('_', '')[:10]
        if not db.execute("SELECT 1 FROM bai_kt WHERE ma=?", (ma,)).fetchone():
            return ma
    return secrets.token_hex(8)


@bp.route('/lop-hoc/')
@login_required
def index():
    db, u = get_db(), current_user()
    dong_bo_lop(db, u['id'])
    ds = db.execute("SELECT * FROM lop WHERE teacher_id=? ORDER BY khoi, ten COLLATE NOCASE",
                    (u['id'],)).fetchall()
    dem = {}
    for r in db.execute("SELECT lop_id, COUNT(*) n FROM bai_kt WHERE teacher_id=? GROUP BY lop_id",
                        (u['id'],)):
        dem[r['lop_id']] = r['n']
    lop = []
    for r in ds:
        d = dict(r)
        d['so_de'] = dem.get(r['id'], 0)
        lop.append(d)
    return render_template('lop_hoc.html', lop=lop)


@bp.route('/lop-hoc/<int:lop_id>', methods=['GET', 'POST'])
@login_required
def chi_tiet(lop_id):
    db, u = get_db(), current_user()
    ensure_schema(db)
    lop = _lop_cua_gv(db, u['id'], lop_id)
    if not lop:
        abort(404)
    preview = None
    if request.method == 'POST':
        act = request.form.get('act') or 'doc'
        if act in ('luu', 'tron'):
            pv = _doc_preview(u['id'], lop_id) or {}
            ds = pv.get('cau') or []
            if not ds:
                flash('Chưa có câu hỏi để lưu. Hãy soạn tay hoặc đọc file trước.', 'err')
            elif act == 'tron':
                tron_cau = request.form.get('tron_cau') == '1'
                tron_dap = request.form.get('tron_dap') == '1'
                if not tron_cau and not tron_dap:
                    flash('Hãy chọn trộn câu hỏi và/hoặc trộn đáp án.', 'err')
                    preview = pv
                else:
                    ds = DE.tron_de(ds, tron_cau=tron_cau, tron_dap=tron_dap)
                    pv['cau'] = ds
                    pv['so'] = len(ds)
                    _luu_preview(u['id'], pv)
                    preview = pv
                    flash('Đã trộn đề. Xem lại rồi bấm Lưu bài.', 'ok')
            else:
                tieu = (request.form.get('tieu_de') or pv.get('tieu_de') or 'Bài kiểm tra')[:120]
                mon = (request.form.get('mon') or pv.get('mon') or '')[:80]
                ma = _ma_moi(db)
                cur = db.execute(
                    "INSERT INTO bai_kt(teacher_id,lop_id,tieu_de,mon,ma,cau_hoi,nguon,dang_mo,created)"
                    " VALUES(?,?,?,?,?,?,?,1,?)",
                    (u['id'], lop_id, tieu, mon, ma, DE.dumps_cau(ds), pv.get('nguon') or '',
                     DE.now()))
                db.commit()
                _xoa_preview(u['id'])
                de_id = cur.lastrowid
                flash('Đã tạo bài kiểm tra. Gửi link cho học sinh.', 'ok')
                return redirect(url_for('lop_hoc.de', de_id=de_id))
        elif act == 'soan_tay':
            ds, loi = _doc_soan_tay(request)
            if loi or not ds:
                flash(loi or 'Chưa soạn được câu hỏi.', 'err')
            else:
                tieu = (request.form.get('tieu_de') or 'Bài kiểm tra').strip()[:120] or 'Bài kiểm tra'
                mon = (request.form.get('mon') or '').strip()[:80]
                preview = {
                    'lop_id': lop_id, 'cau': ds, 'nguon': 'soan_tay',
                    'ten_file': '', 'tieu_de': tieu, 'mon': mon, 'so': len(ds),
                }
                _luu_preview(u['id'], preview)
        else:
            f = request.files.get('file')
            tieu = (request.form.get('tieu_de') or '').strip()[:120]
            mon = (request.form.get('mon') or '').strip()[:80]
            so_cau, so_dap_an = DE.chuan_so(request.form.get('so_cau'), request.form.get('so_dap_an'))
            if not f or not (f.filename or '').strip():
                flash('Hãy chọn file Word .docx hoặc PDF (bài học hoặc đề có đáp án đậm/gạch chân).', 'err')
            else:
                data = f.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    flash('File vượt quá 8 MB.', 'err')
                else:
                    ds, nguon, loi = DE.doc_file(data, f.filename or '',
                                                 so_cau=so_cau, so_dap_an=so_dap_an)
                    if loi or not ds:
                        flash(loi or 'Không tạo được câu hỏi từ file này.', 'err')
                    else:
                        preview = {
                            'lop_id': lop_id,
                            'cau': ds, 'nguon': nguon, 'ten_file': (f.filename or '')[:120],
                            'tieu_de': tieu or ((f.filename or 'Bài kiểm tra').rsplit('.', 1)[0][:80]),
                            'mon': mon, 'so': len(ds),
                        }
                        _luu_preview(u['id'], preview)
    de = [dict(r) for r in db.execute(
        "SELECT id, tieu_de, mon, ma, dang_mo, created, "
        "(SELECT COUNT(*) FROM bai_kt_nop n WHERE n.bai_kt_id=bai_kt.id) so_nop "
        "FROM bai_kt WHERE teacher_id=? AND lop_id=? ORDER BY id DESC",
        (u['id'], lop_id)).fetchall()]
    return render_template('lop_hoc_lop.html', lop=lop, de=de, preview=preview)


@bp.route('/lop-hoc/de/<int:de_id>', methods=['GET', 'POST'])
@login_required
def de(de_id):
    db, u = get_db(), current_user()
    ensure_schema(db)
    row = _de_cua_gv(db, u['id'], de_id)
    if not row:
        abort(404)
    lop = _lop_cua_gv(db, u['id'], row['lop_id'])
    if request.method == 'POST':
        act = request.form.get('act')
        if act == 'dong':
            db.execute("UPDATE bai_kt SET dang_mo=0 WHERE id=?", (de_id,))
            db.commit()
            flash('Đã đóng bài — học sinh không nộp thêm được.', 'ok')
        elif act == 'mo':
            db.execute("UPDATE bai_kt SET dang_mo=1 WHERE id=?", (de_id,))
            db.commit()
            flash('Đã mở lại bài kiểm tra.', 'ok')
        elif act == 'xoa':
            db.execute("DELETE FROM bai_kt_nop WHERE bai_kt_id=?", (de_id,))
            db.execute("DELETE FROM bai_kt WHERE id=? AND teacher_id=?", (de_id, u['id']))
            db.commit()
            flash('Đã xoá bài kiểm tra.', 'ok')
            return redirect(url_for('lop_hoc.chi_tiet', lop_id=row['lop_id']))
        return redirect(url_for('lop_hoc.de', de_id=de_id))
    cau = DE.loads_cau(row['cau_hoi'])
    nop = [dict(r) for r in db.execute(
        "SELECT * FROM bai_kt_nop WHERE bai_kt_id=?", (de_id,)).fetchall()]
    nop = DE.sap_xep_hs(nop)
    link = url_for('lop_hoc.lam_bai', ma=row['ma'], _external=True)
    return render_template('lop_hoc_de.html', de=row, lop=lop, cau=cau, nop=nop, link=link)


@bp.route('/lop-hoc/de/<int:de_id>/excel')
@login_required
def excel(de_id):
    db, u = get_db(), current_user()
    row = _de_cua_gv(db, u['id'], de_id)
    if not row:
        abort(404)
    lop = _lop_cua_gv(db, u['id'], row['lop_id'])
    nop = [dict(r) for r in db.execute(
        "SELECT * FROM bai_kt_nop WHERE bai_kt_id=?", (de_id,)).fetchall()]
    bio = DE.xuat_excel(nop, {'tieu_de': row['tieu_de'] or 'Kết quả bài kiểm tra',
                              'lop': lop['ten'] if lop else '', 'mon': row['mon'] or ''})
    ten = 'Ket-qua-%s.xlsx' % re.sub(r'[^A-Za-z0-9]+', '-', (row['tieu_de'] or 'bai-kt')[:40])
    return send_file(bio, as_attachment=True, download_name=ten,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/bai-kt-anh/<ten>')
def anh(ten):
    """Ảnh trong đề — học sinh cần xem khi làm bài, không cần đăng nhập."""
    if not re.fullmatch(r'[a-f0-9]{24}\.(jpg|png|webp|gif)', ten or '', re.I):
        abort(404)
    p = _anh_dir() / ten
    if not p.is_file():
        abort(404)
    mime = {'.jpg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
            '.gif': 'image/gif'}.get(p.suffix.lower(), 'application/octet-stream')
    return send_file(p, mimetype=mime)


@bp.route('/bai-kt/<ma>', methods=['GET', 'POST'])
def lam_bai(ma):
    """Trang học sinh — không cần đăng nhập."""
    db = get_db()
    ensure_schema(db)
    if not re.fullmatch(r'[A-Za-z0-9]{6,16}', ma or ''):
        abort(404)
    row = db.execute("SELECT * FROM bai_kt WHERE ma=?", (ma,)).fetchone()
    if not row:
        abort(404)
    lop = db.execute("SELECT * FROM lop WHERE id=?", (row['lop_id'],)).fetchone()
    cau_goc = DE.loads_cau(row['cau_hoi'])
    kq = None
    loi = ''
    ho_ten = (request.form.get('ho_ten') or request.args.get('ho_ten') or '').strip()[:80]
    buoc = 'ten'

    def de_hs(ten):
        tu = [t for t in (ten or '').split() if t]
        if len(tu) < 2:
            return cau_goc
        return DE.de_cho_hs(cau_goc, row['ma'], DE.ten_chuan(ten))

    if request.method == 'POST':
        if not allow_request('bai_kt', request.remote_addr, 40, 600):
            loi = 'Thử quá nhiều lần. Em đợi vài phút rồi làm lại.'
        elif not row['dang_mo']:
            loi = 'Bài kiểm tra đã đóng.'
        elif request.form.get('act') == 'nop':
            ho_ten = (request.form.get('ho_ten') or '').strip()[:80]
            tu = [t for t in ho_ten.split() if t]
            if len(tu) < 2 or len(ho_ten) < 4:
                loi = 'Em hãy nhập đủ họ và tên (ví dụ: Nguyễn Văn An).'
                buoc = 'lam'
            else:
                chuan = DE.ten_chuan(ho_ten)
                if db.execute("SELECT 1 FROM bai_kt_nop WHERE bai_kt_id=? AND ten_chuan=?",
                              (row['id'], chuan)).fetchone():
                    loi = 'Em đã nộp bài này rồi.'
                    buoc = 'xong'
                else:
                    cau = de_hs(ho_ten)
                    tra = {}
                    for q in cau:
                        loai = DE.loai_cau(q)
                        if loai == 'gc':
                            mp = {}
                            for j in range(1, len(q.get('cot_a') or []) + 1):
                                chu = (request.form.get('c%d_%d' % (q['id'], j)) or '').strip().lower()[:1]
                                if chu:
                                    mp[j] = chu
                            tra[str(q['id'])] = DE.dumps_ghep(mp)
                        else:
                            raw = request.form.get('c' + str(q['id'])) or ''
                            tra[str(q['id'])] = raw[:500] if loai in ('dk', 'tl') else raw[:2]
                    diem, dung, n, _ct = DE.cham_diem(cau, tra)
                    if diem is None:
                        nx, md = '', ''
                    else:
                        nx, md = DE.nhan_xet_bai(diem, row['mon'] or '')
                    ho, lot, ten = DE.tach_ten(ho_ten)
                    try:
                        db.execute(
                            "INSERT INTO bai_kt_nop(bai_kt_id,ho_ten,ten_chuan,ho,lot,ten,tra_loi,"
                            "diem,muc_do,nhan_xet,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (row['id'], ho_ten, chuan, ho, lot, ten, json.dumps(tra, ensure_ascii=False),
                             diem, md, nx, DE.now()))
                        db.commit()
                    except Exception:
                        db.rollback()
                        loi = 'Em đã nộp bài này rồi.'
                        buoc = 'xong'
                    else:
                        kq = {'diem': diem, 'dung': dung, 'n': n, 'nhan_xet': nx, 'muc_do': md,
                              'ho_ten': ho_ten}
                        buoc = 'xong'
        else:
            tu = [t for t in ho_ten.split() if t]
            if len(tu) < 2:
                loi = 'Em hãy nhập đủ họ và tên.'
            else:
                chuan = DE.ten_chuan(ho_ten)
                if db.execute("SELECT 1 FROM bai_kt_nop WHERE bai_kt_id=? AND ten_chuan=?",
                              (row['id'], chuan)).fetchone():
                    loi = 'Em đã nộp bài này rồi.'
                    buoc = 'xong'
                else:
                    buoc = 'lam'
    hs_cau = DE.an_dap_an(de_hs(ho_ten))
    return render_template('bai_kt_hs.html', de=row, lop=lop, cau=hs_cau, buoc=buoc,
                           ho_ten=ho_ten, kq=kq, loi=loi)

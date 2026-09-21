"""Trang “🔎 Kiểm tra trùng lặp / đạo văn”.

Ba việc trong một chỗ:
  · Đối chiếu một bài với KHO của thầy/cô (KHDH đã lưu + khung/văn bản của Bộ) — luôn chạy.
  · Đối chiếu NGUỒN TRÊN INTERNET (gửi trích đoạn câu nghi vấn ra máy tìm kiếm, tải trang về
    rồi so khớp) — chỉ chạy khi thầy/cô tích chọn.
  · SO NHIỀU BÀI NỘP VỚI NHAU (≥ 2 bài) để phát hiện học sinh chép bài của nhau.

Xử lý nặng (tra Internet) chạy ở luồng riêng, trang kết quả tự làm mới để hiện tiến độ —
để không giữ kết nối HTTP quá lâu. Tạo và XEM TRỰC TUYẾN miễn phí; chỉ khi TẢI báo cáo Word
mới tính 1 lượt (M14).
"""
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from flask import (Blueprint, render_template, request, session, flash, redirect,
                   url_for, send_file, abort)

from ..auth import login_required, current_user
from ..db import get_db
from ..modules import trung_lap as TL
from ..modules import billing as BL

bp = Blueprint('trung_lap', __name__, url_prefix='/trung-lap')
MENU = {'label': 'Kiểm tra trùng lặp / đạo văn', 'endpoint': 'trung_lap.index', 'icon': '🔎'}

TOKEN_RE = re.compile(r'^[0-9a-f]{32}$')
TOI_DA_BAI = 12             # số bài nộp tối đa trong 1 lượt so


def folder():
    root = Path(os.environ.get('DB_DIR', 'data')) / TL.TMP_DIR
    root.mkdir(parents=True, exist_ok=True)
    return root


def _duong(token):
    return folder() / (token + '.json')


def _ghi(token, ho_so):
    """Ghi hồ sơ kết quả (ghi ra tệp tạm rồi thay thế để luồng đọc không thấy tệp dở)."""
    p = _duong(token)
    tam = p.with_suffix('.tam')
    tam.write_text(json.dumps(ho_so, ensure_ascii=False), encoding='utf-8')
    os.replace(tam, p)


def _doc(token, uid):
    if not TOKEN_RE.match(token or ''):
        abort(404)
    p = _duong(token)
    if not p.exists():
        return None
    try:
        h = json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None
    if h.get('uid') != uid:          # không cho xem kết quả của người khác
        abort(403)
    return h


def _nhat_ky_them(ho_so, viec, du_lieu=''):
    dong = {'luc': time.strftime('%H:%M:%S'), 'viec': viec, 'du_lieu': str(du_lieu)[:120]}
    ho_so.setdefault('nhat_ky', []).append(dong)
    ho_so['nhat_ky'] = ho_so['nhat_ky'][-40:]


# ------------------------------------------------------------------ tra Internet ở luồng riêng
def _chay_internet(token, uid, doan, che_do="tieu_chuan"):
    """Tra Internet (nhiều nguồn, nhiều trang) rồi gộp kết quả vào hồ sơ — chạy ở luồng riêng."""
    def gio(viec, du_lieu=''):
        try:
            h = json.loads(_duong(token).read_text(encoding='utf-8'))
            _nhat_ky_them(h, viec, du_lieu)
            _ghi(token, h)
        except Exception:
            pass

    try:
        it = TL.doi_chieu_internet(doan, gio=gio, che_do=che_do)
        h = json.loads(_duong(token).read_text(encoding='utf-8'))
        TL.gop_internet(h['kq'], it)
        _nhat_ky_them(h, 'xong', 'tra %d câu hỏi · %d kết quả · tải %d trang · %d giây'
                      % (it.get('so_cau_hoi', 0), it.get('so_ket_qua', 0),
                         it.get('so_trang_tai', 0), it.get('giay', 0)))
        h['trang_thai'] = 'xong'
        h['xong_luc'] = time.strftime('%H:%M:%S')
        _ghi(token, h)
    except Exception as e:
        try:
            h = json.loads(_duong(token).read_text(encoding='utf-8'))
            _nhat_ky_them(h, 'loi', type(e).__name__)
            h['trang_thai'] = 'xong'
            h['loi_internet'] = ('Phần đối chiếu Internet gặp lỗi (%s). Kết quả đối chiếu kho '
                                 'của thầy/cô vẫn dùng được.' % type(e).__name__)
            _ghi(token, h)
        except Exception:
            pass


# ------------------------------------------------------------------ trang chính
@bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if request.method != 'POST':
        return render_template('trung_lap.html', kq=None, nguoi=_ten_nguoi(),
                               thong_tin=TL.thong_tin(), che_do=TL.CHE_DO,
                               che_do_chon='tieu_chuan', nguon_api=TL.nguon_api())
    u = current_user()
    kieu = (request.form.get('kieu') or 'mot_bai').strip()
    internet = (request.form.get('internet') or '') not in ('', '0', 'off')
    che_do = (request.form.get('che_do') or 'tieu_chuan').strip()
    if che_do not in TL.CHE_DO:
        che_do = 'tieu_chuan'
    nguon = TL.kho_he_thong(u['id'])
    if kieu == 'nhieu_bai':
        return _xu_ly_nhieu(u, nguon)
    try:
        doan, ten, loi = TL.tai_lieu(request.files.get('file'), request.form.get('text'))
    except Exception:
        doan, ten, loi = [], '', 'Không đọc được nội dung thầy/cô gửi lên.'
    if loi:
        flash(loi, 'err')
        return render_template('trung_lap.html', kq=None, nguoi=_ten_nguoi(), che_do=TL.CHE_DO,
                               che_do_chon=che_do, thong_tin=TL.thong_tin(), kieu=kieu,
                               internet=internet, nguon_api=TL.nguon_api())
    kq = TL.phan_tich_mot_bai(doan, ten, nguon=nguon)
    token = uuid.uuid4().hex
    ho_so = {'token': token, 'uid': u['id'], 'luc': time.strftime('%H:%M %d/%m/%Y'),
             'kieu': 'mot_bai', 'ten': ten, 'internet_yeu_cau': bool(internet),
             'trang_thai': 'dang_chay' if internet else 'xong', 'kq': kq, 'nhat_ky': []}
    ho_so['che_do'] = che_do
    if internet:
        _ts = TL.thong_so_che_do(che_do)
        _nhat_ky_them(ho_so, 'bat_dau', 'chế độ %s — %s' % (_ts['ten'], _ts['mo_ta']))
    _ghi(token, ho_so)
    if internet:
        threading.Thread(target=_chay_internet, args=(token, u['id'], doan, che_do),
                         daemon=True).start()
    return redirect(url_for('trung_lap.ket_qua', token=token))


def _xu_ly_nhieu(u, nguon):
    """So nhiều bài nộp với nhau."""
    cac = request.files.getlist('files')
    cac = [f for f in cac if (getattr(f, 'filename', '') or '').strip()]
    dan = (request.form.get('text_nhieu') or '').strip()
    if dan:
        # mỗi bài cách nhau bằng một dòng có 3 dấu gạch trở lên
        for i, phan in enumerate(re.split(r'\n\s*-{3,}\s*\n', dan)):
            if phan.strip():
                cac.append(_Gia(phan.strip(), 'Bài dán %d' % (i + 1)))
    if len(cac) < 2:
        flash('Cần ít nhất 2 bài để so với nhau. Thầy/cô gửi 2 tệp .docx/.pdf, hoặc dán các bài '
              'cách nhau bằng một dòng có ba dấu gạch (---).', 'err')
        return render_template('trung_lap.html', kq=None, nguoi=_ten_nguoi(), che_do=TL.CHE_DO,
                               che_do_chon='tieu_chuan', thong_tin=TL.thong_tin(), kieu='nhieu_bai',
                               nguon_api=TL.nguon_api())
    if len(cac) > TOI_DA_BAI:
        flash('Mỗi lượt so tối đa %d bài. Thầy/cô chia thành các lượt nhỏ hơn.' % TOI_DA_BAI, 'err')
        return render_template('trung_lap.html', kq=None, nguoi=_ten_nguoi(), che_do=TL.CHE_DO,
                               che_do_chon='tieu_chuan', thong_tin=TL.thong_tin(), kieu='nhieu_bai',
                               nguon_api=TL.nguon_api())
    bai, loi_ds = [], []
    for f in cac:
        try:
            doan, ten, loi = TL.tai_lieu(f, '')
        except Exception:
            doan, ten, loi = [], getattr(f, 'filename', ''), 'Không đọc được tệp này.'
        if loi:
            loi_ds.append('%s: %s' % (ten, loi))
            continue
        bai.append((ten, doan))
    if loi_ds:
        flash(' '.join(loi_ds[:4]), 'err')
    if len(bai) < 2:
        flash('Cần ít nhất 2 bài đọc được nội dung để so với nhau.', 'err')
        return render_template('trung_lap.html', kq=None, nguoi=_ten_nguoi(), che_do=TL.CHE_DO,
                               che_do_chon='tieu_chuan', thong_tin=TL.thong_tin(), kieu='nhieu_bai',
                               nguon_api=TL.nguon_api())
    kq = TL.phan_tich_nhieu_bai(bai, nguon=nguon)
    token = uuid.uuid4().hex
    ho_so = {'token': token, 'uid': u['id'], 'luc': time.strftime('%H:%M %d/%m/%Y'),
             'kieu': 'nhieu_bai', 'ten': '%d bài nộp' % len(bai),
             'trang_thai': 'xong', 'kq': kq, 'nhat_ky': []}
    _ghi(token, ho_so)
    return redirect(url_for('trung_lap.ket_qua', token=token))


class _Gia:
    """Giả lập đối tượng tệp cho phần văn bản dán trực tiếp."""

    def __init__(self, chu, ten):
        self._chu = chu.encode('utf-8')
        self.filename = ten + '.txt'

    def read(self, n=-1):
        return self._chu


def _ten_nguoi():
    u = current_user()
    return (u['fullname'] or u['username']) if u else ''


# ------------------------------------------------------------------ xem kết quả (miễn phí)
@bp.route('/<token>')
@login_required
def ket_qua(token):
    u = current_user()
    h = _doc(token, u['id'])
    if not h:
        flash('Không tìm thấy kết quả này (kết quả chỉ lưu tạm trên máy chủ).', 'err')
        return redirect(url_for('trung_lap.index'))
    db = get_db()
    return render_template('trung_lap_kq.html', h=h, kq=h['kq'], token=token,
                           nguoi=_ten_nguoi(), da_tra=BL.da_tra_luot(db, u['id'], token),
                           con_lai=BL.remaining(u), la_pro=BL.is_pro(u),
                           che_do=TL.CHE_DO, nguon_api=TL.nguon_api())


# ------------------------------------------------------------------ tải báo cáo Word (1 lượt)
@bp.route('/<token>/xuat.docx')
@login_required
def xuat(token):
    u = current_user()
    h = _doc(token, u['id'])
    if not h:
        flash('Không tìm thấy kết quả này để xuất báo cáo.', 'err')
        return redirect(url_for('trung_lap.index'))
    if not BL.tra_luot_tai(get_db(), u, 'trunglap', token, 'Báo cáo trùng lặp/đạo văn'):
        flash(BL.thong_bao_het(), 'err')
        return redirect(url_for('core.nang_cap', need='trunglap'))
    kq = h['kq']
    if h.get('trang_thai') != 'xong':
        flash('Phần đối chiếu Internet đang chạy — báo cáo tải về sẽ gồm phần đã có.', 'ok')
    bio = TL.xuat_docx(kq)
    return send_file(bio, as_attachment=True, download_name=TL.ten_tep_docx(kq),
                     mimetype='application/vnd.openxmlformats-officedocument.wordprocessingml.document')


@bp.route('/<token>/chay-lai', methods=['POST'])
@login_required
def chay_lai(token):
    """Chạy lại phần đối chiếu Internet cho một kết quả đã có (không tính thêm lượt)."""
    u = current_user()
    h = _doc(token, u['id'])
    if not h:
        flash('Không tìm thấy kết quả này.', 'err')
        return redirect(url_for('trung_lap.index'))
    if h['kq'].get('kieu') != 'mot_bai':
        flash('Chỉ đối chiếu Internet cho trường hợp kiểm tra một bài.', 'err')
        return redirect(url_for('trung_lap.ket_qua', token=token))
    che_do = (request.form.get('che_do') or h.get('che_do') or 'tieu_chuan').strip()
    if che_do not in TL.CHE_DO:
        che_do = 'tieu_chuan'
    h['che_do'] = che_do
    h['trang_thai'] = 'dang_chay'
    h['nhat_ky'] = []
    h['kq']['internet'] = None
    _nhat_ky_them(h, 'bat_dau', 'chạy lại phần đối chiếu Internet — chế độ %s'
                  % TL.thong_so_che_do(che_do)['ten'])
    _ghi(token, h)
    threading.Thread(target=_chay_internet, args=(token, u['id'], h['kq']['doan'], che_do),
                     daemon=True).start()
    return redirect(url_for('trung_lap.ket_qua', token=token))

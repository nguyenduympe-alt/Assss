"""Báo cáo dung lượng máy chủ (ổ đĩa + RAM + thư mục dữ liệu) — để kịp nâng cấp."""
import os
from pathlib import Path

from ..db import DB_DIR, DB_PATH


def _byte(n):
    n = max(0, int(n or 0))
    if n < 1024:
        return '%d B' % n
    for dv, ten in ((1024 ** 3, 'GB'), (1024 ** 2, 'MB'), (1024, 'KB')):
        if n >= dv:
            x = n / float(dv)
            return ('%.1f %s' % (x, ten)) if x < 10 else ('%.0f %s' % (x, ten))
    return '%d B' % n


def _walk(path, gioi=80000):
    tong, n = 0, 0
    p = Path(path)
    if not p.exists():
        return 0, 0
    if p.is_file():
        try:
            return p.stat().st_size, 1
        except OSError:
            return 0, 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            n += 1
            if n > gioi:
                break
            try:
                tong += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
        if n > gioi:
            break
    return tong, n


def _mem():
    tong = trong = 0
    try:
        with open('/proc/meminfo', encoding='utf-8') as f:
            so = {}
            for dong in f:
                p = dong.split(':')
                if len(p) == 2:
                    so[p[0].strip()] = int(p[1].split()[0])
            tong = so.get('MemTotal', 0) * 1024
            trong = so.get('MemAvailable', 0) * 1024
    except OSError:
        pass
    return tong, trong


def _muc(con_byte, pct_dung):
    """ok / warn / danger — cảnh báo sớm để kịp nâng cấp."""
    gb = 1024 ** 3
    if con_byte < 0.6 * gb or pct_dung >= 92:
        return 'danger', 'Ổ gần đầy — nâng cấp dung lượng ngay.'
    if con_byte < 2 * gb or pct_dung >= 80:
        return 'warn', 'Ổ còn ít chỗ. Nên nâng cấp trước khi đầy.'
    if con_byte < 4 * gb or pct_dung >= 70:
        return 'warn', 'Ổ còn dưới 4 GB trống. Theo dõi để nâng cấp kịp.'
    return 'ok', 'Ổ còn chỗ. Chưa cần nâng cấp.'


def canh_bao_o():
    """Chỉ đo ổ (statvfs) — nhẹ, dùng cho badge menu. Trả 'ok'/'warn'/'danger'."""
    goc = Path(DB_DIR).resolve() if DB_DIR else Path('data')
    try:
        du = os.statvfs(str(goc if goc.exists() else '/'))
    except OSError:
        try:
            du = os.statvfs('/')
        except OSError:
            return 'ok', 0, 0
    tong = du.f_frsize * du.f_blocks
    con = du.f_frsize * du.f_bavail
    pct = (tong - con) * 100.0 / tong if tong else 0
    muc, _ = _muc(con, pct)
    return muc, con, pct


def bao_cao():
    """Số liệu đo trên máy đang chạy. Không gọi mạng."""
    goc = Path(DB_DIR).resolve() if DB_DIR else Path('data')
    try:
        du = os.statvfs(str(goc if goc.exists() else '/'))
    except OSError:
        du = os.statvfs('/')
    tong = du.f_frsize * du.f_blocks
    con = du.f_frsize * du.f_bavail
    dung = max(0, tong - con)
    pct = round(dung * 100.0 / tong, 1) if tong else 0
    muc, loi_khuyen = _muc(con, pct)

    db_sz, _ = _walk(DB_PATH)
    # WAL / SHM đi kèm sqlite
    for duoi in ('-wal', '-shm'):
        p = Path(str(DB_PATH) + duoi)
        if p.exists():
            try:
                db_sz += p.stat().st_size
            except OSError:
                pass
    kho, n_kho = _walk(goc / 'khdh')
    tmp1, n1 = _walk(goc / 'digital-tmp')
    tmp2, n2 = _walk(goc / 'de-tmp')
    app_dir = Path(__file__).resolve().parents[1]
    app_sz, n_app = _walk(app_dir)
    ram_tong, ram_con = _mem()
    ram_dung = max(0, ram_tong - ram_con) if ram_tong else 0
    ram_pct = round(ram_dung * 100.0 / ram_tong, 1) if ram_tong else 0

    hang = [
        {'ten': 'Cơ sở dữ liệu (điểm, TKB, bài kiểm tra…)', 'byte': db_sz, 'so_tep': 1},
        {'ten': 'Kho KHDH / giáo án đã lưu', 'byte': kho, 'so_tep': n_kho},
        {'ten': 'Tệp tạm (rà soát, đề xem trước)', 'byte': tmp1 + tmp2, 'so_tep': n1 + n2},
        {'ten': 'Mã nguồn & tài nguyên ứng dụng', 'byte': app_sz, 'so_tep': n_app},
    ]
    for h in hang:
        h['hien'] = _byte(h['byte'])
    du_lieu = db_sz + kho + tmp1 + tmp2

    return {
        'o_tong': tong, 'o_dung': dung, 'o_con': con, 'o_pct': pct,
        'o_tong_h': _byte(tong), 'o_dung_h': _byte(dung), 'o_con_h': _byte(con),
        'du_lieu': du_lieu, 'du_lieu_h': _byte(du_lieu),
        'hang': hang,
        'muc': muc, 'loi_khuyen': loi_khuyen,
        'ram_tong': ram_tong, 'ram_con': ram_con, 'ram_dung': ram_dung, 'ram_pct': ram_pct,
        'ram_tong_h': _byte(ram_tong), 'ram_con_h': _byte(ram_con), 'ram_dung_h': _byte(ram_dung),
        'thu_muc_du_lieu': str(goc),
        'canh_bao': muc != 'ok',
    }

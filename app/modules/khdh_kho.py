"""(M12) Kho KHDH theo môn: mỗi môn + khối giữ 1 KHDH đang dùng.

- Giáo viên tạo môn (ví dụ Toán · khối 4) rồi tải 1 KHDH (kế hoạch dạy học / phân phối
  chương trình hoặc giáo án) lên cho môn đó. Mỗi môn + khối có đúng một bản ĐANG DÙNG.
- Hệ thống đọc tựa bài trong KHDH để suy ra **số tiết mỗi tuần** của môn; giáo viên sửa tay được.
- Trang Thời khoá biểu chọn môn đã tạo, nhập lớp dạy rồi **đối chiếu** số tiết đã xếp trong tuần
  với số tiết/tuần ghi trong KHDH (thiếu / đủ / thừa tiết).

Không phát sinh lượt sử dụng: lưu kho là lưu trữ; lượt chỉ trừ khi tạo bản tích hợp NLS/AI/STEM.
"""
import datetime
import os
import re
import unicodedata
from pathlib import Path

from . import digital_plan as DP

SO_TUAN = 35        # số tuần thực học chuẩn khi KHDH chỉ ghi số tiết PP (1..140)
KHOI = [str(i) for i in range(1, 13)]


# ---------------- tiện ích ----------------
def chuan(text):
    """Chuẩn hoá tên môn để so trùng: bỏ dấu, gộp khoảng trắng, viết thường."""
    t = unicodedata.normalize('NFD', (text or '').lower().replace('đ', 'd'))
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', t).strip()


def ten_mon(mon, khoi):
    return '%s — khối %s' % ((mon or '').strip(), (khoi or '').strip())


def hom_nay():
    return datetime.date.today().isoformat()


def folder(teacher_id):
    """Thư mục lưu tệp KHDH của một giáo viên (không nằm trong thư mục tạm)."""
    root = Path(os.environ.get('DB_DIR', 'data')) / 'khdh' / str(teacher_id)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def rows_tu_tep(data):
    """Đọc tệp Word .docx đã tải lên → danh sách dòng bài học (dùng lại bộ đọc của KHDH)."""
    return DP.extract_rows(DP.read_word(data))


def so_tiet_tuan(rows):
    """Suy ra số tiết mỗi tuần của môn từ các dòng KHDH; None nếu chưa đủ căn cứ."""
    theo_tuan, dem_tuan, so_le = {}, {}, []
    for r in rows:
        w = (r.get('week') or '').strip()
        m = re.search(r'\d+', (r.get('periods') or '').strip())
        n = None
        if m:
            v = int(m.group(0))
            if 1 <= v <= 12:                      # ô "thời lượng / số tiết" dạng "4 tiết"
                n = v
                so_le.append(v)
        if w:
            dem_tuan[w] = dem_tuan.get(w, 0) + 1
            if n:
                theo_tuan[w] = theo_tuan.get(w, 0) + n
    for src in (theo_tuan, dem_tuan):             # ưu tiên cột "số tiết", rồi đếm số dòng/tuần
        vals = [v for v in src.values() if v]
        if vals:
            return max(set(vals), key=vals.count)
    if so_le:
        return max(set(so_le), key=so_le.count)
    nums = []
    for r in rows:                                # KHDH chỉ ghi số tiết PP tăng dần (1..140)
        m = re.search(r'\d+', (r.get('periods') or '').strip())
        if m:
            nums.append(int(m.group(0)))
    if len(nums) >= 10 and max(nums) > 12:
        return max(1, round((max(nums) - min(nums) + 1) / SO_TUAN))
    return None


# ---------------- đọc kho ----------------
def ban_dang_dung(db, teacher_id, mon, khoi):
    return db.execute('SELECT * FROM khdh WHERE teacher_id=? AND mon_chuan=? AND khoi=?'
                      ' AND dang_dung=1', (teacher_id, chuan(mon), str(khoi))).fetchone()


def tim(db, teacher_id, kid):
    return db.execute('SELECT * FROM khdh WHERE id=? AND teacher_id=?', (kid, teacher_id)).fetchone()


def cac_ban(db, teacher_id, mon, khoi):
    """Mọi phiên bản của một môn + khối, bản đang dùng lên đầu."""
    return db.execute('SELECT * FROM khdh WHERE teacher_id=? AND mon_chuan=? AND khoi=?'
                      ' ORDER BY dang_dung DESC, phien_ban DESC, id DESC',
                      (teacher_id, chuan(mon), str(khoi))).fetchall()


def danh_sach(db, teacher_id):
    """Các môn đang dùng (mỗi môn + khối 1 dòng), sắp theo tên môn rồi khối."""
    return db.execute('SELECT * FROM khdh WHERE teacher_id=? AND dang_dung=1'
                      ' ORDER BY mon COLLATE NOCASE, CAST(khoi AS INTEGER), id', (teacher_id,)).fetchall()


def dem_ban(db, teacher_id, mon, khoi):
    return db.execute('SELECT COUNT(*) FROM khdh WHERE teacher_id=? AND mon_chuan=? AND khoi=?',
                      (teacher_id, chuan(mon), str(khoi))).fetchone()[0]


def chi_tiet(db, teacher_id, kid):
    """Chi tiết một bản: kèm danh sách bản khác của cùng môn + khối."""
    row = tim(db, teacher_id, kid)
    if not row:
        return None, []
    return row, [r for r in cac_ban(db, teacher_id, row['mon'], row['khoi']) if r['id'] != row['id']]


# ---------------- ghi kho ----------------
def luu(db, teacher_id, mon, khoi, ten_file, data, rows=None, loai='ppct', tiet_tuan=None,
        thay_the=True, so_tiet_tay=None):
    """Lưu 1 KHDH cho môn + khối.

    thay_the=True  → xoá bản đang dùng cũ (và tệp của nó), bản mới là phiên bản kế tiếp.
    thay_the=False → giữ bản cũ làm lịch sử (đánh số phiên bản), bản mới thành bản đang dùng.
    """
    mon = (mon or '').strip()
    khoi = str(khoi or '').strip()
    rows = rows if rows is not None else rows_tu_tep(data)
    cu = ban_dang_dung(db, teacher_id, mon, khoi)
    phien_ban = 1
    if cu:
        phien_ban = (cu['phien_ban'] or 1) + 1
        if thay_the:
            _xoa_tep(teacher_id, cu['luu'])
            db.execute('DELETE FROM khdh WHERE id=?', (cu['id'],))
        else:
            db.execute('UPDATE khdh SET dang_dung=0 WHERE id=?', (cu['id'],))
    con_lai = danh_sach(db, teacher_id)
    if tiet_tuan is None and not any(chuan(r['mon']) == chuan(mon) and r['khoi'] == khoi for r in con_lai):
        tiet_tuan = so_tiet_tuan(rows)
    tiet_tay = 1 if so_tiet_tay is not None else 0
    if so_tiet_tay is not None:
        tiet_tuan = so_tiet_tay
    cur = db.execute(
        'INSERT INTO khdh(teacher_id,mon,mon_chuan,khoi,ten_file,luu,loai,so_dong,so_tiet_tuan,'
        ' tiet_tuan_tay,phien_ban,dang_dung,created,updated)'
        " VALUES(?,?,?,?,?,'',?,?,?,?,?,1,?,?)",
        (teacher_id, mon, chuan(mon), khoi, (ten_file or '')[:200], loai or 'ppct', len(rows),
         tiet_tuan, tiet_tay, phien_ban, hom_nay(), hom_nay()))
    kid = cur.lastrowid
    ten_luu = 'khdh-%d.docx' % kid
    (folder(teacher_id) / ten_luu).write_bytes(data)
    db.execute('UPDATE khdh SET luu=? WHERE id=?', (ten_luu, kid))
    db.commit()
    return kid


def tao_mon(db, teacher_id, mon, khoi):
    """Ghi nhận một môn chưa có KHDH (giáo viên nhập môn mới ở Thời khoá biểu)."""
    mon, khoi = (mon or '').strip(), str(khoi or '').strip()
    if not mon or khoi not in KHOI:
        return None
    cu = ban_dang_dung(db, teacher_id, mon, khoi)
    if cu:
        return cu['id']
    cur = db.execute('INSERT INTO khdh(teacher_id,mon,mon_chuan,khoi,ten_file,luu,loai,so_dong,'
                     ' so_tiet_tuan,tiet_tuan_tay,phien_ban,dang_dung,created,updated)'
                     " VALUES(?,?,?,?,'','','ppct',0,NULL,0,0,1,?,?)",
                     (teacher_id, mon, chuan(mon), khoi, hom_nay(), hom_nay()))
    db.commit()
    return cur.lastrowid


def dat_tiet_tuan(db, teacher_id, kid, so):
    """Giáo viên tự nhập số tiết/tuần (so=None → quay lại để hệ thống suy ra)."""
    row = tim(db, teacher_id, kid)
    if not row:
        return False
    if so is None:
        rows = _doc_lai_tep(teacher_id, row)
        db.execute('UPDATE khdh SET so_tiet_tuan=?, tiet_tuan_tay=0, updated=? WHERE id=?',
                   (so_tiet_tuan(rows) if rows else None, hom_nay(), kid))
    else:
        db.execute('UPDATE khdh SET so_tiet_tuan=?, tiet_tuan_tay=1, updated=? WHERE id=?',
                   (int(so), hom_nay(), kid))
    db.commit()
    return True


def doi_ban(db, teacher_id, kid):
    """Chuyển bản đang dùng sang một phiên bản khác của cùng môn + khối."""
    row = tim(db, teacher_id, kid)
    if not row:
        return False
    db.execute('UPDATE khdh SET dang_dung=0 WHERE teacher_id=? AND mon_chuan=? AND khoi=?',
               (teacher_id, row['mon_chuan'], row['khoi']))
    db.execute('UPDATE khdh SET dang_dung=1 WHERE id=?', (kid,))
    db.commit()
    return True


def xoa(db, teacher_id, kid):
    """Xoá môn khỏi kho: xoá mọi phiên bản của đúng môn + khối đó và tệp kèm theo."""
    row = tim(db, teacher_id, kid)
    if not row:
        return False
    for r in cac_ban(db, teacher_id, row['mon'], row['khoi']):
        _xoa_tep(teacher_id, r['luu'])
    db.execute('DELETE FROM khdh WHERE teacher_id=? AND mon_chuan=? AND khoi=?',
               (teacher_id, row['mon_chuan'], row['khoi']))
    db.commit()
    return True


def xoa_ban(db, teacher_id, kid):
    """Xoá riêng một phiên bản (không xoá cả môn). Không xoá được bản đang dùng."""
    row = tim(db, teacher_id, kid)
    if not row or row['dang_dung']:
        return False
    _xoa_tep(teacher_id, row['luu'])
    db.execute('DELETE FROM khdh WHERE id=?', (kid,))
    db.commit()
    return True


def _xoa_tep(teacher_id, ten):
    if not ten:
        return
    try:
        (folder(teacher_id) / ten).unlink()
    except OSError:
        pass


def doc_tep(teacher_id, row):
    """Đọc lại tệp KHDH đã lưu (để tích hợp NLS/AI/STEM mà không phải tải lên lại)."""
    if not row or not row['luu']:
        return None
    try:
        return (folder(teacher_id) / row['luu']).read_bytes()
    except OSError:
        return None


def _doc_lai_tep(teacher_id, row):
    data = doc_tep(teacher_id, row)
    if not data:
        return []
    try:
        return rows_tu_tep(data)
    except Exception:
        return []


def tom_tat(rows, gioi_han=6):
    """Vài tựa bài đầu để giáo viên đối chiếu nhanh trong trang kho."""
    ds = [(r.get('title') or '').strip() for r in (rows or [])]
    return [t for t in ds if t][:gioi_han]


# ---------------- đối chiếu với thời khoá biểu ----------------
def doi_chieu(db, teacher_id, tkb_rows):
    """So số tiết đã xếp trong thời khoá biểu với số tiết/tuần trong KHDH.

    Trả về danh sách dòng: môn, khối, lớp, số tiết KHDH yêu cầu, số tiết đã xếp,
    kết luận và ghi chú. Ghép theo (môn, khối, lớp dạy); dòng thời khoá biểu cũ chưa ghi
    khối thì ghép theo tên môn nếu môn đó chỉ có một khối trong kho.
    """
    kho = danh_sach(db, teacher_id)
    theo_mon = {}
    for k in kho:
        theo_mon.setdefault(k['mon_chuan'], []).append(k)

    def tim_kho(mon, khoi):
        ds = theo_mon.get(chuan(mon), [])
        if not ds:
            return None
        if khoi:
            return next((k for k in ds if str(k['khoi']) == str(khoi)), None)
        return ds[0] if len(ds) == 1 else None

    nhom = {}
    for r in tkb_rows:
        mon = (r['mon'] or '').strip()
        khoi = str(r['khoi'] or '').strip() if 'khoi' in r.keys() else ''
        key = (chuan(mon), khoi, (r['lop'] or '').strip())
        d = nhom.setdefault(key, {'mon': mon, 'khoi': khoi, 'lop': (r['lop'] or '').strip(),
                                  'so_tiet': 0, 'mon_chuan': chuan(mon)})
        d['so_tiet'] += 1

    ra = []
    for key, d in nhom.items():
        k = tim_kho(d['mon'], d['khoi'])
        if k and not d['khoi']:
            d['khoi'] = str(k['khoi'])
        can = k['so_tiet_tuan'] if k else None
        if k and not k['luu']:
            ket_luan, ghi_chu = 'chua_co_khdh', 'Môn này chưa có KHDH trong kho'
        elif not k:
            ket_luan, ghi_chu = 'chua_co_khdh', 'Môn này chưa có trong kho KHDH'
        elif not can:
            ket_luan, ghi_chu = 'chua_ro', ('Số tiết/tuần của KHDH chưa xác định — '
                                            'thầy/cô nhập tay trong kho KHDH')
        elif d['so_tiet'] < can:
            ket_luan, ghi_chu = 'thieu', 'Còn thiếu %d tiết/tuần so với KHDH' % (can - d['so_tiet'])
        elif d['so_tiet'] > can:
            ket_luan, ghi_chu = 'thua', 'Đã xếp thừa %d tiết/tuần so với KHDH' % (d['so_tiet'] - can)
        else:
            ket_luan, ghi_chu = 'du', 'Đủ số tiết/tuần theo KHDH'
        ra.append(dict(d, khdh=k, can=can, ket_luan=ket_luan, ghi_chu=ghi_chu))
    ra.sort(key=lambda x: (chuan(x['mon']), str(x['khoi']), x['lop']))
    return ra

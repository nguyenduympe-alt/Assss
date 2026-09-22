"""(M32) Thời khoá biểu lưu theo PHIÊN BẢN có tuần bắt đầu hiệu lực.

Yêu cầu: sửa/lưu ở tuần W thì bản cũ giữ nguyên từ mốc trước đến hết tuần W−1;
bản mới dùng từ W tới trước mốc kế. Không ghi đè lịch sử, không tạo TKB rời
từng tuần. Lưu lại cùng tuần bắt đầu = cập nhật mốc đó (không sinh mốc trùng).
Mốc gắn đúng giáo viên + năm học.
"""
import datetime


def nam_hoc_tu_ngay(d):
    """Năm học từ ngày thứ Hai tuần 1: từ tháng 8 thuộc năm đó / năm sau."""
    if not d:
        d = datetime.date.today()
    if isinstance(d, str):
        d = datetime.date.fromisoformat(d[:10])
    y = d.year
    if d.month >= 8:
        return "%d-%d" % (y, y + 1)
    return "%d-%d" % (y - 1, y)


def dam_bao_cot(db):
    """Thêm cột tuan_bd + nam_hoc cho DB cũ (an toàn gọi nhiều lần)."""
    cols = {r[1] for r in db.execute("PRAGMA table_info(tkb)")}
    for ten, ddl in (("tuan_bd", "INTEGER DEFAULT 1"), ("nam_hoc", "TEXT")):
        if ten not in cols:
            try:
                db.execute("ALTER TABLE tkb ADD COLUMN %s %s" % (ten, ddl))
                db.commit()
            except Exception:
                pass


def chuan_hoa(db, uid, nam):
    """Gán năm học + tuần bắt đầu = 1 cho dòng TKB cũ (chưa có phiên bản)."""
    dam_bao_cot(db)
    db.execute("UPDATE tkb SET tuan_bd=1 WHERE teacher_id=? AND (tuan_bd IS NULL OR tuan_bd=0)",
               (uid,))
    db.execute("UPDATE tkb SET nam_hoc=? WHERE teacher_id=? AND (nam_hoc IS NULL OR TRIM(nam_hoc)='')",
               (nam, uid))
    db.commit()


def moc(db, uid, nam):
    """Danh sách tuần bắt đầu đã có phiên bản, tăng dần (vd [1, 5, 9])."""
    chuan_hoa(db, uid, nam)
    rows = db.execute("SELECT DISTINCT COALESCE(tuan_bd,1) t FROM tkb"
                      " WHERE teacher_id=? AND COALESCE(nam_hoc,'')=? ORDER BY t",
                      (uid, nam)).fetchall()
    return [int(r[0]) for r in rows if r[0]]


def phien_cho_tuan(db, uid, nam, tuan):
    """Tuần bắt đầu hiệu lực tại tuần `tuan` (mốc lớn nhất ≤ tuan). 0 = chưa có TKB."""
    chuan_hoa(db, uid, nam)
    tuan = max(1, int(tuan or 1))
    r = db.execute("SELECT MAX(COALESCE(tuan_bd,1)) m FROM tkb"
                   " WHERE teacher_id=? AND COALESCE(nam_hoc,'')=? AND COALESCE(tuan_bd,1)<=?",
                   (uid, nam, tuan)).fetchone()
    return int(r[0] or 0)


def dong(db, uid, nam, tuan):
    """Các tiết của phiên bản hiệu lực tại tuần `tuan`."""
    v = phien_cho_tuan(db, uid, nam, tuan)
    if not v:
        return []
    return db.execute("SELECT * FROM tkb WHERE teacher_id=? AND COALESCE(nam_hoc,'')=?"
                      " AND COALESCE(tuan_bd,1)=? ORDER BY thu, buoi DESC, tiet",
                      (uid, nam, v)).fetchall()


def ds_lop(db, uid, nam=""):
    """Danh sách lớp đã từng dùng (mọi phiên bản) — để nạp combobox."""
    dam_bao_cot(db)
    q = "SELECT DISTINCT lop FROM tkb WHERE teacher_id=? AND TRIM(COALESCE(lop,''))<>''"
    a = [uid]
    if nam:
        q += " AND (COALESCE(nam_hoc,'')=? OR COALESCE(nam_hoc,'')='')"
        a.append(nam)
    q += " ORDER BY lop"
    return [r[0] for r in db.execute(q, a).fetchall() if r[0]]


def _chep(db, uid, nam, tu_tuan, sang_tuan):
    """Sao chép toàn bộ tiết của mốc tu_tuan thành mốc mới sang_tuan."""
    rows = db.execute("SELECT thu,buoi,tiet,lop,mon,khoi,phong FROM tkb"
                      " WHERE teacher_id=? AND COALESCE(nam_hoc,'')=? AND COALESCE(tuan_bd,1)=?",
                      (uid, nam, tu_tuan)).fetchall()
    for r in rows:
        db.execute("INSERT INTO tkb(teacher_id,thu,buoi,tiet,lop,mon,khoi,phong,tuan_bd,nam_hoc)"
                   " VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (uid, r["thu"], r["buoi"], r["tiet"], r["lop"], r["mon"], r["khoi"], r["phong"],
                    sang_tuan, nam))
    return len(rows)


def dam_bao_phien(db, uid, nam, tuan):
    """Đảm bảo có phiên bản đúng mốc `tuan` (sao chép từ mốc trước nếu chưa có).

    Không đụng các mốc *sau* `tuan`. Trả về tuần bắt đầu của phiên bản để ghi.
    """
    tuan = max(1, int(tuan or 1))
    chuan_hoa(db, uid, nam)
    hien = phien_cho_tuan(db, uid, nam, tuan)
    if hien == tuan:
        return tuan
    if hien:
        _chep(db, uid, nam, hien, tuan)
    db.commit()
    return tuan


def luu_lop(db, uid, nam, tuan, ds_doi):
    """Cập nhật lớp theo danh sách {khoa: 'thu|buoi|tiet', lop: '6A'}.

    Chỉ ghi khi có thay đổi thật. Cùng mốc → cập nhật tại chỗ; mốc mới → sao
    chép rồi sửa (giữ nguyên lịch sử + các mốc về sau).
    Trả về (ok, thong_bao, so_doi).
    """
    tuan = max(1, int(tuan or 1))
    hien = dong(db, uid, nam, tuan)
    if not hien:
        return False, "Chưa có thời khoá biểu để sửa lớp — thầy/cô nhập TKB trước.", 0
    bang = {}
    for r in hien:
        bang["%s|%s|%s" % (r["thu"], r["buoi"], r["tiet"])] = (r["lop"] or "").strip()
    doi = []
    for d in ds_doi:
        k = (d.get("khoa") or "").strip()
        lop = (d.get("lop") or "").strip()[:60]
        if not k or k not in bang:
            continue
        if not lop:
            return False, "Vui lòng chọn lớp cho mọi tiết (tiết %s còn trống)." % k, 0
        if lop != bang[k]:
            doi.append((k, lop))
    if not doi:
        return True, "Không có thay đổi lớp — thời khoá biểu giữ nguyên.", 0
    v = dam_bao_phien(db, uid, nam, tuan)
    for k, lop in doi:
        thu, buoi, tiet = k.split("|", 2)
        db.execute("UPDATE tkb SET lop=? WHERE teacher_id=? AND COALESCE(nam_hoc,'')=?"
                   " AND COALESCE(tuan_bd,1)=? AND thu=? AND buoi=? AND tiet=?",
                   (lop, uid, nam, v, thu, buoi, tiet))
    db.commit()
    return True, ("Đã lưu thời khoá biểu — áp dụng từ tuần %d (%d tiết đổi lớp). "
                  "Các tuần trước mốc này giữ nguyên bản cũ." % (v, len(doi))), len(doi)


def lich_su(db, uid, nam, ngay=None):
    """Các lần TKB đã lưu: từ tuần nào đến hết tuần nào (trước mốc kế), kèm ngày nếu có.

    `ngay`: {tuan: (tu_txt, den_txt)} lấy từ tuần dạy lịch báo giảng.
    """
    ds = moc(db, uid, nam)
    ngay = ngay or {}
    ra = []
    for i, t in enumerate(ds):
        den = (ds[i + 1] - 1) if i + 1 < len(ds) else None
        n = db.execute("SELECT COUNT(*) FROM tkb WHERE teacher_id=? AND COALESCE(nam_hoc,'')=?"
                       " AND COALESCE(tuan_bd,1)=?", (uid, nam, t)).fetchone()[0]
        tu_ngay, den_ngay = ngay.get(t, ("", ""))
        ra.append({"tuan_bd": t, "den_tuan": den, "so_tiet": n,
                   "tu": tu_ngay, "den": den_ngay, "lan": i + 1})
    return ra


def gan_phien(dt, tuan, nam):
    """Gắn tuan_bd + nam_hoc vào dict tiết khi INSERT."""
    dt = dict(dt)
    dt["tuan_bd"] = max(1, int(tuan or 1))
    dt["nam_hoc"] = nam
    return dt

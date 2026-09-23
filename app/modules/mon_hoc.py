"""(M31) QUẢN LÝ MÔN HỌC — gom mọi nơi có môn về một trang và đưa PHÂN PHỐI CHƯƠNG TRÌNH cho từng môn.

Yêu cầu của thầy/cô: “Thêm quản lý môn học để đưa phân phối chương trình cho môn”.

Trang Quản lý môn học liệt kê MỌI môn + khối mà giáo viên đang có, gom từ 4 nguồn:
  · danh sách MÔN DẠY đã khai ở Cài đặt / Thời khoá biểu (cột `subjects`),
  · kho KHDH (môn + khối có KHDH hoặc mới ghi nhận, chưa có tệp),
  · bảng PPCT (số dòng bài học theo môn + khối),
  · bảng thời khoá biểu (số tiết đã xếp theo môn + khối).

Với mỗi dòng, giáo viên làm được ngay:
  · NHẬP PHÂN PHỐI CHƯƠNG TRÌNH cho đúng môn + khối đó (tệp Word/Excel, tùy chọn thay thế PPCT cũ),
  · xem PPCT của môn (lọc sẵn theo môn + khối),
  · đổi tên môn / đổi khối (tự cập nhật PPCT, thời khoá biểu, kho KHDH, danh sách môn dạy),
  · đặt làm MÔN CHÍNH (môn đầu danh sách),
  · xoá môn kèm dữ liệu tuỳ chọn (PPCT / thời khoá biểu / KHDH trong kho / bỏ khỏi danh sách môn dạy).

Bộ này KHÔNG tự đặt mã, không sửa nội dung bài học — chỉ gom nhóm, ghi vào đúng môn + khối.
"""
import hashlib
import re

from . import khdh_kho as KHO
from . import mon_day as MD
from . import ppct_tach as PT
from . import doc_lich as DL

TOI_DA_TEP = 25               # số tệp tối đa một lượt nhập PPCT cho môn
DAI_TEP = 8 * 1024 * 1024     # dung lượng tối đa một tệp
DUOI_OK = (".docx", ".xlsx", ".xlsm", ".xls", ".csv") + DL.DUOI_OK


def _gon(s):
    return re.sub(r"\s+", " ", (s or "").replace("\u00a0", " ")).strip()


def _khoa(mon, khoi):
    return (MD.bo_dau(_gon(mon)), str(khoi or "").strip())


def _dem(db, sql, *a):
    try:
        return db.execute(sql, a).fetchone()[0] or 0
    except Exception:
        return 0


def liet_ke(db, uid, u=None):
    """Danh sách môn + khối của giáo viên kèm số liệu, sắp theo môn rồi khối.

    Mỗi phần tử: {'mon','khoi','co_kho','kid','ten_file','tiet_tuan','so_ppct','so_tuan','so_tkb',
                  'trong_danh_sach','chinh','dang_dung_kho'}
    """
    ds_mon = MD.danh_sach(u) if u is not None else []
    chinh = ds_mon[0] if ds_mon else ""
    ra, thay = [], {}

    def _dong(mon, khoi):
        k = _khoa(mon, khoi)
        if not k[0]:
            return None
        if k not in thay:
            thay[k] = {"mon": _gon(mon), "khoi": str(khoi or "").strip(), "co_kho": False, "kid": None,
                       "chinh": False,
                       "ten_file": "", "tiet_tuan": None, "so_ppct": 0, "so_tuan": 0, "so_tkb": 0,
                       "trong_danh_sach": False, "chinh": False, "dang_dung_kho": False,
                       "tiet_tuan_tay": False}
            ra.append(thay[k])
        return thay[k]

    for r in KHO.danh_sach(db, uid):                      # 1) kho KHDH (môn + khối)
        d = _dong(r["mon"], r["khoi"])
        if d:
            d["co_kho"] = d["co_kho"] or bool(r["luu"])
            d["kid"] = d["kid"] or r["id"]
            d["ten_file"] = d["ten_file"] or (r["ten_file"] or "")
            d["tiet_tuan"] = r["so_tiet_tuan"] if d["tiet_tuan"] is None else d["tiet_tuan"]
            d["tiet_tuan_tay"] = bool(r["tiet_tuan_tay"])
            d["dang_dung_kho"] = True

    for r in db.execute("SELECT mon, COALESCE(khoi,'') k, COUNT(*) n, COUNT(DISTINCT tuan) t"
                        " FROM ppct WHERE teacher_id=? GROUP BY lower(mon), COALESCE(khoi,'')",
                        (uid,)).fetchall():
        d = _dong(r[0], r[1])
        if d:
            d["so_ppct"] += r[2]
            d["so_tuan"] = max(d["so_tuan"], r[3])

    for r in db.execute("SELECT mon, COALESCE(khoi,'') k, COUNT(*) n FROM tkb WHERE teacher_id=?"
                        " GROUP BY lower(mon), COALESCE(khoi,'')", (uid,)).fetchall():
        d = _dong(r[0], r[1])
        if d:
            d["so_tkb"] += r[2]

    # 4) danh sách MÔN DẠY đã khai (Cài đặt / thời khoá biểu): khớp vào dòng đã có khối,
    #    chỉ tạo dòng mới khi môn đó chưa có chỗ nào ghi khối (môn dạy không kèm khối).
    for mon in ds_mon:
        k = MD.bo_dau(mon)
        trung = [d for d in ra if MD.bo_dau(d["mon"]) == k]
        if trung:
            for d in trung:
                d["trong_danh_sach"] = True
                d["chinh"] = bool(chinh) and MD.bo_dau(chinh) == k
        else:
            d = _dong(mon, "")
            if d:
                d["trong_danh_sach"] = True
                d["chinh"] = bool(chinh) and MD.bo_dau(chinh) == k
    for d in ra:
        if "chinh" not in d:
            d["chinh"] = bool(chinh) and MD.bo_dau(chinh) == MD.bo_dau(d["mon"])
    ra.sort(key=lambda d: (not d["chinh"], MD.bo_dau(d["mon"]), int(d["khoi"]) if d["khoi"].isdigit() else 99))
    for d in ra:
        d["slug"] = "mh-%s-%s" % (MD.bo_dau(d["mon"]).replace(" ", "-"), d["khoi"] or "0")
    return ra


def thong_ke(ds):
    """Đếm nhanh cho dải chip đầu trang."""
    return {"so_mon": len(ds),
            "co_ppct": sum(1 for d in ds if d["so_ppct"]),
            "co_khdh": sum(1 for d in ds if d["co_kho"]),
            "chua_khdh": sum(1 for d in ds if not d["co_kho"]),
            "dong_ppct": sum(d["so_ppct"] for d in ds),
            "tiet_tkb": sum(d["so_tkb"] for d in ds)}


def dau_ppct(db, uid):
    """Dấu vân tay PPCT của giáo viên — đổi khi thêm/sửa/xoá bài.

    Lịch báo giảng dùng dấu này để tự làm mới khi phân phối chương trình thay đổi.
    """
    rows = db.execute(
        "SELECT id, tuan, COALESCE(tiet_pp,''), COALESCE(mon,''), COALESCE(khoi,''),"
        " COALESCE(ten_bai,''), COALESCE(ghi_chu,'') FROM ppct WHERE teacher_id=? ORDER BY id",
        (uid,)).fetchall()
    h = hashlib.md5()
    h.update(str(len(rows)).encode())
    for r in rows:
        h.update(b"\n")
        h.update("|".join("" if x is None else str(x) for x in r).encode("utf-8", "replace"))
    return h.hexdigest()


def dem_ppct(db, uid, mon, khoi):
    return _dem(db, "SELECT COUNT(*) FROM ppct WHERE teacher_id=? AND lower(mon)=lower(?)"
                    " AND COALESCE(khoi,'')=?", uid, _gon(mon), str(khoi or ""))


def them_mon(db, uid, mon, khoi="", tao_vao_kho=True):
    """Thêm một môn (kèm khối nếu có) vào danh sách môn dạy. Trả về (ok, thong_bao)."""
    goc = _gon(mon)
    if len(goc) > MD.DAI_MON:
        return False, "Tên môn quá dài (tối đa %d ký tự)." % MD.DAI_MON
    mon, khoi = MD.chuan_mon(goc), str(khoi or "").strip()
    if not mon:
        return False, "Vui lòng nhập tên môn."
    if khoi and khoi not in KHO.KHOI:
        return False, "Khối phải từ 1 đến 12 (hoặc để trống)."
    ds = MD.danh_sach(db.execute("SELECT * FROM teacher WHERE id=?", (uid,)).fetchone())
    if len(ds) >= MD.TOI_DA_MON and not any(MD.bo_dau(x) == MD.bo_dau(mon) for x in ds):
        return False, "Mỗi giáo viên tối đa %d môn. Thầy/cô bỏ bớt môn không dùng." % MD.TOI_DA_MON
    moi = MD.them(db, uid, mon)
    if khoi and tao_vao_kho:
        KHO.tao_mon(db, uid, mon, khoi)                  # để môn hiện sẵn trong ô chọn ở Thời khoá biểu
    thong_bao = ("Đã thêm môn %s%s." % (mon, (" khối " + khoi) if khoi else "")) if moi else \
                ("Môn %s đã có trong danh sách%s." % (mon, (", đã ghi nhận khối " + khoi) if khoi else ""))
    return True, thong_bao


def doi_ten(db, uid, mon, khoi, mon_moi, khoi_moi=""):
    """Đổi tên môn / đổi khối: cập nhật PPCT + thời khoá biểu + kho KHDH + danh sách môn dạy."""
    mon, khoi = _gon(mon), str(khoi or "").strip()
    goc_moi = _gon(mon_moi)
    if len(goc_moi) > MD.DAI_MON:
        return False, "Tên môn quá dài (tối đa %d ký tự)." % MD.DAI_MON
    mon_moi, khoi_moi = MD.chuan_mon(goc_moi), str(khoi_moi or "").strip()
    if not mon or not mon_moi:
        return False, "Thiếu tên môn cần sửa hoặc tên môn mới."
    if khoi_moi and khoi_moi not in KHO.KHOI:
        return False, "Khối phải từ 1 đến 12 (hoặc để trống)."
    khoi_moi = khoi_moi or khoi
    dem = {}
    for bang in ("ppct", "tkb"):
        dem[bang] = _dem(db, "SELECT COUNT(*) FROM %s WHERE teacher_id=? AND lower(mon)=lower(?)"
                             " AND COALESCE(khoi,'')=?" % bang, uid, mon, khoi)
        db.execute("UPDATE %s SET mon=?, khoi=? WHERE teacher_id=? AND lower(mon)=lower(?)"
                   " AND COALESCE(khoi,'')=?" % bang, (mon_moi, khoi_moi, uid, mon, khoi))
    dem["khdh"] = _dem(db, "SELECT COUNT(*) FROM khdh WHERE teacher_id=? AND lower(mon)=lower(?)"
                            " AND COALESCE(khoi,'')=?", uid, mon, khoi)
    db.execute("UPDATE khdh SET mon=?, mon_chuan=?, khoi=? WHERE teacher_id=? AND lower(mon)=lower(?)"
               " AND COALESCE(khoi,'')=?", (mon_moi, MD.bo_dau(mon_moi), khoi_moi, uid, mon, khoi))
    MD.them(db, uid, mon_moi)
    if mon_moi and MD.bo_dau(mon_moi) != MD.bo_dau(mon):
        MD.xoa(db, uid, mon)                             # đổi tên thì bỏ tên cũ khỏi danh sách môn dạy
    db.commit()
    return True, ("Đã sửa môn %s%s thành %s%s — cập nhật %d dòng PPCT, %d tiết thời khoá biểu, %d bản KHDH."
                  % (mon, (" khối " + khoi) if khoi else "", mon_moi, (" khối " + khoi_moi) if khoi_moi else "",
                     dem["ppct"], dem["tkb"], dem["khdh"]))


def xoa_mon(db, uid, mon, khoi, xoa_ppct=True, xoa_tkb=True, xoa_kho=False, bo_danh_sach=True):
    """Xoá môn: tuỳ chọn xoá PPCT / thời khoá biểu / KHDH trong kho / bỏ khỏi danh sách môn dạy."""
    mon, khoi = _gon(mon), str(khoi or "").strip()
    if not mon:
        return False, "Thiếu tên môn cần xoá."
    dem = {"ppct": 0, "tkb": 0, "kho": 0, "ds": 0}
    if xoa_ppct:
        dem["ppct"] = _dem(db, "SELECT COUNT(*) FROM ppct WHERE teacher_id=? AND lower(mon)=lower(?)"
                               " AND COALESCE(khoi,'')=?", uid, mon, khoi)
        db.execute("DELETE FROM ppct WHERE teacher_id=? AND lower(mon)=lower(?) AND COALESCE(khoi,'')=?",
                   (uid, mon, khoi))
    if xoa_tkb:
        dem["tkb"] = _dem(db, "SELECT COUNT(*) FROM tkb WHERE teacher_id=? AND lower(mon)=lower(?)"
                              " AND COALESCE(khoi,'')=?", uid, mon, khoi)
        db.execute("DELETE FROM tkb WHERE teacher_id=? AND lower(mon)=lower(?) AND COALESCE(khoi,'')=?",
                   (uid, mon, khoi))
    if xoa_kho:
        for r in db.execute("SELECT id FROM khdh WHERE teacher_id=? AND lower(mon)=lower(?)"
                            " AND COALESCE(khoi,'')=?", (uid, mon, khoi)).fetchall():
            KHO.xoa(db, uid, r["id"])
            dem["kho"] += 1
    if bo_danh_sach and MD.xoa(db, uid, mon):
        # (M31) môn còn dữ liệu thì dòng vẫn hiện ở trang Quản lý môn học kèm ghi chú
        # “Chưa có trong danh sách môn dạy” + nút Thêm lại — nên bỏ khỏi danh sách luôn được.
        dem["ds"] = 1
    db.commit()
    return True, ("Đã xoá môn %s%s: %d dòng PPCT, %d tiết thời khoá biểu, %d bản KHDH, %s danh sách môn dạy."
                  % (mon, (" khối " + khoi) if khoi else "", dem["ppct"], dem["tkb"], dem["kho"],
                     "bỏ khỏi" if dem["ds"] else "giữ trong"))


def dat_chinh(db, uid, mon):
    """Đưa một môn lên đầu danh sách (môn chính) — các ô chọn môn trong hệ thống lấy môn này làm mặc định."""
    mon = MD.chuan_mon(_gon(mon))
    row = db.execute("SELECT * FROM teacher WHERE id=?", (uid,)).fetchone()
    ds = MD.danh_sach(row)
    if not mon or not any(MD.bo_dau(x) == MD.bo_dau(mon) for x in ds):
        return False, "Môn này chưa có trong danh sách môn dạy của thầy/cô."
    ten = next(x for x in ds if MD.bo_dau(x) == MD.bo_dau(mon))
    MD.luu(db, uid, [ten] + [x for x in ds if MD.bo_dau(x) != MD.bo_dau(ten)])
    return True, "Đã đặt %s làm môn chính (môn đầu danh sách)." % ten


def dong_ppct(db, uid, mon, khoi):
    """Các dòng PPCT của đúng một môn + khối, sắp theo tuần rồi tiết."""
    return db.execute("SELECT * FROM ppct WHERE teacher_id=? AND lower(mon)=lower(?)"
                      " AND COALESCE(khoi,'')=? ORDER BY tuan, tiet_pp, id",
                      (uid, _gon(mon), str(khoi or ""))).fetchall()


def them_dong(db, uid, mon, khoi, tuan, tiet_pp, ten_bai, ghi_chu=""):
    """Thêm một dòng PPCT trực tiếp trên trang Quản lý môn — tự gắn môn + khối đang thao tác."""
    mon, khoi = _gon(mon), str(khoi or "").strip()
    ten_bai = _gon(ten_bai)
    if not mon:
        return False, "Thiếu tên môn."
    if khoi not in KHO.KHOI:
        return False, "Thêm bài PPCT cần có khối (1–12)."
    if not ten_bai:
        return False, "Vui lòng nhập tên bài dạy."
    ds = PT.no_rong_tuan_tiet([{"tuan": tuan, "tiet_pp": tiet_pp, "ten_bai": ten_bai,
                                "ghi_chu": _gon(ghi_chu)}])
    n = 0
    tuan_dau = None
    for r in ds:
        try:
            tuan_i = int(r.get("tuan") or 0)
        except Exception:
            tuan_i = 0
        if tuan_i < 1 or tuan_i > 60:
            return False, "Tuần phải từ 1 đến 60 (ô “1-2” / “1,2” / “1+2” sẽ tự tách)."
        try:
            tiet = int(r.get("tiet_pp")) if str(r.get("tiet_pp") or "").strip() != "" else None
        except Exception:
            return False, "Tiết PPCT phải là số (ô “1-2” hoặc “1,2” sẽ tự tách)."
        db.execute("INSERT INTO ppct(teacher_id,khoi,mon,tuan,tiet_pp,ten_bai,ghi_chu) VALUES(?,?,?,?,?,?,?)",
                   (uid, khoi, mon, tuan_i, tiet, ten_bai, r.get("ghi_chu") or None))
        n += 1
        if tuan_dau is None:
            tuan_dau = tuan_i
    if not n:
        return False, "Tuần phải từ 1 đến 60 (ô “1-2” / “1,2” / “1+2” sẽ tự tách)."
    db.commit()
    MD.them(db, uid, mon)
    if n == 1:
        return True, "Đã thêm bài “%s” vào PPCT môn %s khối %s (tuần %d)." % (ten_bai, mon, khoi, tuan_dau)
    return True, ("Đã thêm bài “%s” vào PPCT môn %s khối %s — tách thành %d dòng tuần/tiết."
                  % (ten_bai, mon, khoi, n))


def sua_dong(db, uid, iid, tuan, tiet_pp, ten_bai, ghi_chu=""):
    """Sửa một dòng PPCT — chỉ dòng của đúng giáo viên."""
    r = db.execute("SELECT * FROM ppct WHERE id=? AND teacher_id=?", (iid, uid)).fetchone()
    if not r:
        return False, "Không tìm thấy dòng PPCT cần sửa (có thể đã bị xoá)."
    ten_bai = _gon(ten_bai)
    if not ten_bai:
        return False, "Vui lòng nhập tên bài dạy."
    try:
        tuan = int(tuan or 0)
    except Exception:
        tuan = 0
    if tuan < 1 or tuan > 60:
        return False, "Tuần phải từ 1 đến 60."
    try:
        tiet = int(tiet_pp) if str(tiet_pp or "").strip() != "" else None
    except Exception:
        return False, "Tiết PPCT phải là số."
    db.execute("UPDATE ppct SET tuan=?, tiet_pp=?, ten_bai=?, ghi_chu=? WHERE id=? AND teacher_id=?",
               (tuan, tiet, ten_bai, _gon(ghi_chu) or None, iid, uid))
    db.commit()
    return True, "Đã sửa bài “%s” (tuần %d) của môn %s." % (ten_bai, tuan, r["mon"])


def xoa_dong(db, uid, iid):
    r = db.execute("SELECT * FROM ppct WHERE id=? AND teacher_id=?", (iid, uid)).fetchone()
    if not r:
        return False, "Không tìm thấy dòng PPCT cần xoá."
    db.execute("DELETE FROM ppct WHERE id=? AND teacher_id=?", (iid, uid))
    db.commit()
    return True, "Đã xoá bài “%s” khỏi PPCT môn %s." % (r["ten_bai"] or "", r["mon"])


def xoa_ppct(db, uid, mon, khoi):
    """Xoá hết PPCT (lịch môn) của đúng một môn + khối — không đụng TKB / môn khác."""
    mon, khoi = _gon(mon), str(khoi or "").strip()
    if not mon:
        return False, "Thiếu tên môn cần xoá PPCT.", 0
    n = dem_ppct(db, uid, mon, khoi)
    if not n:
        return True, "Môn %s%s chưa có dòng PPCT nào." % (mon, (" khối " + khoi) if khoi else ""), 0
    db.execute("DELETE FROM ppct WHERE teacher_id=? AND lower(mon)=lower(?) AND COALESCE(khoi,'')=?",
               (uid, mon, khoi))
    db.commit()
    return True, ("Đã xoá hết %d dòng PPCT của môn %s%s."
                  % (n, mon, (" khối " + khoi) if khoi else "")), n


def _thieu_tuan(rows):
    """True khi tệp chưa ghi tuần (hoặc mọi bài cùng một tuần) — lúc đó mới chia đều 35 tuần."""
    tuans = set()
    for r in rows or []:
        try:
            t = int(r.get("tuan") or 0)
        except Exception:
            t = 0
        if t >= 1:
            tuans.add(t)
    return len(tuans) <= 1


def chia_deu_35(rows, so_tuan=None):
    """Gán tuần + tiết PPCT: chia đều tổng số bài cho 35 tuần (dư rải tuần đầu)."""
    so_tuan = int(so_tuan or KHO.SO_TUAN) or KHO.SO_TUAN
    so_tuan = max(1, min(60, so_tuan))
    ds = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        ten = _gon(r.get("ten_bai") or "")
        if not ten:
            continue
        ds.append(r)
    n = len(ds)
    if not n:
        return []
    base, du = divmod(n, so_tuan)
    ra, i, tiet = [], 0, 1
    for tuan in range(1, so_tuan + 1):
        k = base + (1 if tuan <= du else 0)
        for _ in range(k):
            r = dict(ds[i])
            r["tuan"] = tuan
            r["tiet_pp"] = tiet
            r["ten_bai"] = _gon(r.get("ten_bai") or "")
            ra.append(r)
            i += 1
            tiet += 1
    return ra


def sua_hang_loat(db, uid, mon, khoi, ids, tuans, tiets, tens, ghis):
    """Lưu cả bộ PPCT từ các ô sửa trên trang — dòng trống tên bài thì xoá, dòng mới thì thêm."""
    mon, khoi = _gon(mon), str(khoi or "").strip()
    if not mon:
        return False, "Thiếu tên môn."
    if khoi not in KHO.KHOI:
        return False, "Sửa PPCT cần có khối (1–12)."
    ids = list(ids or [])
    tuans = list(tuans or [])
    tiets = list(tiets or [])
    tens = list(tens or [])
    ghis = list(ghis or [])
    n = max(len(ids), len(tuans), len(tiets), len(tens), len(ghis))
    if n > 500:
        return False, "Quá nhiều dòng để lưu một lúc (tối đa 500)."
    while len(ids) < n:
        ids.append("")
    while len(tuans) < n:
        tuans.append("")
    while len(tiets) < n:
        tiets.append("")
    while len(tens) < n:
        tens.append("")
    while len(ghis) < n:
        ghis.append("")
    hop_le = set()
    for r in dong_ppct(db, uid, mon, khoi):
        hop_le.add(int(r["id"]))
    n_sua = n_them = n_xoa = 0
    for iid, tuan, tiet_pp, ten_bai, ghi_chu in zip(ids, tuans, tiets, tens, ghis):
        ten_bai = _gon(ten_bai)
        iid_s = str(iid or "").strip()
        try:
            iid_i = int(iid_s) if iid_s else 0
        except Exception:
            iid_i = 0
        if iid_i and iid_i not in hop_le:
            continue
        if iid_i and not ten_bai:
            db.execute("DELETE FROM ppct WHERE id=? AND teacher_id=?", (iid_i, uid))
            n_xoa += 1
            continue
        if not ten_bai:
            continue
        ds = PT.no_rong_tuan_tiet([{"tuan": tuan, "tiet_pp": tiet_pp, "ten_bai": ten_bai,
                                    "ghi_chu": _gon(ghi_chu)}])
        if not ds:
            return False, "Tuần phải từ 1 đến 60 (ô “1-2” / “1,2” / “1+2” tự tách — bài “%s”)." % ten_bai[:80]
        ghi = _gon(ghi_chu) or None
        for j, r in enumerate(ds):
            try:
                tuan_i = int(r.get("tuan") or 0)
            except Exception:
                tuan_i = 0
            if tuan_i < 1 or tuan_i > 60:
                return False, "Tuần phải từ 1 đến 60 (ô “1-2” / “1,2” / “1+2” tự tách — bài “%s”)." % ten_bai[:80]
            try:
                tiet = int(r.get("tiet_pp")) if str(r.get("tiet_pp") or "").strip() != "" else None
            except Exception:
                return False, "Tiết PPCT phải là số (ô “1-2” / “1,2” / “1+2” tự tách — bài “%s”)." % ten_bai[:80]
            if iid_i and j == 0:
                db.execute("UPDATE ppct SET tuan=?, tiet_pp=?, ten_bai=?, ghi_chu=? WHERE id=? AND teacher_id=?",
                           (tuan_i, tiet, ten_bai, ghi, iid_i, uid))
                n_sua += 1
            else:
                db.execute("INSERT INTO ppct(teacher_id,khoi,mon,tuan,tiet_pp,ten_bai,ghi_chu) VALUES(?,?,?,?,?,?,?)",
                           (uid, khoi, mon, tuan_i, tiet, ten_bai, ghi))
                n_them += 1
    db.commit()
    MD.them(db, uid, mon)
    if not (n_sua or n_them or n_xoa):
        return False, "Chưa có thay đổi nào để lưu."
    return True, ("Đã lưu phân phối môn %s khối %s: sửa %d, thêm %d, xoá %d dòng."
                  % (mon, khoi, n_sua, n_them, n_xoa))


# ---------------------------------------------------------------- nhập PPCT cho môn
def _doc_tep(f, mon_mac_dinh, khoi_mac_dinh, ds_mon=()):
    """Đọc một tệp thành các phần (môn + khối) với môn/khối mặc định là của dòng đang nhập."""
    ten = (getattr(f, "filename", "") or "")[:200]
    if not ten:
        return None, "Tệp không có tên — thầy/cô chọn lại tệp."
    if not ten.lower().endswith(DUOI_OK):
        return None, "Tệp “%s” không phải Word, bảng tính, PDF hoặc ảnh." % ten
    try:
        data = f.read(DAI_TEP + 1)
    except Exception:
        return None, "Không đọc được tệp “%s”." % ten
    if len(data) > DAI_TEP:
        return None, "Tệp “%s” lớn hơn 8 MB — thầy/cô lưu gọn lại rồi thử lại." % ten
    if DL.la_pdf(ten) or DL.la_anh(ten):
        ok, tb, phan = DL.doc_ppct(data, ten, mon_mac_dinh, khoi_mac_dinh)
        if not ok:
            return None, tb
        return phan, ""
    try:
        phan = PT.tach(data, ten, ds_mon, mon_mac_dinh, khoi_mac_dinh)
    except ValueError as exc:
        return None, str(exc)
    except Exception:
        return None, "Không đọc được tệp “%s” (hãy lưu lại .docx / .xlsx / .pdf rồi thử lại)." % ten
    if not phan:
        return None, ("Không thấy bảng phân phối chương trình trong tệp “%s”. Tệp cần có bảng với cột"
                      " “Tên bài dạy” (hoặc các dòng bắt đầu bằng “Bài 1…”)." % ten)
    return phan, ""


def nhap_ppct(db, uid, ds_tep, mon, khoi, thay_cu=True, ds_mon=()):
    """Nhập PPCT cho MỘT môn + khối của trang Quản lý môn học.

    Trả về (ket_qua, so_dong, so_loi). `ket_qua`: mỗi tệp một dòng kèm các phần đã đọc.
    """
    mon, khoi = _gon(mon), str(khoi or "").strip()
    if not mon:
        return [], 0, 1
    ket_qua, so_dong, so_loi, da_xoa = [], 0, 0, False
    for f in ds_tep[:TOI_DA_TEP]:
        ten = (getattr(f, "filename", "") or "")[:200]
        dong = {"ten": ten, "phan": [], "loi": "", "so_dong": 0}
        phan, loi = _doc_tep(f, mon, khoi, ds_mon)
        if loi:
            dong["loi"] = loi
            so_loi += 1
            ket_qua.append(dong)
            continue
        for p in phan:
            # Đưa đúng dòng môn thì đã biết môn + khối — tệp không cần cột lớp/khối.
            p["mon"], p["khoi"] = mon, khoi
            if not p["khoi"]:
                p["loi"] = "chưa rõ KHỐI — chọn khối cho môn này ở ô “Khối” rồi nhập lại"
                so_loi += 1
                dong["phan"].append(p)
                continue
            if thay_cu and not da_xoa and MD.bo_dau(p["mon"]) == MD.bo_dau(mon) and str(p["khoi"]) == khoi:
                db.execute("DELETE FROM ppct WHERE teacher_id=? AND lower(mon)=lower(?) AND COALESCE(khoi,'')=?",
                           (uid, mon, khoi))
                da_xoa = True
            p["rows"] = PT.no_rong_tuan_tiet(p["rows"])
            if _thieu_tuan(p["rows"]):
                p["rows"] = chia_deu_35(p["rows"])
                dong["chia_deu"] = True
            for r in p["rows"]:
                db.execute("INSERT INTO ppct(teacher_id,khoi,mon,tuan,tiet_pp,ten_bai,ghi_chu)"
                           " VALUES(?,?,?,?,?,?,?)",
                           (uid, p["khoi"], p["mon"], r.get("tuan") or 1, r.get("tiet_pp"),
                            r.get("ten_bai"), PT.ghi_chu_ppct(r) or None))
                so_dong += 1
            p["loi"] = ""
            dong["so_dong"] += len(p["rows"])
            dong["phan"].append(p)
        ket_qua.append(dong)
    db.commit()
    return ket_qua, so_dong, so_loi


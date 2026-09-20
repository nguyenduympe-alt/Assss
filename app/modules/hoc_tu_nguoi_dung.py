"""Học từ quyết định của giáo viên — vòng học để mô hình ngày càng chính xác hơn.

Cách hoạt động
--------------
1. Khi giáo viên duyệt/xuất bản Word, hệ thống ghi lại quyết định của giáo viên với
   từng đề xuất sửa chính tả: NHẬN (đã tích) hay BỎ QUA (không tích).
2. HỌC NGAY (không cần huấn luyện lại — có hiệu lực từ lần kiểm tra sau):
     · giáo viên bấm nút "từ này đúng" -> coi là từ ĐÚNG ngay (tín hiệu rõ ràng);
      hoặc một từ bị bỏ qua (không tích) đủ nhiều lần -> cũng coi là từ ĐÚNG;
     · một cặp "từ sai -> từ đúng" được nhận đủ nhiều lần -> ưu tiên đúng bản sửa đó.
3. HỌC SÂU: dữ liệu phản hồi được xuất ra JSONL (xuat_jsonl) rồi trộn vào tập huấn
   luyện để huấn luyện lại mô hình; chỉ công bố mô hình mới nếu qua cổng chất lượng
   (xem /home/user/train/hoc_tu_nguoi_dung.py). Trọng số câu học từ người dùng cao hơn
   câu tổng hợp vì đó là dữ liệu thật do giáo viên xác nhận.

Riêng tư
--------
· Chỉ ghi TỪ được đề xuất, bản sửa, và 1 từ mỗi bên làm ngữ cảnh — KHÔNG ghi cả giáo án.
· Dữ liệu chỉ nằm trên máy chủ của trường, không gửi đi đâu.
· Thầy/cô có thể TẮT hoàn toàn bằng khoá 'hoc_tu_nguoi_dung' = 0 (bảng setting).
"""
import json
import os
import re
import datetime as _dt

from ..db import DB_PATH      # cùng CSDL với ứng dụng, nhưng tự mở kết nối riêng

# Module này KHÔNG dùng Flask (get_db/setting cần ngữ cảnh ứng dụng) để có thể chạy
# từ dòng lệnh và trong kiểm thử: mọi truy cập đều qua _con().


def _con():
    import sqlite3 as _sq
    con = _sq.connect(DB_PATH, timeout=30)
    con.row_factory = _sq.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con

KHOAS = "hoc_tu_nguoi_dung"
NGUONG_BO = 5          # bị bỏ qua (không tích) >= 5 lần thì coi từ đó là ĐÚNG
NGUONG_DUNG = 1        # giáo viên BẤM NÚT "từ này đúng" 1 lần là đủ (tín hiệu rõ ràng)
NGUONG_NHAN = 2        # được nhận đủ 2 lần thì đề xuất đó là "sửa chắc", tích sẵn
TOI_DA_TU = 5000       # giới hạn số từ đã học để tệp luôn nhỏ
TOI_DA_NGU_CANH = 24   # số ký tự mỗi bên ngữ cảnh lưu lại


def bat():
    """Việc học từ người dùng có đang bật không? (mặc định: bật)."""
    try:
        con = _con()
        r = con.execute("SELECT v FROM setting WHERE k=?", (KHOAS,)).fetchone()
        con.close()
        v = (r["v"] if r else "1") or "1"
    except Exception:
        v = "1"
    return v.strip().lower() not in ("0", "tat", "off", "false")


def dat_bat(b):
    con = _con()
    con.execute("INSERT INTO setting(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (KHOAS, "1" if b else "0"))
    con.commit()
    con.close()


def duong_dan_hoc():
    """Tệp JSON chứa kiến thức học được (mô hình đọc tệp này, không đọc CSDL)."""
    return os.path.join(os.path.dirname(DB_PATH), "hoc_tu_nguoi_dung.json")


# ------------------------------------------------------------------ ghi phản hồi
def ten_giao_vien(uid):
    """Tên đăng nhập của giáo viên (để ghi vào nhật ký phản hồi). Không có thì để trống."""
    try:
        con = _con()
        r = con.execute("SELECT username FROM teacher WHERE id=?", (uid,)).fetchone()
        con.close()
        return (r["username"] if r else "") or ""
    except Exception:
        return ""


def _ngu_canh(doan, start, end):
    """1 từ mỗi bên chỗ sai — vừa đủ để mô hình học ngữ cảnh, không lưu cả câu."""
    trai = (doan[:start] or "").strip()[-TOI_DA_NGU_CANH:]
    phai = (doan[end:] or "").strip()[:TOI_DA_NGU_CANH]
    return trai, phai


def ghi(de_xuat, chon_ids, giao_vien="", lop="", phien_ban="", ep_quyet_dinh=None):
    """Ghi quyết định của giáo viên cho mọi đề xuất đã hiển thị.

    de_xuat: danh sách đề xuất (có id, para, start, end, goc, de_xuat, nguon, doan_goc)
    chon_ids: các id giáo viên đã tích để áp dụng.
    Trả về số dòng đã ghi.
    """
    if not bat():
        return 0
    chon = set(chon_ids or [])
    luc = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db = _con()
    n = 0
    for d in de_xuat or []:
        tu = (d.get("goc") or "").strip()
        if not tu or len(tu) > 40:
            continue
        doan = d.get("doan_goc") or ""
        truoc, sau = _ngu_canh(doan, d.get("start") or 0, d.get("end") or 0)
        db.execute(
            "INSERT INTO ml_phan_hoi(luc,giao_vien,lop,phien_ban,tu,truoc,sau,de_xuat,"
            "quyet_dinh,nguon) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (luc, giao_vien, lop, phien_ban, tu, truoc, sau, d.get("de_xuat") or "",
             ep_quyet_dinh or ("nhan" if d["id"] in chon else "bo"),
             d.get("nguon") or "luat"))
        n += 1
    db.commit()
    _tinh_lai_da_hoc(db)
    _ghi_snapshot(db)
    return n


# ------------------------------------------------------- tính lại kiến thức học được
def _tinh_lai_da_hoc(db=None):
    """Gom phản hồi thành 2 loại kiến thức: từ đúng, và cặp sửa đã được duyệt."""
    db = db or _con()
    db.execute("DELETE FROM ml_da_hoc")
    # 1a. giáo viên BẤM NÚT "từ này đúng" -> học ngay (tín hiệu rõ ràng)
    for r in db.execute(
            "SELECT lower(tu) AS tu, COUNT(*) AS n, MAX(luc) AS cuoi FROM ml_phan_hoi "
            "WHERE quyet_dinh='dung' AND length(tu)>=2 GROUP BY lower(tu) "
            "HAVING n >= ? ORDER BY n DESC LIMIT ?", (NGUONG_DUNG, TOI_DA_TU)):
        db.execute("INSERT OR REPLACE INTO ml_da_hoc(loai,khoa,dem,du_lieu,cap_nhat)"
                   " VALUES('tu_dung',?,?,?,?)",
                   (r["tu"], r["n"], json.dumps({"tu": r["tu"], "dung": r["n"],
                                                 "cach": "giáo viên bấm nút từ này đúng"},
                                                ensure_ascii=False), r["cuoi"] or ""))
    # 1b. từ bị bỏ qua nhiều lần -> cũng coi là từ đúng (tín hiệu ngầm, cần nhiều lần)
    for r in db.execute(
            "SELECT lower(tu) AS tu, COUNT(*) AS n, MAX(luc) AS cuoi FROM ml_phan_hoi "
            "WHERE quyet_dinh='bo' AND length(tu)>=2 GROUP BY lower(tu) "
            "HAVING n >= ? ORDER BY n DESC LIMIT ?", (NGUONG_BO, TOI_DA_TU)):
        db.execute("INSERT OR REPLACE INTO ml_da_hoc(loai,khoa,dem,du_lieu,cap_nhat)"
                   " VALUES('tu_dung',?,?,?,?)",
                   (r["tu"], r["n"], json.dumps({"tu": r["tu"], "bo": r["n"],
                                                 "cach": "bị bỏ qua nhiều lần"},
                                                ensure_ascii=False), r["cuoi"] or ""))
    # 2. cặp sửa được nhận nhiều lần -> ưu tiên bản sửa này
    for r in db.execute(
            "SELECT lower(tu) AS goc, lower(de_xuat) AS sua, COUNT(*) AS n, MAX(luc) AS cuoi "
            "FROM ml_phan_hoi WHERE quyet_dinh='nhan' AND de_xuat<>'' AND length(de_xuat)<=40 "
            "GROUP BY lower(tu), lower(de_xuat) ORDER BY n DESC LIMIT ?", (TOI_DA_TU,)):
        # bỏ cặp mà chính từ gốc cũng từng bị giáo viên bỏ qua nhiều lần (tín hiệu trái nhau)
        bo = db.execute("SELECT COUNT(*) AS n FROM ml_phan_hoi WHERE quyet_dinh='bo' "
                        "AND lower(tu)=? AND de_xuat=?", (r["goc"], r["sua"])).fetchone()["n"]
        if bo >= NGUONG_BO:
            continue
        db.execute("INSERT OR REPLACE INTO ml_da_hoc(loai,khoa,dem,du_lieu,cap_nhat)"
                   " VALUES('cap_sua',?,?,?,?)",
                   (r["goc"] + " -> " + r["sua"], r["n"],
                    json.dumps({"goc": r["goc"], "sua": r["sua"], "dem": r["n"],
                                "bo": bo}, ensure_ascii=False), r["cuoi"] or ""))
    db.commit()


def _ghi_snapshot(db=None):
    """Ghi kiến thức học được ra JSON để mô hình đọc (ghi kiểu nguyên tử, tránh hỏng tệp)."""
    db = db or _con()
    ra = {"tu_dung": {}, "cap_sua": {}, "cap_nhat": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    for r in db.execute("SELECT loai,khoa,dem FROM ml_da_hoc"):
        if r["loai"] == "tu_dung":
            ra["tu_dung"][r["khoa"]] = r["dem"]
        else:
            goc, _, sua = r["khoa"].partition(" -> ")
            ra["cap_sua"][goc] = {"sua": sua, "dem": r["dem"]}
    p = duong_dan_hoc()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tam = p + ".tmp"
    with open(tam, "w", encoding="utf-8") as f:
        json.dump(ra, f, ensure_ascii=False)
    os.replace(tam, p)
    return ra


def da_hoc():
    """Đọc kiến thức học được (không cần CSDL) — dùng cho giao diện và kiểm thử."""
    p = duong_dan_hoc()
    if not os.path.exists(p):
        return {"tu_dung": {}, "cap_sua": {}, "cap_nhat": ""}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"tu_dung": {}, "cap_sua": {}, "cap_nhat": ""}


def thong_ke():
    """Số liệu cho giao diện: đang bật hay tắt, đã học được gì."""
    try:
        db = _con()
        tong = db.execute("SELECT COUNT(*) AS n FROM ml_phan_hoi").fetchone()["n"]
        nhan = db.execute("SELECT COUNT(*) AS n FROM ml_phan_hoi WHERE quyet_dinh='nhan'"
                          ).fetchone()["n"]
    except Exception:
        tong = nhan = 0
    h = da_hoc()
    try:
        so_dung = _con().execute("SELECT COUNT(*) AS n FROM ml_phan_hoi WHERE quyet_dinh='dung'"
                                 ).fetchone()["n"]
    except Exception:
        so_dung = 0
    return {"bat": bat(), "so_phan_hoi": tong, "so_nhan": nhan, "so_bo": tong - nhan,
            "so_dung": so_dung,
            "so_tu_dung": len(h.get("tu_dung") or {}), "so_cap_sua": len(h.get("cap_sua") or {}),
            "cap_nhat": h.get("cap_nhat") or "", "nguong_bo": NGUONG_BO, "nguong_nhan": NGUONG_NHAN, "nguong_dung": NGUONG_DUNG}


# ------------------------------------------------------------------ xuất để huấn luyện
def xuat_jsonl(duong_dan, phien_ban=""):
    """Xuất toàn bộ phản hồi ra JSONL để đưa sang máy huấn luyện."""
    con = _con()
    n = 0
    with open(duong_dan, "w", encoding="utf-8") as f:
        for r in con.execute("SELECT * FROM ml_phan_hoi ORDER BY id"):
            f.write(json.dumps({k: r[k] for k in r.keys()}, ensure_ascii=False) + "\n")
            n += 1
    con.close()
    return n

import sqlite3, os, json
from flask import g

# DB_DIR: khi deploy nên trỏ vào ổ đĩa lưu trữ bền (persistent disk), vd /var/data
DB_DIR = os.environ.get("DB_DIR") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DB_DIR, "edu.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS teacher(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL,
  fullname TEXT,
  school TEXT,
  subject TEXT,
  role TEXT DEFAULT 'teacher',
  email TEXT,
  phone TEXT,                      -- so dien thoai nhan tin nhan ma kich hoat
  google_sub TEXT,
  avatar TEXT,
  used INTEGER DEFAULT 0,          -- so luot da dung
  bought INTEGER DEFAULT 0,        -- so luot mua them (goi le 10k)
  expires TEXT,                    -- han su dung goi tra phi (ISO date)
  created TEXT
);
CREATE TABLE IF NOT EXISTS license(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT UNIQUE NOT NULL,
  months INTEGER DEFAULT 12,
  loai TEXT DEFAULT 'vip',         -- 'vip' = 1 nam | 'luot' = cong them luot
  luot INTEGER DEFAULT 0,
  note TEXT,
  used_by INTEGER,                 -- teacher_id da dung
  used_at TEXT,
  created TEXT
);
CREATE TABLE IF NOT EXISTS usage_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER, kind TEXT, detail TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS ppct(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER, khoi TEXT, mon TEXT,
  tuan INTEGER, tiet_pp INTEGER, ten_bai TEXT, ghi_chu TEXT
);
CREATE TABLE IF NOT EXISTS tkb(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER,
  thu INTEGER,          -- 2..8 (8 = Chu nhat)
  buoi TEXT,            -- Sang / Chieu
  tiet INTEGER,
  lop TEXT, mon TEXT, phong TEXT
);
CREATE TABLE IF NOT EXISTS khdh(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER,
  mon TEXT, mon_chuan TEXT,        -- ten mon + ten da chuan hoa (bo dau) de so trung
  khoi TEXT,                       -- khoi/lop (1..12)
  ten_file TEXT, luu TEXT,         -- ten tep goc + ten tep luu trong DB_DIR/khdh/<teacher_id>/
  loai TEXT DEFAULT 'ppct',        -- 'ppct' = KHDH/phan phoi chuong trinh | 'lesson' = giao an
  so_dong INTEGER DEFAULT 0,       -- so dong bai hoc doc duoc tu KHDH
  so_tiet_tuan INTEGER,            -- so tiet moi tuan (he thong suy ra hoac giao vien nhap)
  tiet_tuan_tay INTEGER DEFAULT 0, -- 1 = giao vien tu nhap, khong ghi de
  phien_ban INTEGER DEFAULT 1,
  dang_dung INTEGER DEFAULT 1,     -- 1 = ban dang dung (moi mon + khoi chi 1 ban)
  created TEXT, updated TEXT
);
CREATE INDEX IF NOT EXISTS idx_khdh_gv ON khdh(teacher_id, mon_chuan, khoi, dang_dung);
CREATE TABLE IF NOT EXISTS lop(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER, ten TEXT, khoi TEXT
);
CREATE TABLE IF NOT EXISTS hocsinh(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  lop_id INTEGER, ho_ten TEXT, ma_hs TEXT
);
CREATE TABLE IF NOT EXISTS danhgia(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER, lop TEXT, mon TEXT, hocky TEXT,
  ho_ten TEXT, diem REAL, muc_do TEXT, nhan_xet_goc TEXT,
  nhan_xet TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS nghi(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER,
  ten TEXT,                 -- vd: Nghi Tet Nguyen dan
  kieu TEXT DEFAULT 'tuan', -- 'tuan' = nghi tron tuan (khong tinh PPCT) | 'ngay' = nghi le
  tu_ngay TEXT, den_ngay TEXT,
  created TEXT
);
CREATE TABLE IF NOT EXISTS bank_tx(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref TEXT UNIQUE,                 -- ma giao dich ngan hang (chong xu ly trung)
  noi_dung TEXT, so_tien INTEGER, loai TEXT, ngay TEXT, nguon TEXT,
  teacher_id INTEGER, goi TEXT, code TEXT,
  trang_thai TEXT,                 -- da_kich_hoat | da_tao_ma | cho_doi_soat | bo_qua | trung
  ghi_chu TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS sms_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER, phone TEXT, noi_dung TEXT, loai TEXT,
  provider TEXT, ok INTEGER, ket_qua TEXT, created TEXT
);
CREATE TABLE IF NOT EXISTS setting(
  k TEXT PRIMARY KEY, v TEXT
);
CREATE TABLE IF NOT EXISTS ml_phan_hoi(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  luc TEXT, giao_vien TEXT, lop TEXT, phien_ban TEXT,
  tu TEXT, truoc TEXT, sau TEXT, de_xuat TEXT,
  quyet_dinh TEXT,                 -- nhan | bo  (giáo viên nhận hay bỏ qua đề xuất)
  nguon TEXT                       -- luat | mo_hinh | hoc_tu_nguoi_dung
);
CREATE INDEX IF NOT EXISTS idx_ml_phan_hoi_tu ON ml_phan_hoi(tu);
CREATE TABLE IF NOT EXISTS ml_da_hoc(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  loai TEXT,                       -- tu_dung | cap_sua
  khoa TEXT UNIQUE,                -- từ đúng  |  "từ sai -> từ đúng"
  dem INTEGER DEFAULT 0,
  du_lieu TEXT,                    -- JSON chi tiết
  cap_nhat TEXT
);
"""


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        # timeout: chờ thay vì báo lỗi "database is locked" khi worker khác đang ghi
        g.db = sqlite3.connect(DB_PATH, timeout=30)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA busy_timeout=30000")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Tạo bảng và nâng cấp lược đồ. An toàn khi nhiều worker cùng gọi một lúc.

    Khi deploy với gunicorn --workers 2, cả hai tiến trình cùng khởi tạo CSDL trống
    nên phải khoá ghi và dùng INSERT OR IGNORE, nếu không một worker sẽ chết vì
    UNIQUE constraint failed: teacher.username.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")      # nhiều tiến trình đọc/ghi mượt hơn
    con.execute("PRAGMA busy_timeout=30000")
    con.executescript(SCHEMA)
    from werkzeug.security import generate_password_hash
    import datetime as _dt
    con.execute(
        "INSERT OR IGNORE INTO teacher(username,password,fullname,school,subject,role,created)"
        " VALUES(?,?,?,?,?,?,?)",
        ("gv", generate_password_hash("123456"), "Nguyễn Văn A",
         "Trường Tiểu học Sóc Trăng", "Toán", "admin", _dt.date.today().isoformat()))
    # --- tu dong them cot moi cho DB cu (migration) ---
    cols = {r[1] for r in con.execute("PRAGMA table_info(teacher)")}
    for name, ddl in [("email", "TEXT"), ("phone", "TEXT"), ("google_sub", "TEXT"), ("avatar", "TEXT"),
                      ("used", "INTEGER DEFAULT 0"), ("bought", "INTEGER DEFAULT 0"),
                      ("expires", "TEXT"), ("created", "TEXT"),
                      ("subjects", "TEXT")]:        # (M17) một giáo viên dạy nhiều môn
        if name not in cols:
            try:
                con.execute(f"ALTER TABLE teacher ADD COLUMN {name} {ddl}")
            except sqlite3.OperationalError:
                pass        # worker khác vừa thêm cột này rồi
    lcols = {r[1] for r in con.execute("PRAGMA table_info(license)")}
    for name, ddl in [("loai", "TEXT DEFAULT 'vip'"), ("luot", "INTEGER DEFAULT 0")]:
        if name not in lcols:
            try:
                con.execute(f"ALTER TABLE license ADD COLUMN {name} {ddl}")
            except sqlite3.OperationalError:
                pass
    kcols = {r[1] for r in con.execute("PRAGMA table_info(khdh)")}
    if kcols and "mon_chuan" not in kcols:          # DB tao truoc M12
        try:
            con.execute("ALTER TABLE khdh ADD COLUMN mon_chuan TEXT")
        except sqlite3.OperationalError:
            pass
    tcols = {r[1] for r in con.execute("PRAGMA table_info(tkb)")}
    for name, ddl in (("khoi", "TEXT"),):
        if name not in tcols:
            try:
                con.execute(f"ALTER TABLE tkb ADD COLUMN {name} {ddl}")
            except sqlite3.OperationalError:
                pass
    # (M17) DB cũ: chuyển "môn dạy" đang có thành dòng đầu của danh sách môn
    con.execute("UPDATE teacher SET subjects=subject WHERE (subjects IS NULL OR TRIM(subjects)='')"
                " AND subject IS NOT NULL AND TRIM(subject)<>''")
    con.execute("UPDATE teacher SET role='admin' WHERE username='gv' AND (role IS NULL OR role='teacher')")
    con.commit()
    con.close()


def setting(k, default=""):
    r = get_db().execute("SELECT v FROM setting WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_setting(k, v):
    db = get_db()
    db.execute("INSERT INTO setting(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
    db.commit()

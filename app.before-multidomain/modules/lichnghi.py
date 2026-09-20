"""Quản lý lịch nghỉ: tuần nghỉ trọn (Tết, hè) và ngày nghỉ lẻ (lễ).

Nguyên tắc đánh số tuần:
  - "Tuần lịch" (calendar week) = tuần thực tế trôi qua tính từ ngày khai giảng.
  - "Tuần học" (tuần PPCT) = chỉ đếm những tuần KHÔNG nghỉ.
  Ví dụ: khai giảng 01/09, nghỉ Tết 2 tuần lịch thứ 22-23
     -> tuần lịch 21 = tuần học 21
     -> tuần lịch 22, 23 = NGHỈ TẾT (không có tuần học)
     -> tuần lịch 24 = tuần học 22
Nhờ vậy tên bài trong PPCT không bị lệch sau kỳ nghỉ.
"""
import datetime, json

THU_VN = {0: "Thứ Hai", 1: "Thứ Ba", 2: "Thứ Tư", 3: "Thứ Năm",
          4: "Thứ Sáu", 5: "Thứ Bảy", 6: "Chủ Nhật"}


# ---------- tiện ích ----------
def monday_of(d):
    return d - datetime.timedelta(days=d.weekday())


def parse_date(s):
    try:
        return datetime.date.fromisoformat(str(s).strip())
    except Exception:
        return None


# ---------- truy vấn ----------
def get_breaks(db, uid):
    """Danh sách kỳ nghỉ: [{id, ten, tu, den, kieu}] — kieu: 'tuan' | 'ngay'."""
    rows = db.execute("SELECT * FROM nghi WHERE teacher_id=? ORDER BY tu_ngay", (uid,)).fetchall()
    out = []
    for r in rows:
        out.append({"id": r["id"], "ten": r["ten"], "kieu": r["kieu"],
                    "tu": parse_date(r["tu_ngay"]), "den": parse_date(r["den_ngay"])})
    return [b for b in out if b["tu"] and b["den"]]


def off_mondays(breaks):
    """Tập hợp các thứ Hai của những TUẦN bị nghỉ trọn."""
    s = set()
    for b in breaks:
        if b["kieu"] != "tuan":
            continue
        m = monday_of(b["tu"])
        while m <= b["den"]:
            s.add(m)
            m += datetime.timedelta(days=7)
    return s


def off_days(breaks):
    """Tập hợp các NGÀY nghỉ lẻ -> {date: tên kỳ nghỉ}."""
    d = {}
    for b in breaks:
        if b["kieu"] != "ngay":
            continue
        cur = b["tu"]
        while cur <= b["den"]:
            d[cur] = b["ten"]
            cur += datetime.timedelta(days=1)
    return d


def week_label(monday, breaks):
    """Tuần lịch này có nghỉ trọn không? Trả về tên kỳ nghỉ hoặc None."""
    for b in breaks:
        if b["kieu"] == "tuan" and monday_of(b["tu"]) <= monday <= b["den"]:
            return b["ten"]
    return None


# ---------- ánh xạ tuần học <-> ngày ----------
def build_calendar(tuan1, breaks, max_hoc=60):
    """Trả về (map_hoc_to_monday, danh_sach_tuan_lich).

    map_hoc_to_monday: {tuần_học: thứ_Hai}
    danh_sach: [{'monday':d, 'nghi':tên|None, 'hoc':số tuần học|None}, ...]
    """
    offs = off_mondays(breaks)
    mp, lst = {}, []
    hoc = 0
    m = monday_of(tuan1)
    guard = 0
    while hoc < max_hoc and guard < 120:
        guard += 1
        ten = week_label(m, breaks)
        if m in offs or ten:
            lst.append({"monday": m, "nghi": ten or "Nghỉ", "hoc": None})
        else:
            hoc += 1
            mp[hoc] = m
            lst.append({"monday": m, "nghi": None, "hoc": hoc})
        m += datetime.timedelta(days=7)
    return mp, lst


def monday_for_week(tuan1, breaks, tuan_hoc):
    """Thứ Hai tương ứng với tuần học thứ N (đã bỏ qua các tuần nghỉ)."""
    mp, _ = build_calendar(tuan1, breaks, max_hoc=max(tuan_hoc, 1) + 2)
    return mp.get(tuan_hoc, monday_of(tuan1) + datetime.timedelta(weeks=tuan_hoc - 1))


def current_week(tuan1, breaks, today=None):
    """Tuần học hiện tại theo lịch thật; 0 nếu đang trong kỳ nghỉ / ngoài năm học."""
    today = today or datetime.date.today()
    m_now = monday_of(today)
    mp, lst = build_calendar(tuan1, breaks)
    for it in lst:
        if it["monday"] == m_now:
            return it["hoc"] or 0
    return 0


# ---------- mẫu nghỉ Tết ----------
def tet_suggest(year):
    """Gợi ý khoảng nghỉ Tết Nguyên đán (ước lượng) để GV chỉnh lại."""
    known = {2026: (2, 17), 2027: (2, 6), 2028: (1, 26), 2029: (2, 13), 2030: (2, 3)}
    if year in known:
        mo, dy = known[year]
        return datetime.date(year, mo, dy)
    return datetime.date(year, 2, 1)

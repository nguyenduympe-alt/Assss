# 🔧 Tài liệu kỹ thuật EduAssist

Dành cho người muốn tự sửa hoặc thêm chức năng mới. Nếu bạn chỉ cần đưa website lên mạng, hãy đọc `HUONG-DAN-DEPLOY.md`.

---

## Công nghệ sử dụng

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Khung web | Flask 3.1 | Nhẹ, dễ đọc, dễ mở rộng |
| Cơ sở dữ liệu | SQLite (WAL) | Một file duy nhất, dễ sao lưu, đủ cho vài trăm người dùng |
| Máy chủ chạy thật | Gunicorn (gthread) | Ổn định, chịu tải tốt |
| Sinh PDF | ReportLab + phông DejaVu | Hỗ trợ đầy đủ tiếng Việt có dấu |
| Sinh Word | python-docx | Giữ nguyên định dạng gốc |
| Đọc Excel | openpyxl | Không cần cài Microsoft Office |
| Mã QR | Tự viết theo chuẩn EMVCo | Chạy offline, không phụ thuộc dịch vụ ngoài |
| Nhận xét & chính tả | Quy tắc nội bộ | **Không cần API key, không tốn tiền, chạy offline** |

Toàn bộ hệ thống **không gọi ra ngoài Internet** trừ khi bạn tự bật SMS/Zalo/Google.

---

## Cấu trúc thư mục

```
edu/
├── run.py                  # chạy thử ở máy (cổng 8080)
├── requirements.txt        # danh sách thư viện
├── render.yaml             # cấu hình deploy Render
├── Procfile / Dockerfile   # deploy nền tảng khác
├── deploy-vps.sh           # script cài VPS tự động
│
├── app/
│   ├── __init__.py         # khởi tạo ứng dụng, đăng ký blueprint
│   ├── db.py               # lược đồ CSDL + tự nâng cấp cột khi lên phiên bản mới
│   ├── auth.py             # đăng nhập, đăng ký, Google OAuth
│   ├── core.py             # toàn bộ trang chính
│   ├── webhook.py          # nhận giao dịch ngân hàng
│   │
│   ├── modules/            # phần xử lý nghiệp vụ, tách riêng để dễ kiểm thử
│   │   ├── config.py       # ⭐ cấu hình trung tâm (CSDL > biến môi trường > mặc định)
│   │   ├── billing.py      # hạn mức, gói cước, mã kích hoạt
│   │   ├── bank_webhook.py # đối soát chuyển khoản tự động
│   │   ├── sms.py          # cổng nhắn tin đa nhà cung cấp
│   │   ├── vietqr.py       # sinh mã QR chuyển khoản
│   │   ├── ai_nhanxet.py   # sinh nhận xét học sinh
│   │   ├── chinhta.py      # dò lỗi chính tả tiếng Việt
│   │   ├── docx_text.py    # đọc/sửa file Word giữ nguyên định dạng
│   │   ├── excel_io.py     # đọc/ghi Excel
│   │   ├── lichnghi.py     # tính lịch nghỉ, dồn tuần học
│   │   ├── pdf_bao_giang.py
│   │   └── word_bao_giang.py
│   │
│   ├── plugins/            # ⭐ nơi thêm chức năng mới
│   ├── templates/          # giao diện (Jinja2)
│   └── static/fonts/       # phông DejaVu cho PDF tiếng Việt
│
└── data/edu.db             # dữ liệu (KHÔNG đưa lên GitHub)
```

---

## Chạy thử ở máy tính

```bash
cd edu
pip install -r requirements.txt
python run.py
```

Mở http://127.0.0.1:8080 — đăng nhập `gv` / `123456`.

Muốn thử đúng như khi chạy thật (nhiều worker):

```bash
gunicorn "app:create_app()" --bind 0.0.0.0:8080 --workers 2 --threads 4
```

---

## ⭐ Thêm chức năng mới — cách nhanh nhất

Tạo một file `.py` trong `app/plugins/`, hệ thống **tự phát hiện và tự thêm vào menu**.

```python
# app/plugins/thongke.py
from flask import Blueprint, render_template_string
from ..auth import login_required

bp = Blueprint("thongke", __name__)

# Khai báo này giúp chức năng tự hiện lên thanh menu bên trái
MENU = {"label": "Thống kê lớp", "endpoint": "thongke.trang_chinh", "icon": "📈"}


@bp.route("/thong-ke")
@login_required
def trang_chinh():
    return render_template_string("""
        {% extends 'base.html' %}
        {% block head %}Thống kê lớp{% endblock %}
        {% block body %}
          <div class="card"><h3>Nội dung của bạn</h3></div>
        {% endblock %}
    """)
```

Khởi động lại là xong — không cần sửa file nào khác.

---

## Cấu hình trung tâm

Mọi tham số đọc qua `app/modules/config.py`, theo thứ tự ưu tiên:

```
1. Giá trị admin lưu trên web (bảng setting, tiền tố "cfg.")
2. Biến môi trường
3. Giá trị mặc định khai trong DINH_NGHIA
```

### Thêm một tham số mới vào trang Cài đặt

Chỉ cần thêm một dòng vào danh sách `DINH_NGHIA` trong `config.py`:

```python
Muc("TEN_THAM_SO", "Nhãn hiển thị", "giá trị mặc định",
    kieu="text",          # text | number | password | select | bool
    nhom="thuong_hieu",   # nhóm nào trong 6 nhóm sẵn có
    mo_ta="Câu giải thích cho người dùng",
    bimat=False),         # True thì che giá trị khi hiển thị
```

Giao diện tự dựng ô nhập, tự lưu, tự hiện nhãn nguồn gốc. Đọc giá trị bằng `CFG.get("TEN_THAM_SO")`.

> ⚠️ Có bộ nhớ đệm TTL 3 giây để nhiều worker đồng bộ với nhau. Đừng đọc cấu hình trong vòng lặp chạy hàng nghìn lần.

---

## Hệ thống hạn mức

```python
from .modules import billing as BL

BL.can_use(user)                          # còn lượt không?
BL.consume(db, user, "kind", "chi tiết")  # trừ 1 lượt và ghi nhật ký
BL.remaining(user)                        # số lượt còn lại, None = VIP không giới hạn
```

Công thức: `còn lại = FREE_QUOTA + teacher.bought − teacher.used`. VIP (`expires` còn hạn) thì không giới hạn.

Giá trị `kind` dùng trong `usage_log`: `pdf`, `word`, `excel`, `chinhta`.

---

## Đối soát chuyển khoản

```
Ngân hàng → SePay/Casso → POST /webhook/bank
  → check_auth()       xác thực bằng BANK_WEBHOOK_TOKEN
  → parse_payload()    chuẩn hoá dữ liệu (nhận cả 2 định dạng)
  → tach_ma()          bóc "EDU0007 LUOT" → (7, 'luot')
  → xu_ly()            đối chiếu tiền, cộng lượt/VIP, nhắn tin
```

Chống xử lý trùng bằng khoá duy nhất `bank_tx.ref`.

### Thêm nhà cung cấp nhắn tin mới

Trong `app/modules/sms.py`:

```python
def _send_ten_moi(phone, text, **kw):
    r = _requests().post("https://api...", json={...}, timeout=_tg())
    return r.json().get("ok") is True, "Thông điệp kết quả"

PROVIDERS["ten_moi"] = ("Tên hiển thị", _send_ten_moi)
```

Rồi thêm `("ten_moi", "Tên hiển thị")` vào danh sách `chon` của mục `SMS_PROVIDER` trong `config.py` để nó hiện ra trong ô chọn.

---

## Cơ sở dữ liệu

| Bảng | Nội dung |
|---|---|
| `teacher` | tài khoản giáo viên, `used`/`bought`/`expires` quản hạn mức |
| `license` | mã kích hoạt, `loai` = `vip` \| `luot` |
| `usage_log` | nhật ký từng lượt sử dụng |
| `bank_tx` | giao dịch chuyển khoản đã nhận |
| `sms_log` | nhật ký tin nhắn đã gửi |
| `ppct`, `tkb`, `nghi` | phân phối chương trình, thời khoá biểu, lịch nghỉ |
| `danhgia` | nhận xét học sinh đã sinh |
| `setting` | cấu hình hệ thống (tiền tố `cfg.`) |

### Thêm cột mới mà không mất dữ liệu cũ

Trong `db.py`, thêm vào `SCHEMA` **và** vào danh sách migration:

```python
for name, ddl in [..., ("cot_moi", "TEXT")]:
    if name not in cols:
        try:
            con.execute(f"ALTER TABLE teacher ADD COLUMN {name} {ddl}")
        except sqlite3.OperationalError:
            pass
```

Hệ thống tự thêm cột khi khởi động, dữ liệu cũ giữ nguyên.

---

## Lưu ý khi chạy nhiều worker

Đã xử lý sẵn các vấn đề sau, **đừng phá vỡ khi sửa code**:

| Vấn đề | Cách đã xử lý |
|---|---|
| Nhiều worker cùng tạo CSDL trống → lỗi UNIQUE | `INSERT OR IGNORE` trong `init_db()` |
| Hai worker cùng thêm cột → lỗi duplicate column | Bọc `try/except OperationalError` |
| "database is locked" | Bật WAL + `busy_timeout=30000` |
| Worker này không thấy cấu hình worker kia vừa lưu | Bộ đệm TTL 3 giây trong `config.py` |
| Cookie phiên quá 4KB (file Word upload) | Lưu ra `data/tmp/`, cookie chỉ giữ token 32 ký tự |

---

## Giao diện

Kế thừa `base.html` và dùng lại các lớp CSS có sẵn:

```jinja
{% extends 'base.html' %}
{% block head %}Tiêu đề trang{% endblock %}
{% block crumb %}Mô tả ngắn{% endblock %}
{% block body %}
  <div class="card">
    <div class="chead"><h3>Tiêu đề</h3><span class="chip">nhãn</span></div>
    <div class="g2"> ... hai cột ... </div>
    <button class="ok">Nút chính</button>
    <button class="sec">Nút phụ</button>
  </div>
{% endblock %}
```

Lớp dùng chung: `.card` `.chead` `.g2` `.g3` `.kpis` `.kpi` `.tbl-wrap` `.badge.HTT/.HT/.CHT` `.btn.sec/.ok/.dan/.sm` `.chip` `.empty` `.row` `label.f` `hr.s` · flash `ok`/`err`.

Bảng màu: teal `#0d9488`, emerald `#059669`, nền `#f3f8f6`, thanh bên `#0a1f1c`.

---

## Quy ước đánh giá học sinh

```python
# Quy đổi điểm sang mức độ (tiểu học)
điểm ≥ 8  → HTT (Hoàn thành tốt)
điểm ≥ 5  → HT  (Hoàn thành)
còn lại   → CHT (Chưa hoàn thành)

# Xếp loại (THCS/THPT)
≥ 9 Xuất sắc · ≥ 8 Giỏi · ≥ 6.5 Khá · ≥ 5 Đạt · < 5 Chưa đạt
```

Sửa trong `app/modules/ai_nhanxet.py`.

---

## Kiểm thử nhanh trước khi deploy

```bash
# 1. Kiểm tra cú pháp toàn bộ
python -m compileall -q app && echo OK

# 2. Chạy thử nhiều worker với CSDL trống (bắt lỗi tranh chấp)
rm -f data/edu.db
gunicorn "app:create_app()" --bind 0.0.0.0:8080 --workers 4

# 3. Kiểm tra máy chủ sống
curl http://127.0.0.1:8080/suc-khoe
```

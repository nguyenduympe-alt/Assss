# 🚀 Hướng dẫn đưa website lên Internet cho nhiều giáo viên dùng

Tài liệu này viết cho người **chưa từng đưa website lên mạng bao giờ**. Cứ làm tuần tự từ trên xuống.

---

## 📋 Mục lục

1. [Chọn nơi đặt website](#1)
2. [Chuẩn bị mã nguồn trên GitHub](#2)
3. [CÁCH A — Render.com (miễn phí, dễ nhất)](#3)
4. [CÁCH B — VPS riêng (dùng thật, ổn định)](#4)
5. [Việc BẮT BUỘC làm ngay sau khi lên mạng](#5)
6. [Cấu hình website qua giao diện](#6)
7. [Hướng dẫn giáo viên sử dụng](#7)
8. [Sao lưu dữ liệu](#8)
9. [Nâng cấp website sau này](#9)
10. [Xử lý sự cố thường gặp](#10)

---

<a id="1"></a>
## 1. Chọn nơi đặt website

| Nơi đặt | Chi phí | Độ khó | Chịu được bao nhiêu người | Phù hợp |
|---|---|---|---|---|
| **Render.com** ⭐ | Miễn phí | Dễ nhất | ~20-30 giáo viên | Dùng thử, tổ chuyên môn |
| **Render trả phí** | ~7 USD/tháng | Dễ | ~100 giáo viên | Một trường học |
| **VPS Việt Nam** | 50-150k₫/tháng | Trung bình | 200+ giáo viên | Nhiều trường, dùng lâu dài |

> **Lời khuyên:** Bắt đầu bằng **Render miễn phí** để chạy thử vài tuần.
> Khi thấy ổn và có người dùng thật thì chuyển sang VPS hoặc Render trả phí.

### ⚠️ Điều quan trọng nhất phải biết trước

Website lưu dữ liệu trong **một file duy nhất** tên `edu.db` (chứa tài khoản giáo viên, phân phối chương trình, lịch sử thanh toán…).

- Trên **Render gói miễn phí**, file này **bị xoá sạch mỗi lần deploy lại hoặc máy chủ khởi động lại** → chỉ dùng để chạy thử.
- Muốn giữ dữ liệu lâu dài, bắt buộc phải có **ổ đĩa bền** (Render trả phí) hoặc **VPS**.

---

<a id="2"></a>
## 2. Chuẩn bị mã nguồn trên GitHub

Cả hai cách deploy đều cần bước này.

1. Tạo tài khoản miễn phí tại https://github.com
2. Bấm dấu **+** góc phải trên → **New repository**
3. Đặt tên `eduassist`, chọn **Private** (riêng tư), bấm **Create repository**
4. Tải toàn bộ thư mục `edu` từ workspace về máy tính
5. Trên trang GitHub vừa tạo, bấm dòng chữ **uploading an existing file**
6. Kéo thả **tất cả** file và thư mục bên trong `edu` vào (gồm `app/`, `run.py`, `requirements.txt`, `render.yaml`, `Procfile`, `Dockerfile`)
7. Bấm **Commit changes**

> 💡 Nếu bạn biết dùng Git thì nhanh hơn:
> ```bash
> cd edu
> git init && git add -A && git commit -m "EduAssist"
> git branch -M main
> git remote add origin https://github.com/TEN-CUA-BAN/eduassist.git
> git push -u origin main
> ```

> ⚠️ **Đừng tải file `data/edu.db` lên GitHub** — đó là dữ liệu thật, không phải mã nguồn.

---

<a id="3"></a>
## 3. CÁCH A — Render.com (miễn phí)

### Bước 1 — Tạo dịch vụ

1. Vào https://render.com → **Get Started** → đăng nhập **bằng tài khoản GitHub**
2. Bấm **New +** → chọn **Web Service**
3. Chọn kho `eduassist` → bấm **Connect**
4. Render tự đọc file `render.yaml` và điền sẵn mọi thứ. Kiểm tra lại:

   | Mục | Giá trị |
   |---|---|
   | Name | `eduassist` (hoặc tên bạn thích) |
   | Region | **Singapore** (gần Việt Nam nhất) |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn "app:create_app()" --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120` |
   | Instance Type | Free |

5. Bấm **Create Web Service** và chờ khoảng 3-5 phút

### Bước 2 — Lấy địa chỉ website

Xong sẽ có địa chỉ dạng:

```
https://eduassist-xxxx.onrender.com
```

Mở thử — nếu hiện trang đăng nhập là **thành công**. Đây chính là địa chỉ gửi cho giáo viên.

### Bước 3 — Bật ổ đĩa bền (nếu muốn giữ dữ liệu)

Gói miễn phí sẽ xoá dữ liệu mỗi lần deploy. Muốn giữ:

1. Nâng lên gói **Starter** (~7 USD/tháng)
2. Vào **Settings → Disks → Add Disk**
   - Name: `eduassist-data`
   - Mount Path: `/var/data`
   - Size: 1 GB
3. Vào **Environment**, thêm biến: `DB_DIR` = `/var/data`
4. Bấm **Save** — website tự khởi động lại

### Bước 4 — Chống "ngủ đông" (gói miễn phí)

Gói miễn phí sẽ ngủ sau 15 phút không ai truy cập, lần vào sau phải chờ ~50 giây. Khắc phục miễn phí:

1. Đăng ký https://uptimerobot.com (miễn phí)
2. **Add New Monitor** → HTTP(s)
3. URL: `https://eduassist-xxxx.onrender.com/suc-khoe`
4. Monitoring Interval: **5 phút**

Website sẽ được "đánh thức" liên tục, giáo viên vào lúc nào cũng nhanh.

---

<a id="4"></a>
## 4. CÁCH B — VPS riêng (khuyên dùng khi chạy thật)

Nhà cung cấp VPS Việt Nam giá tốt: **Vietnix, AZDIGI, TinoHost, Viettel IDC** (~50-150k₫/tháng). Chọn cấu hình tối thiểu **1 CPU / 1GB RAM / Ubuntu 22.04**.

### Bước 1 — Kết nối vào VPS

Nhà cung cấp gửi cho bạn địa chỉ IP, tài khoản `root` và mật khẩu. Mở **Terminal** (macOS/Linux) hoặc **PowerShell** (Windows):

```bash
ssh root@DIA-CHI-IP-CUA-BAN
```

### Bước 2 — Trỏ tên miền về VPS (làm TRƯỚC khi cài)

Bạn cần một tên miền (mua ở Mắt Bão, PA Vietnam, Namecheap… khoảng 200-300k₫/năm).

1. Vào trang quản lý tên miền, tạo bản ghi **A** trỏ về địa chỉ IP của VPS
2. Chờ 15-30 phút cho tên miền cập nhật
3. Kiểm tra đã trỏ đúng chưa: `ping tenmien-cua-ban.com` phải ra đúng IP của VPS

> Phải làm bước này trước, vì script cài đặt sẽ tự xin chứng chỉ HTTPS — cần tên miền trỏ đúng thì mới xin được.

### Bước 3 — Cài đặt tự động bằng một lệnh

```bash
apt update && apt install -y git
git clone https://github.com/TEN-CUA-BAN/eduassist.git /opt/src
cd /opt/src
bash deploy-vps.sh tenmien-cua-ban.com email-cua-ban@gmail.com
```

Script tự động làm hết 7 việc: cài Python và thư viện → tạo dịch vụ chạy nền tự khởi động cùng máy → cấu hình Nginx → **xin chứng chỉ HTTPS miễn phí** → **đặt lịch sao lưu hằng ngày**.

Chạy xong sẽ hiện:

```
==========================================
 HOÀN TẤT! Truy cập: https://tenmien-cua-ban.com
 Tài khoản mặc định: gv / 123456  (ĐỔI NGAY!)
```

### Bước 4 — Các lệnh quản lý thường dùng

```bash
systemctl status eduassist      # xem website còn chạy không
systemctl restart eduassist     # khởi động lại
journalctl -u eduassist -f      # xem nhật ký lỗi theo thời gian thực
eduassist-backup                # sao lưu dữ liệu ngay lập tức
```

**Vị trí các file quan trọng:**

| Nội dung | Đường dẫn |
|---|---|
| Mã nguồn đang chạy | `/opt/eduassist` |
| Cơ sở dữ liệu (quan trọng nhất) | `/var/lib/eduassist/edu.db` |
| Bản sao lưu tự động | `/var/backups/eduassist/` |
| Cấu hình dịch vụ | `/etc/systemd/system/eduassist.service` |

---

<a id="5"></a>
## 5. ⚠️ Việc BẮT BUỘC làm ngay sau khi lên mạng

### 5.1. Đổi mật khẩu quản trị — LÀM NGAY LẬP TỨC

Tài khoản mặc định `gv / 123456` **ai đọc tài liệu cũng biết**. Website đã công khai thì bất kỳ ai cũng đăng nhập được vào trang quản trị.

1. Đăng nhập bằng `gv` / `123456`
2. Website sẽ hiện **dải cảnh báo đỏ** ở đầu mọi trang — bấm nút **Đổi mật khẩu**
3. Đặt mật khẩu mạnh (chữ hoa, chữ thường, số, ký tự đặc biệt, từ 10 ký tự)
4. Cảnh báo đỏ biến mất nghĩa là đã an toàn

### 5.2. Đặt khoá bí mật cho phiên đăng nhập

Trên Render: vào **Environment**, kiểm tra đã có biến `SECRET_KEY` chưa (file `render.yaml` để Render tự sinh). Nếu chưa có, thêm vào với một chuỗi ngẫu nhiên dài.

Trên VPS: script `deploy-vps.sh` **đã tự sinh `SECRET_KEY` ngẫu nhiên và bật `HTTPS_ONLY=1`** rồi, không cần làm gì thêm. Muốn kiểm tra:

```bash
grep SECRET_KEY /etc/systemd/system/eduassist.service
```

### 5.3. Kiểm tra danh sách an toàn

Đăng nhập admin → **Bảng điều khiển QT** → xem khối **🩺 Tình trạng hệ thống**. Mọi mục nên có dấu ✅.

---

<a id="6"></a>
## 6. Cấu hình website qua giao diện

Từ đây trở đi **không cần đụng vào file hay lệnh nào nữa**. Đăng nhập tài khoản admin → menu **⚙️ Cài đặt hệ thống**.

| Nhóm | Nên làm gì |
|---|---|
| 🏫 **Thông tin website** | Đổi tên website thành tên trường mình, thêm số Zalo và email hỗ trợ để giáo viên biết hỏi ai |
| 💳 **Gói cước** | Đặt số lượt miễn phí và giá tiền phù hợp với địa phương |
| 🏦 **Tài khoản nhận tiền** | **Quan trọng** — điền đúng ngân hàng và số tài khoản của bạn, mã QR sẽ tự vẽ lại |
| ⚡ **Đối soát tự động** | Bấm **🎲 Tự sinh khoá bí mật** rồi làm theo `HUONG-DAN-THANH-TOAN-TU-DONG.md` |
| 📩 **Nhắn tin** | Đăng ký eSMS hoặc Zalo ZNS, dán khoá, bấm **📩 Gửi tin thử** để kiểm tra |
| 🔑 **Đăng nhập Google** | Xem mục 6.1 bên dưới |

Mọi thay đổi **có hiệu lực ngay**, không phải deploy lại.

### 6.1. Bật đăng nhập bằng Google (khuyên dùng)

Giáo viên ngại nhớ thêm mật khẩu, cho đăng nhập bằng Google sẽ tiện hơn nhiều.

1. Vào https://console.cloud.google.com → tạo dự án mới
2. Menu trái → **APIs & Services** → **OAuth consent screen** → chọn **External** → điền tên ứng dụng và email → Save
3. Sang **Credentials** → **Create Credentials** → **OAuth client ID**
   - Application type: **Web application**
   - Authorized redirect URIs: điền chính xác
     ```
     https://dia-chi-website-cua-ban/login/google/callback
     ```
4. Bấm **Create**, copy **Client ID** và **Client Secret**
5. Về website → **Cài đặt hệ thống** → mục **🔑 Đăng nhập Google** → dán vào → Lưu

Trang đăng nhập sẽ hiện thêm nút **Đăng nhập bằng Google**.

---

<a id="7"></a>
## 7. Hướng dẫn giáo viên sử dụng

Gửi đoạn tin nhắn mẫu này cho đồng nghiệp:

> 📚 **Mời thầy/cô dùng thử phần mềm hỗ trợ soạn hồ sơ**
>
> 🔗 Địa chỉ: https://dia-chi-website-cua-ban
>
> Phần mềm giúp:
> • Nhập phân phối chương trình và thời khoá biểu một lần, tự xuất **lịch báo giảng** ra PDF và Word cho cả năm
> • Tự động **sinh nhận xét học sinh** từ file Excel điểm số (cả tiểu học CHT/HT/HTT lẫn THCS/THPT)
> • **Kiểm tra lỗi chính tả** file Word, bấm một nút là sửa xong, giữ nguyên định dạng
> • Tự tính **lịch nghỉ lễ, nghỉ Tết**, dồn tuần học cho khớp
>
> Thầy/cô bấm **Đăng ký** để tạo tài khoản, được dùng thử miễn phí ngay.

### Quy trình dùng lần đầu của giáo viên

1. **Đăng ký** tài khoản (hoặc đăng nhập Google)
2. Vào **Cài đặt** điền họ tên, trường, môn dạy → thông tin này tự in lên lịch báo giảng
3. Vào **Phân phối chương trình** nhập PPCT (nhập tay hoặc tải file Excel mẫu lên)
4. Vào **Thời khoá biểu** nhập thời khoá biểu một tuần
5. Vào **Lịch nghỉ** khai các đợt nghỉ lễ, nghỉ Tết
6. Vào **Lịch báo giảng** chọn tuần → bấm xuất **PDF** hoặc **Word**

---

<a id="8"></a>
## 8. Sao lưu dữ liệu

**Đây là việc quan trọng nhất để không mất công sức của giáo viên.**

### Trên VPS — đã tự động rồi

Script `deploy-vps.sh` đã tự đặt lịch sao lưu **2 giờ sáng mỗi ngày, giữ 30 bản gần nhất** tại `/var/backups/eduassist/`.

Kiểm tra xem có chạy không:

```bash
ls -lh /var/backups/eduassist/     # xem danh sách bản sao lưu
eduassist-backup                   # sao lưu ngay lập tức
crontab -l                         # xem lịch đã đặt
```

### Tải bản sao về máy tính (nên làm mỗi tháng)

Chạy lệnh này **trên máy tính của bạn**, không phải trên VPS:

```bash
scp root@DIA-CHI-IP:/var/lib/eduassist/edu.db ./sao-luu-edu.db
```

### Khôi phục khi có sự cố

```bash
systemctl stop eduassist
cp /var/backups/eduassist/edu-20260913-0200.db /var/lib/eduassist/edu.db
chown www-data:www-data /var/lib/eduassist/edu.db
systemctl start eduassist
```

### Trên Render

Vào **Shell** trong bảng điều khiển Render, chạy:

```bash
cat /var/data/edu.db | base64
```

Copy kết quả về máy và giải mã. Cách này thủ công, nên **VPS vẫn tốt hơn cho việc dùng lâu dài**.

---

<a id="9"></a>
## 9. Nâng cấp website sau này

Khi có phiên bản mới (thêm chức năng, sửa lỗi):

**Trên Render:** chỉ cần tải mã mới lên GitHub, Render **tự động deploy lại** trong vài phút.

**Trên VPS:**

```bash
cd /opt/src && git pull
bash deploy-vps.sh tenmien-cua-ban.com email-cua-ban@gmail.com
```

Hoặc nhanh hơn nếu chỉ sửa mã nguồn:

```bash
cd /opt/src && git pull
rsync -a --exclude data --exclude __pycache__ --exclude .git ./ /opt/eduassist/
chown -R www-data:www-data /opt/eduassist
systemctl restart eduassist
```

> ✅ Dữ liệu giáo viên **không bị mất** khi nâng cấp. Hệ thống tự thêm cột mới vào cơ sở dữ liệu cũ.

---

<a id="10"></a>
## 10. Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân & cách xử lý |
|---|---|
| Vào web chờ rất lâu rồi mới hiện | Render gói miễn phí đang ngủ. Làm theo mục 3 Bước 4 (UptimeRobot) |
| Mất hết tài khoản sau khi deploy | Chưa bật ổ đĩa bền. Làm theo mục 3 Bước 3 |
| Nút đăng nhập Google báo lỗi | Địa chỉ chuyển hướng khai ở Google Console không khớp. Phải đúng `https://ten-mien/login/google/callback`, có cả `https://` |
| Mã QR hiện sai số tài khoản | Vào **Cài đặt hệ thống → 🏦 Tài khoản nhận tiền** sửa lại |
| Chuyển khoản rồi mà không tự kích hoạt | Xem `HUONG-DAN-THANH-TOAN-TU-DONG.md`. Vào **Quản trị → ⚡ Chuyển khoản tự động** xem giao dịch có về không |
| Giáo viên không nhận được tin nhắn | Vào **Cài đặt hệ thống → 📩 Nhắn tin**, kiểm tra còn đang để "Giả lập" không. Bấm **Gửi tin thử** |
| Không xuất được PDF, lỗi phông chữ | Kiểm tra thư mục `app/static/fonts/` có đủ `DejaVuSans.ttf` và `DejaVuSans-Bold.ttf` |
| Trang báo lỗi 500 | VPS: `journalctl -u eduassist -n 50`. Render: xem tab **Logs** |
| Web chậm khi đông người | Tăng số worker: sửa `--workers 2` thành `--workers 4` (cần VPS từ 2GB RAM) |

### Kiểm tra nhanh website còn sống

Mở địa chỉ: `https://website-cua-ban/suc-khoe`

Hiện `{"ok": true, ...}` nghĩa là máy chủ và cơ sở dữ liệu đều bình thường.

---

## ✅ Danh sách kiểm tra trước khi mời giáo viên dùng

- [ ] Website mở được bằng địa chỉ công khai
- [ ] Đã **đổi mật khẩu** tài khoản `gv` (dải cảnh báo đỏ đã biến mất)
- [ ] Đã đặt `SECRET_KEY` và `HTTPS_ONLY=1`
- [ ] Đã bật **ổ đĩa bền** hoặc dùng VPS (để không mất dữ liệu)
- [ ] Đã sửa **tên website** và **thông tin liên hệ** trong Cài đặt hệ thống
- [ ] Đã điền đúng **số tài khoản ngân hàng**, thử quét mã QR bằng app ngân hàng xem có ra đúng tên mình không
- [ ] Đã bật **UptimeRobot** (nếu dùng Render miễn phí)
- [ ] Đã đặt lịch **sao lưu tự động**
- [ ] Đã tự đăng ký thử một tài khoản giáo viên và chạy thử toàn bộ: nhập PPCT → xuất báo giảng → sửa chính tả

---

## 📞 Các tài liệu khác

- `HUONG-DAN-THANH-TOAN-TU-DONG.md` — kết nối SePay/Casso và dịch vụ nhắn tin
- `README-KY-THUAT.md` — dành cho người muốn tự thêm chức năng mới

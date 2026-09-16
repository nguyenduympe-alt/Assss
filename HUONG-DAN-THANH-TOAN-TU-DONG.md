# Hướng dẫn bật thanh toán tự động + nhắn tin mã kích hoạt

Hệ thống đã có sẵn toàn bộ phần lập trình. Việc còn lại chỉ là **đăng ký dịch vụ và điền khoá vào biến môi trường**.

Luồng hoạt động:

```
Giáo viên quét QR chuyển khoản  →  Tiền vào Agribank
        ↓
SePay / Casso phát hiện biến động số dư (2-15 giây)
        ↓
Gọi vào  https://<tên-miền>/webhook/bank
        ↓
EduAssist đọc nội dung "EDU0007 3LUOT"  →  tìm đúng giáo viên
        ↓
Tạo mã + cộng lượt / bật VIP ngay lập tức
        ↓
Nhắn SMS hoặc Zalo báo cho giáo viên
```

---

## Bước 1 — Đăng ký dịch vụ đối soát ngân hàng

Chọn **một** trong hai (hệ thống hỗ trợ cả hai, không cần sửa code):

### SePay (khuyên dùng cho Agribank)

1. Đăng ký tại https://sepay.vn → liên kết tài khoản Agribank `7614215002756`.
2. Vào **Tích hợp webhooks → Thêm webhook**:
   - URL: `https://<tên-miền-của-bạn>/webhook/bank`
   - Kiểu xác thực: **API Key**
   - Giá trị: chuỗi bí mật bạn tự đặt (chính là `BANK_WEBHOOK_TOKEN` bên dưới)
   - Sự kiện: **Chỉ tiền vào**
3. Bấm **Gửi thử** — trang Quản trị của website phải hiện giao dịch mới.

### Casso

1. Đăng ký tại https://casso.vn → liên kết tài khoản ngân hàng.
2. **Cài đặt → Webhook → Tạo webhook**:
   - URL: `https://<tên-miền-của-bạn>/webhook/bank`
   - Secure Token: chuỗi bí mật bạn tự đặt

---

## Bước 2 — Đăng ký dịch vụ nhắn tin

Chọn nhà cung cấp tuỳ nhu cầu:

| Nhà cung cấp | `SMS_PROVIDER` | Chi phí tham khảo | Ghi chú |
|---|---|---|---|
| Zalo ZNS | `zns` | ~200-400đ/tin | Rẻ nhất, giáo viên VN dùng Zalo nhiều. Cần duyệt mẫu tin |
| eSMS.vn | `esms` | ~350-800đ/tin | SMS brandname, cần đăng ký tên thương hiệu |
| SpeedSMS.vn | `speedsms` | ~350-700đ/tin | Tương tự eSMS |
| Twilio | `twilio` | ~$0.04/tin | Dùng khi có khách nước ngoài |
| Giả lập | `log` | miễn phí | **Mặc định** — chỉ ghi nhật ký, không gửi thật |

**Mẹo:** đặt `SMS_PROVIDER=zns,esms` để ưu tiên Zalo (rẻ), nếu số đó chưa có Zalo thì tự động chuyển sang SMS.

---

## Bước 3 — Điền khoá vào website

**Cách dễ nhất:** đăng nhập tài khoản admin → **Cài đặt hệ thống** (menu bên trái) → điền vào
các ô tương ứng → bấm Lưu. Có hiệu lực ngay, không cần deploy lại.

- Khoá webhook: mục **⚡ Đối soát chuyển khoản tự động** → bấm **🎲 Tự sinh khoá bí mật**,
  rồi sao chép sang SePay / Casso.
- Khoá SMS: mục **📩 Nhắn tin cho giáo viên** → chọn nhà cung cấp, dán khoá,
  bấm **📩 Gửi tin thử** để kiểm tra ngay.

---

### Cách thay thế: dùng biến môi trường

Vẫn hỗ trợ như cũ (giá trị lưu trong web sẽ được ưu tiên hơn).
Trên Render / VPS, thêm các biến sau:

```bash
# --- Bắt buộc: khoá bí mật cổng webhook ---
# Tự sinh bằng: python -c "import secrets;print(secrets.token_urlsafe(32))"
BANK_WEBHOOK_TOKEN=chuoi-bi-mat-that-dai-cua-ban

# --- Cách xử lý khi nhận được tiền ---
AUTO_ACTIVATE=1        # 1 = cộng lượt/VIP thẳng vào tài khoản (khuyên dùng)
                       # 0 = chỉ sinh mã, giáo viên tự nhập
BANK_SAI_SO=0          # cho phép lệch bao nhiêu đồng vẫn chấp nhận

# --- Nhắn tin: chọn 1 nhà cung cấp rồi điền khoá tương ứng ---
SMS_PROVIDER=esms

# nếu dùng eSMS.vn
ESMS_API_KEY=...
ESMS_SECRET_KEY=...
ESMS_BRANDNAME=EDUASSIST

# nếu dùng Zalo ZNS
# SMS_PROVIDER=zns
# ZNS_ACCESS_TOKEN=...
# ZNS_TEMPLATE_ID=...

# nếu dùng SpeedSMS
# SMS_PROVIDER=speedsms
# SPEEDSMS_TOKEN=...
# SPEEDSMS_SENDER=...

# nếu dùng Twilio
# SMS_PROVIDER=twilio
# TWILIO_SID=...
# TWILIO_TOKEN=...
# TWILIO_FROM=+1234567890
```

Chạy thử tại máy:

```bash
BANK_WEBHOOK_TOKEN=test-123 SMS_PROVIDER=log python run.py
```

---

## Bước 4 — Kiểm tra

Giả lập một giao dịch chuyển khoản (thay `EDU0007` bằng mã tài khoản thật):

```bash
curl -X POST https://<tên-miền>/webhook/bank \
  -H "Authorization: Apikey chuoi-bi-mat-that-dai-cua-ban" \
  -H "Content-Type: application/json" \
  -d '{"gateway":"Agribank","transferType":"in","transferAmount":10000,
       "content":"CT DEN EDU0007 3LUOT","referenceCode":"TEST001",
       "transactionDate":"2026-09-13 16:30:00"}'
```

Sau đó mở **Quản trị → ⚡ Chuyển khoản tự động** để xem kết quả.

---

## Hệ thống tự xử lý những tình huống nào?

| Tình huống | Cách xử lý |
|---|---|
| Chuyển đúng 10.000đ ghi `EDU0007 3LUOT` | Cộng 3 lượt + nhắn tin ngay |
| Chuyển đúng 100.000đ ghi `EDU0007 1NAM` | Bật VIP 1 năm + nhắn tin ngay |
| Chuyển 30.000đ (3 gói lẻ) | Tự cộng **9 lượt** |
| Ngân hàng ghi liền `EDU00073LUOT` | Vẫn tách đúng thành EDU0007 + gói lẻ |
| Quên ghi loại gói, chỉ ghi `EDU0007` | Tự suy ra gói theo số tiền |
| Ghi `1NAM` nhưng chỉ chuyển 10.000đ | Tự hạ xuống gói lẻ 3 lượt |
| Chuyển thiếu (5.000đ) | Treo lại, chờ admin đối soát tay |
| Quên ghi mã EDU | Treo lại, admin gán tay bằng nút **Duyệt** |
| Webhook bị gọi lại nhiều lần | Nhận diện trùng qua mã giao dịch, không cộng 2 lần |
| Giao dịch tiền ra | Bỏ qua |
| Giáo viên chưa khai số điện thoại | Vẫn kích hoạt bình thường, chỉ không nhắn tin |
| Gửi tin nhắn thất bại | Ghi vào Nhật ký tin nhắn, admin bấm **📩 Gửi lại** |

## Bảo mật

- Webhook **bắt buộc** có `BANK_WEBHOOK_TOKEN`; chưa đặt thì cổng bị khoá hoàn toàn (trả 401).
- Chấp nhận 3 kiểu xác thực: `Authorization: Apikey`, `Secure-Token`, và chữ ký `X-Signature` HMAC-SHA256.
- So sánh khoá bằng `hmac.compare_digest` để chống dò khoá theo thời gian phản hồi.
- Mỗi mã giao dịch ngân hàng chỉ xử lý một lần (`bank_tx.ref` là khoá duy nhất).
- Số điện thoại hiển thị dạng che bớt `0912***678` trong trang quản trị.

## Mở rộng thêm nhà cung cấp tin nhắn

Mở `app/modules/sms.py`, viết thêm một hàm rồi khai báo vào `PROVIDERS`:

```python
def _send_nhacungcap_moi(phone, text, **kw):
    r = _requests().post("https://api...", json={...}, timeout=TIMEOUT)
    return r.json().get("ok") is True, "Thông báo kết quả"

PROVIDERS["ten_moi"] = ("Tên hiển thị", _send_nhacungcap_moi)
```

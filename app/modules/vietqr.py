"""Sinh mã VietQR (chuẩn EMVCo) offline -> ảnh SVG nhúng thẳng vào trang.

Không gọi API bên ngoài nên luôn hiển thị được, kể cả khi máy chủ không có Internet.
Mã quét được bằng mọi app ngân hàng Việt Nam (Agribank, MB, VCB, Techcombank...).
"""
import io

BANK_BIN = {
    "agribank": "970405", "vietcombank": "970436", "vietinbank": "970415",
    "bidv": "970418", "mbbank": "970422", "techcombank": "970407",
    "acb": "970416", "vpbank": "970432", "tpbank": "970423", "sacombank": "970403",
}


def _tlv(tag, value):
    return f"{tag}{len(value):02d}{value}"


def _crc16(data: str) -> str:
    crc = 0xFFFF
    for ch in data.encode("utf-8"):
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def vietqr_payload(bank_bin, account, amount=None, content="", receiver=""):
    """Tạo chuỗi dữ liệu VietQR chuẩn EMVCo."""
    acc_info = _tlv("00", bank_bin) + _tlv("01", str(account))
    merchant = _tlv("00", "A000000727") + _tlv("01", acc_info) + _tlv("02", "QRIBFTTA")
    s = _tlv("00", "01") + _tlv("01", "12" if amount else "11") + _tlv("38", merchant)
    s += _tlv("53", "704")                       # VND
    if amount:
        s += _tlv("54", str(int(amount)))
    s += _tlv("58", "VN")
    if receiver:
        s += _tlv("59", receiver[:25])
    s += _tlv("62", _tlv("08", content[:25])) if content else ""
    s += "6304"
    return s + _crc16(s)


def qr_svg(text, box=7, border=2, dark="#0f172a", light="#ffffff"):
    """Vẽ QR thành SVG (chuỗi) — nhúng inline nên không cần file ảnh."""
    import qrcode
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M,
                       box_size=1, border=border)
    qr.add_data(text)
    qr.make(fit=True)
    m = qr.get_matrix()
    n = len(m)
    size = n * box
    # LUU Y: truoc day SVG ghi thang width/height = so module * 7 (thuong 259-315 px) nhung
    # khung hien thi chi rong 210 px va khong khoa tran -> phan thua cua ma QR tran sang phai,
    # bi cac o chu ben canh de len => khong quet duoc. Nay SVG luon co gian vua dung khung chua.
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
             f'viewBox="0 0 {n} {n}" preserveAspectRatio="xMidYMid meet" '
             f'style="display:block;width:100%;height:100%;max-width:100%;max-height:100%" '
             f'shape-rendering="crispEdges" role="img" aria-label="Ma QR chuyen khoan">',
             f'<rect width="{n}" height="{n}" fill="{light}"/>']
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                x2 = x
                while x2 + 1 < n and row[x2 + 1]:
                    x2 += 1
                parts.append(f'<rect x="{x}" y="{y}" width="{x2-x+1}" height="1" fill="{dark}"/>')
                x = x2 + 1
            else:
                x += 1
    parts.append("</svg>")
    return "".join(parts)


def build_qr(bank="mbbank", account="0939286896", amount=100000,
             content="EDUASSIST", receiver=""):
    bin_ = BANK_BIN.get(bank.lower(), bank)
    return qr_svg(vietqr_payload(bin_, account, amount, content, receiver))

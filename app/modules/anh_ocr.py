"""OCR ảnh chạy NỘI BỘ (RapidOCR — mô hình PP-OCRv4, ONNX, CPU) trong tiến trình riêng.

Phục vụ: giáo viên chỉ có ẢNH CHỤP thời khoá biểu — hệ thống đọc chữ + tọa độ
từng dòng ngay trên máy chủ, KHÔNG gửi tệp ra ngoài.
"""
import json
import os
import subprocess
import sys
import tempfile

TOI_DA_ANH = 8 * 1024 * 1024
HAN_TRUOT = 90  # giây

_DUOI_ANH = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")


def la_anh(ten):
    ten = (ten or "").lower()
    return ten.endswith(_DUOI_ANH)


def doc_tokens(data, ten=""):
    """Ảnh (bytes) → (ok, thong_bao, lines).

    lines: [{t, x0, y0, x1, y1, c}] — chữ + hình chữ nhật quanh từng dòng."""
    if not data:
        return False, "Tệp ảnh trống.", []
    if len(data) > TOI_DA_ANH:
        return False, "Ảnh lớn hơn 8 MB — hãy chụp nhẹ/chỉnh kích thước rồi thử lại.", []
    tmp_in = tmp_out = None
    try:
        fd, tmp_in = tempfile.mkstemp(suffix=".img")
        os.write(fd, data)
        os.close(fd)
        fd, tmp_out = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        worker = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "_ocr_anh_worker.py")
        p = subprocess.run([sys.executable, worker, tmp_in, tmp_out],
                           capture_output=True, timeout=HAN_TRUOT)
        if not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
            return False, "Bộ đọc ảnh chưa sẵn sàng hoặc lỗi — thử lại lần nữa.", []
        kq = json.load(open(tmp_out, encoding="utf-8"))
        if not kq.get("ok"):
            return False, kq.get("msg") or "Không đọc được ảnh.", []
        lines = kq.get("lines") or []
        if not lines:
            return False, ("Không nhận ra chữ nào trong ảnh — ảnh mờ/quá nhỏ, "
                           "hãy chụp rõ hơn."), []
        return True, "%d dòng chữ" % len(lines), lines
    except subprocess.TimeoutExpired:
        return False, "Đọc ảnh quá lâu (trên %d giây) — thử ảnh nhỏ/rõ hơn." % HAN_TRUOT, []
    except Exception as e:
        return False, "Lỗi đọc ảnh: %s" % e, []
    finally:
        for f in (tmp_in, tmp_out):
            try:
                if f and os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

"""Worker OCR ảnh — chạy trong TIẾN TRÌNH RIÊNG để cô lập RAM (RapidOCR ~280 MB peak).

Dùng:  python3 _ocr_anh_worker.py <ảnh_vào> <kết_quả.json>
Ghi ra JSON: {"ok": true, "lines": [{t,x0,y0,x1,y1,c}, ...]} hoặc {"ok": false, "msg": "..."}

Chạy tiến trình riêng vì:
  - gunicorn worker giữ RAM thấp (RAM OCR giải phóng hết khi worker thoát);
  - lỗi/crash của engine không làm sập web.
"""
import json
import sys


def main():
    anh_vao, file_ra = sys.argv[1], sys.argv[2]
    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR

        img = cv2.imread(anh_vao)
        if img is None:
            json.dump({"ok": False, "msg": "Không mở được tệp ảnh."},
                      open(file_ra, "w", encoding="utf-8"))
            return
        h, w = img.shape[:2]
        # ảnh chụp nhỏ → phóng to giúp nhận chữ nhỏ rõ hơn
        if max(h, w) < 1000:
            s = 1400.0 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
        elif max(h, w) > 4500:  # ảnh quá lớn → thu cho nhanh
            s = 4500.0 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        ocr = RapidOCR()
        kq, _ = ocr(img)
        ra = []
        for box, text, conf in (kq or []):
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            ra.append({"t": str(text), "x0": min(xs), "y0": min(ys),
                       "x1": max(xs), "y1": max(ys), "c": float(conf)})
        json.dump({"ok": True, "lines": ra},
                  open(file_ra, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        try:
            json.dump({"ok": False, "msg": "Lỗi đọc ảnh: %s" % e},
                      open(file_ra, "w", encoding="utf-8"))
        except Exception:
            pass


if __name__ == "__main__":
    main()

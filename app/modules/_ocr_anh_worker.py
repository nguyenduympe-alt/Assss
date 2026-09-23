"""Worker OCR ảnh — chạy trong TIẾN TRÌNH RIÊNG để cô lập RAM (OCR ~300 MB peak).

Dùng:  python3 _ocr_anh_worker.py <ảnh_vào> <kết_quả.json>
Ghi ra JSON: {"ok": true, "lines": [{t,x0,y0,x1,y1,c}, ...], "model": "mobile|server"}
             hoặc {"ok": false, "msg": "..."}

Chiến lược "tốt nhất cho CPU Cloud VPS" (đã đo thực tế):
  - PP-OCRv4 mobile (RapidOCR ONNX): nhanh ~4s/ảnh, chính xác cao.
  - ENSEMBLE 2-3 biến thể tiền xử lý (gốc / sắc nét / phóng to): GỘP token của các
    lần đọc (loại trùng) — bắt thêm các dòng chữ mờ bị bỏ sót.
  - PP-OCRv4 SERVER: chính xác hơn nhưng đo thực tế 138s/ảnh trên CPU VPS dùng chung
    → CHỈ bật khi đặt biến môi trường OCR_DUNG_SERVER=1 (mặc định tắt).
Tiến trình riêng vì gunicorn giữ RAM thấp + lỗi engine không làm sập web.
"""
import json
import os
import sys

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
DET_SERVER = os.path.join(MODEL_DIR, "ch_PP-OCRv4_det_server.onnx")
REC_SERVER = os.path.join(MODEL_DIR, "ch_PP-OCRv4_rec_server.onnx")
RAM_CAN_SERVER_MB = 1500.0


def ram_trong_mb():
    try:
        for dong in open("/proc/meminfo"):
            if dong.startswith("MemAvailable:"):
                return float(dong.split()[1]) / 1024.0
    except Exception:
        pass
    return 0.0


def chon_may_hoc():
    """Server chỉ khi: biến môi trường bật + file có + RAM trống đủ."""
    if os.environ.get("OCR_DUNG_SERVER", "").lower() not in ("1", "true", "yes"):
        return None, None
    if (os.path.exists(DET_SERVER) and os.path.exists(REC_SERVER)
            and ram_trong_mb() >= RAM_CAN_SERVER_MB):
        return DET_SERVER, REC_SERVER
    return None, None


def _tron_tokens(cac_bo):
    """Gộp nhiều lần đọc: loại token trùng (cùng chữ, cùng vị trí ±12px).
    Token của các lượt phụ chỉ nhận khi tin cậy ≥ 0.55 (tránh token rác)."""
    ra = list(cac_bo[0])
    for bo in cac_bo[1:]:
        for tk in bo:
            if tk.get("c", 0) < 0.55:
                continue
            trung = False
            for da in ra:
                if (tk["t"] == da["t"] and abs(tk["x0"] - da["x0"]) < 12
                        and abs(tk["y0"] - da["y0"]) < 12):
                    trung = True
                    if tk.get("c", 0) > da.get("c", 0):
                        da.update(tk)
                    break
            if not trung:
                ra.append(tk)
    return ra


def _tok_xu_ly(kq):
    ra = []
    for box, text, conf in (kq or []):
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        ra.append({"t": str(text), "x0": min(xs), "y0": min(ys),
                   "x1": max(xs), "y1": max(ys), "c": float(conf)})
    return ra


def main():
    anh_vao, file_ra = sys.argv[1], sys.argv[2]
    try:
        import cv2
        import numpy as np
        from rapidocr_onnxruntime import RapidOCR

        img = cv2.imread(anh_vao)
        if img is None:
            json.dump({"ok": False, "msg": "Không mở được tệp ảnh."},
                      open(file_ra, "w", encoding="utf-8"))
            return
        h, w = img.shape[:2]
        # ảnh chụp nhỏ → phóng to giúp nhận chữ nhỏ rõ hơn
        if max(h, w) < 1100:
            s = 1500.0 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_CUBIC)
        elif max(h, w) > 5000:  # ảnh quá lớn → thu cho nhanh
            s = 5000.0 / max(h, w)
            img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

        det_path, rec_path = chon_may_hoc()
        ten_may = "mobile"
        may = None
        if det_path:
            try:
                may = RapidOCR(det_model_path=det_path, rec_model_path=rec_path)
                ten_may = "server"
            except Exception:
                may, ten_may = None, "mobile"
        if may is None:
            may = RapidOCR()

        # Lần 1: ảnh đã chuẩn hoá
        bo_1 = _tok_xu_ly(may(img)[0])
        cac_bo = [bo_1]

        # Lần 2: bản sắc nét hơn (unsharp) — bắt chữ mờ; chỉ khi lần 1 chưa tốt
        diem_1 = len(bo_1) * (sum(t["c"] for t in bo_1) / max(1, len(bo_1)))
        if len(bo_1) < 60 and diem_1 < 55 and len(cac_bo[0]) >= 0:
            mo = cv2.GaussianBlur(img, (0, 0), 2.2)
            sac = cv2.addWeighted(img, 1.55, mo, -0.55, 0)
            bo_2 = _tok_xu_ly(may(sac)[0])
            cac_bo.append(bo_2)

        # Lần 3: phóng to thêm 1.3× — chữ quá nhỏ; chỉ khi vẫn nghèo token
        if sum(len(b) for b in cac_bo) < 48:
            h2, w2 = img.shape[:2]
            to = cv2.resize(img, (int(w2 * 1.3), int(h2 * 1.3)),
                            interpolation=cv2.INTER_CUBIC)
            bo_3 = _tok_xu_ly(may(to)[0])
            cac_bo.append(bo_3)

        ra = _tron_tokens(cac_bo)
        if not ra:
            json.dump({"ok": False, "msg": "Không nhận ra chữ nào trong ảnh."},
                      open(file_ra, "w", encoding="utf-8"))
            return
        json.dump({"ok": True, "lines": ra, "model": ten_may,
                   "so_lan_doc": len(cac_bo)},
                  open(file_ra, "w", encoding="utf-8"), ensure_ascii=False)
    except Exception as e:
        try:
            json.dump({"ok": False, "msg": "Lỗi đọc ảnh: %s" % e},
                      open(file_ra, "w", encoding="utf-8"))
        except Exception:
            pass


if __name__ == "__main__":
    main()

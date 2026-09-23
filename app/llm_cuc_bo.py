"""LỚP DÙNG CHỦNG cho AI cục bộ (Qwen2.5 trên máy chủ này, offline) — web gọi qua đây.

Mọi chức năng xử lý ngôn ngữ bằng AI của EduAssist ĐI QUA LỚP NÀY, không gọi
llama/HTTP trực tiếp. Model 1.5B là mặc định; hạ 0.5B chỉ khi thiếu RAM thật
(quyết định phía llm_server, kèm lý do); hết cả hai → trả lỗi "het_ram"/"ban";
lỗi dịch vụ được phân loại riêng, KHÔNG giả là thiếu RAM.

KHÔNG gửi dữ liệu giáo viên ra ngoài — mọi thứ ở lại máy chủ.
"""
import json
import os
import re
import threading

import requests

_KY_LA = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")  # CJK: leak của model

URL = os.environ.get("LLM_URL", "http://127.0.0.1:8021")
HAN_MAC_DINH = float(os.environ.get("LLM_HAN_GOI", "100"))

_cache = {"luc": 0.0, "du_lieu": None}
_khoa = threading.Lock()


def thong_tin(han=3.0, bo_cache=False):
    """Trạng thái dịch vụ AI: dict từ /health, hoặc None nếu không gọi được."""
    now = __import__("time").time()
    with _khoa:
        if not bo_cache and _cache["du_lieu"] is not None and now - _cache["luc"] < 2.0:
            return _cache["du_lieu"]
    try:
        r = requests.get(URL + "/health", timeout=han)
        if r.status_code == 200:
            du = r.json()
        else:
            du = {"ok": False, "trang_thai": "loi", "mo_hinh": None,
                  "ly_do": "Dịch vụ AI trả mã %s" % r.status_code,
                  "ma_loi": "loi_dich_vu"}
    except Exception as e:
        du = {"ok": False, "trang_thai": "khong_chay", "mo_hinh": None,
              "ly_do": "Dịch vụ AI cục bộ chưa chạy (%s)" % type(e).__name__,
              "ma_loi": "loi_dich_vu"}
    with _khoa:
        _cache["luc"] = now
        _cache["du_lieu"] = du
    return du


def co_san(han=3.0):
    """Dịch vụ có tiếp nhận được yêu cầu không (kể cả đang nạp model — sẽ xếp hàng)."""
    du = thong_tin(han)
    return bool(du) and du.get("trang_thai") in ("san_sang", "dang_tai")


def nhan_mo_hinh(du=None):
    """Nhãn tiếng Việt cho model đang dùng."""
    du = du or thong_tin() or {}
    m = du.get("mo_hinh") or ""
    if "1.5b" in m:
        return "Qwen2.5-1.5B (Q4)"
    if "0.5b" in m:
        return "Qwen2.5-0.5B (Q4) — hạ do RAM"
    return "chưa nạp"


def sinh(prompt_he_thong, prompt_nguoi, toi_da_token=120, nhiet_do=0.8, han=None):
    """Sinh văn bản. Trả dict:
      {ok: True, text, model, usage}             — thành công
      {ok: False, loai_loi: het_ram|ban|loi_dich_vu|het_han, msg} — thất bại rõ loại
    """
    han = float(han or HAN_MAC_DINH)
    body = {"messages": [{"role": "system", "content": prompt_he_thong},
                         {"role": "user", "content": prompt_nguoi}],
            "max_tokens": int(toi_da_token), "temperature": float(nhiet_do)}
    try:
        r = requests.post(URL + "/v1/chat/completions", json=body, timeout=han)
    except requests.Timeout:
        return {"ok": False, "loai_loi": "het_han",
                "msg": ("AI sinh quá %ds không xong (đang quá tải) — thử lại "
                        "hoặc dùng chế độ khác." % int(han))}
    except Exception as e:
        return {"ok": False, "loai_loi": "loi_dich_vu",
                "msg": "Không gọi được dịch vụ AI cục bộ: %s" % type(e).__name__}
    if r.status_code == 200:
        du = r.json()
        text = (du["choices"][0]["message"]["content"] or "").strip()
        # Lọc ký tự CJK do model đôi khi lẫn vào câu tiếng Việt
        if _KY_LA.search(text):
            text = _KY_LA.split(text)[0].strip().rstrip(",;:.")
        ok = bool(text) and len(text) >= 12
        return {"ok": ok, "text": text, "model": du.get("model"),
                "ly_do": du.get("ly_do"), "usage": du.get("usage"),
                "loai_loi": "ok" if ok else "chat_luong",
                "msg": "" if ok else "AI trả về rỗng hoặc ký tự lạ."}
    try:
        loi = r.json().get("detail")
        if isinstance(loi, str):
            loi = json.loads(loi)
    except Exception:  # noqa: BLE001
        loi = {"loai": "loi_dich_vu", "msg": "Dịch vụ AI trả mã %s" % r.status_code}
    return {"ok": False, "loai_loi": loi.get("loai", "loi_dich_vu"),
            "msg": loi.get("msg", "Lỗi dịch vụ AI chưa rõ.")}


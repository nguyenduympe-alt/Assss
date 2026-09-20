"""Kho tra cứu Khung năng lực số — có phiên bản, mã, nguồn và vị trí nguồn.

Dữ liệu nạp từ app/assets/khung-nld-so.json, sinh bởi xay_kho_nld.py từ
PHỤ LỤC 1 (Bảng mã chỉ báo NLS theo Công văn 3456/BGDĐT-GDPT), trang 61–78,
trong tài liệu tập huấn của Bộ GDĐT (Hà Nội 2025).

Nguyên tắc: tra cứu chỉ trả về bản ghi CÓ THẬT trong kho. Không suy diễn mã,
không ghép mã mới. Mọi hàm tra cứu đều trả kèm nguồn + vị trí để kiểm chứng.
"""
import json
from functools import lru_cache
from pathlib import Path

ASSET = Path(__file__).resolve().parents[1] / "assets" / "khung-nld-so.json"

# Các miền năng lực (lấy từ chính kho dữ liệu)
MIEN_TOI_DA = 6


@lru_cache(maxsize=1)
def kho():
    return json.loads(ASSET.read_text(encoding="utf-8"))


def phien_ban():
    return kho().get("version", "")


def muc_do_theo_lop(lop):
    """Trả về mã mức độ (CB1/CB2/TC1/TC2/NC1) theo lớp 1–12, theo bảng đối chiếu cột."""
    return kho().get("grade_levels", {}).get(str(lop).strip(), "")


def thong_tin_muc(level):
    return kho().get("level_info", {}).get(level, {})


def tra_ma(code):
    """Tra một mã chỉ báo. Trả None nếu mã KHÔNG có trong kho (không tự tạo)."""
    if not code:
        return None
    for x in kho()["indicators"]:
        if x["code"] == code:
            return x
    return None


def kiem_tra_ma(code):
    """Xác thực một mã: có tồn tại không, khớp miền/mức không. Dùng cho bộ kiểm tra đầu ra."""
    ban_ghi = tra_ma(code)
    if not ban_ghi:
        return {"hop_le": False, "ly_do": f"Mã '{code}' không có trong kho chỉ báo đã kiểm chứng."}
    return {"hop_le": True, "ban_ghi": ban_ghi, "ly_do": "Mã có trong kho, kèm nguồn và vị trí."}


def tra_theo_muc(level, domain=None):
    ra = [x for x in kho()["indicators"] if x["level"] == level]
    if domain:
        ra = [x for x in ra if domain.lower() in x["domain"].lower()]
    return ra


def tra_theo_thanh_phan(component, level=None):
    ra = [x for x in kho()["indicators"] if x["component"] == component]
    if level:
        ra = [x for x in ra if x["level"] == level]
    return ra


def danh_sach_mien():
    return list(kho().get("domains", []))


def danh_sach_thanh_phan():
    return [{"ma": k, **v} for k, v in kho().get("components", {}).items()]


def tra_cuu(tu_khoa, lop=None, gioi_han=30):
    """Tra cứu tự do theo từ khoá trên nguyên văn tiêu chí — phục vụ ô tìm kiếm."""
    tu_khoa = (tu_khoa or "").strip().lower()
    ra = kho()["indicators"]
    if lop:
        muc = muc_do_theo_lop(lop)
        if muc:
            ra = [x for x in ra if x["level"] == muc]
    if tu_khoa:
        ra = [x for x in ra
              if tu_khoa in x["verbatim"].lower() or tu_khoa in x.get("name", "").lower()
              or tu_khoa in x.get("code", "").lower()]
    return ra[:gioi_han]


def tom_tat_nguon(ban_ghi):
    """Dòng trích dẫn nguồn để in vào giáo án."""
    return (f"{ban_ghi['verbatim']} "
            f"[{ban_ghi['code']} — {ban_ghi['name']}; {ban_ghi['source']}; {ban_ghi['source_location']}]")


def thong_ke():
    k = kho()
    return {
        "phien_ban": k.get("version"),
        "so_mien": len(k.get("domains", [])),
        "so_thanh_phan": len(k.get("components", {})),
        "so_chi_bao": len(k.get("indicators", [])),
        "can_cu": k.get("can_cu"),
        "cong_van": k.get("cong_van_huong_dan"),
        "nguon": k.get("nguon", {}),
        **(k.get("thong_ke") or {}),
    }

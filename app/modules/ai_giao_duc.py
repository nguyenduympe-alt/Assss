"""Tích hợp GIÁO DỤC TRÍ TUỆ NHÂN TẠO (AI) vào kế hoạch bài dạy.

Căn cứ pháp lí (đã kiểm chứng, xem app/assets/khung-giao-duc-ai.json):
  • Quyết định 2422/QĐ-BGDĐT ngày 18/8/2026 — Khung nội dung giáo dục trí tuệ nhân tạo
    cho học sinh phổ thông.
  • Công văn 5588/BGDĐT-GDPT ngày 19/8/2026 — hướng dẫn triển khai từ năm học 2026-2027:
    nội dung cốt lõi 12 tiết/lớp/năm học; ba hình thức (chuyên đề, LỒNG GHÉP trong môn học
    và hoạt động giáo dục, hoạt động theo nhu cầu); lồng ghép KHÔNG làm thay đổi hoặc gia
    tăng yêu cầu cần đạt của môn học.

PHÂN BIỆT RÕ HAI LOẠI NỘI DUNG (giữ nguyên nguyên tắc của công cụ năng lực số):
  [QUY ĐỊNH] — câu chữ lấy từ văn bản của Bộ, không sửa một chữ.
  [ĐỀ XUẤT]  — phần hệ thống soạn cho bài học cụ thể; là gợi ý, giáo viên duyệt trước khi dùng.

Khung KHÔNG có mã chỉ báo cho từng mạch nội dung, nên hệ thống KHÔNG tự đặt mã: mọi chỗ
đều gọi đúng tên mạch (“Đạo đức AI”, “Các kỹ thuật và ứng dụng AI”…) và ghi rõ nguồn.
"""
import json
import re
from pathlib import Path

from .giao_an import khong_dau

ASSET = Path(__file__).resolve().parents[1] / "assets" / "khung-giao-duc-ai.json"

NGUON_NGAN = ("Khung nội dung giáo dục AI cho học sinh phổ thông — "
              "Quyết định 2422/QĐ-BGDĐT ngày 18/8/2026; hướng dẫn triển khai: "
              "Công văn 5588/BGDĐT-GDPT ngày 19/8/2026")

# quy định đưa vào mục tiêu cho mọi bài (đều là trích dẫn đã kiểm chứng)
QUY_DINH_MAC_DINH = ["long_ghep", "vua_suc", "khong_tai_khoan"]


def khoa():
    return json.loads(ASSET.read_text(encoding="utf-8"))


def muc_do_lop(lop):
    """Nhóm cấp học của lớp: '1-5' | '6-9' | '10-12' ('' nếu chưa rõ lớp)."""
    try:
        n = int(str(lop).strip())
    except (TypeError, ValueError):
        return ""
    if 1 <= n <= 5:
        return "1-5"
    if 6 <= n <= 9:
        return "6-9"
    if 10 <= n <= 12:
        return "10-12"
    return ""


def ten_cap(k):
    return {"1-5": "Cấp tiểu học", "6-9": "Cấp trung học cơ sở",
            "10-12": "Cấp trung học phổ thông"}.get(k, "")


def mach(k=None):
    ds = khoa()["mach"]
    if k is None:
        return ds
    return [m for m in ds if m["id"] == k]


def quy_dinh(*khoa_nao):
    ds = {x["khoa"]: x for x in khoa()["quy_dinh"]}
    return [ds[k] for k in (khoa_nao or ds) if k in ds]


def thong_ke():
    k = khoa()
    return {"so_mach": len(k["mach"]), "theo_cap": list(k["theo_cap"]),
            "can_cu": [x["van_ban"] for x in k["can_cu"]]}


# ------------------------------------------------------------------ chọn mạch nội dung
def _diem_tu_khoa(van_ban, ds_tu_khoa):
    """Điểm khớp từ khoá theo RANH GIỚI TỪ trên văn bản đã bỏ dấu.

    Cụm càng dài càng đáng tin (khớp “tri tue nhan tao” nặng hơn khớp “ai”).
    ”Ai” là từ rất dễ khớp nhầm, nên chỉ tính khi viết đúng cụm “ai” đứng riêng và
    đi kèm một từ chỉ công nghệ ở gần — nếu không thì bỏ qua.
    """
    n = " " + re.sub(r"\s+", " ", khong_dau(van_ban or "")) + " "
    diem, khop = 0.0, []
    for tk in ds_tu_khoa:
        tk_kd = khong_dau(tk)
        if re.search(r"\b" + re.escape(tk_kd) + r"\b", n):
            if tk_kd == "ai":
                tiep = n[n.find(" ai ") + 4:n.find(" ai ") + 4 + 26] if " ai " in n else ""
                if not re.search(r"\b(cong cu|tro ly|nhan dien|chatbot|tao sinh|dung|su dung|"
                                 r"kiem chung|thiet bi|phan mem|tri tue)\b", tiep):
                    continue
            diem += 1 + len(tk_kd.split()) * 0.5
            khop.append(tk)
    return diem, khop


def goi_y(lop, mon="", ten_bai="", van_ban="", toi_da=2, mach_chon=None):
    """Chọn mạch nội dung giáo dục AI phù hợp với bài (có căn cứ, không gán bừa).

    Trả về (danh sách, cảnh báo). Mỗi mục gồm: tên mạch, nội dung khung theo cấp,
    đoạn trích [QUY ĐỊNH], và phần [ĐỀ XUẤT] (mục tiêu, hoạt động, sản phẩm, minh chứng).
    """
    k = muc_do_lop(lop)
    if not k:
        return [], ["Chưa xác định được lớp của giáo án nên chưa chọn được nội dung giáo dục AI. "
                    "Hãy ghi rõ “Lớp: …” hoặc chọn lớp trước khi chạy."]

    kho_dl = khoa()
    mach_theo_id = {m["id"]: m for m in kho_dl["mach"]}
    cap = kho_dl["theo_cap"][k]
    canh_bao = []

    if mach_chon:
        ra = []
        for mid in mach_chon:
            if mid not in mach_theo_id:
                canh_bao.append(f"Mạch “{mid}” không có trong Khung — đã bỏ qua.")
                continue
            ra.append(_mot_muc(kho_dl, mach_theo_id[mid], k, lop, co_so="giáo viên tự chọn"))
        return ra, canh_bao

    diem = {}
    khop = {}
    for mid, ds_tk in kho_dl["tu_khoa_goi_y"].items():
        d, kh = _diem_tu_khoa(van_ban, ds_tk)
        if d:
            diem[mid] = d
            khop[mid] = kh
    # gợi ý theo môn học: Công văn 5588 có nêu ví dụ lồng ghép cho từng môn
    mon_kd = khong_dau(mon or "")
    for ten_mon, ds in kho_dl["goi_y_theo_mon"].items():
        if ten_mon and ten_mon in mon_kd:
            for i, mid in enumerate(ds):
                diem[mid] = diem.get(mid, 0) + (1.5 if i == 0 else 0.8)
                khop.setdefault(mid, []).append(f"môn {mon}")

    if not diem:
        # Không có căn cứ nào trong bài: KHÔNG gán bừa — đưa 1 mục “cần giáo viên duyệt”.
        mid = "M3"
        canh_bao.append("Bài học chưa nêu hoạt động nào liên quan tới AI. Hệ thống đưa một gợi ý "
                        "ở dạng “cần giáo viên duyệt”, mặc định KHÔNG tích — chỉ dùng nếu thầy/cô "
                        "thật sự tổ chức hoạt động này trong tiết học.")
        x = _mot_muc(kho_dl, mach_theo_id[mid], k, lop, co_so="", can_duyet=True)
        return [x], canh_bao

    xep = sorted(diem.items(), key=lambda kv: (-kv[1], kv[0]))[:max(1, toi_da)]
    ra = []
    for mid, _d in xep:
        co_so = ""
        if khop.get(mid):
            co_so = ("khớp với nội dung bài: “"
                 + "”, “".join(list(dict.fromkeys(khop[mid]))[:3]) + "”")
        ra.append(_mot_muc(kho_dl, mach_theo_id[mid], k, lop, co_so=co_so))
    canh_bao.append(f"Đã đối chiếu Khung giáo dục AI — {cap['ten_cap']} ({cap['huong'][:60]}…).")
    return ra, canh_bao


def _mot_muc(kho_dl, m, k, lop, co_so="", can_duyet=False):
    dx = (kho_dl["goi_y_hoat_dong"].get(m["id"]) or {}).get(k) or {}
    theo_lop = ""
    if k == "1-5" and str(lop).strip() in kho_dl.get("theo_lop_tieu_hoc", {}):
        theo_lop = kho_dl["theo_lop_tieu_hoc"][str(lop).strip()]
    return {
        "id": m["id"],
        "ten_mach": m["ten"],
        "tom_tat": m["tom_tat"],
        "muc_do": m.get("muc_do", ""),
        "cap": k,
        "ten_cap": ten_cap(k),
        "huong_cap": kho_dl["theo_cap"][k]["huong"],
        "noi_dung_theo_lop": theo_lop,
        "de_xuat": {
            "muc_tieu": dx.get("muc_tieu", ""),
            "hoat_dong": dx.get("hoat_dong", ""),
            "san_pham": dx.get("san_pham", ""),
            "minh_chung": dx.get("minh_chung", ""),
        },
        "quy_dinh": quy_dinh(*QUY_DINH_MAC_DINH),
        "nguon": NGUON_NGAN,
        "co_so": co_so,
        "can_duyet": can_duyet,
    }


# ------------------------------------------------------------------ soạn hoạt động
def soan_hoat_dong(ten_bai, lop, mon, chon, thoi_luong=6):
    """Soạn hoạt động giáo dục AI để chèn vào tiến trình bài dạy (lồng ghép)."""
    if not chon:
        return None
    ten = "Hoạt động tích hợp giáo dục AI (QĐ 2422/QĐ-BGDĐT)"
    muc_tieu = "; ".join(f"“{x['ten_mach']}”: {x['de_xuat']['muc_tieu']}" for x in chon)
    return {
        "ten": ten,
        "muc_tieu": muc_tieu,
        "ma": "AI",
        "thoi_luong": thoi_luong,
        "gv": _gv(chon, lop, mon),
        "hs": _hs(chon, lop),
        "cong_cu": _cong_cu(lop),
        "cac_buoc": _cac_buoc(chon, lop),
        "san_pham": "; ".join(dict.fromkeys(x["de_xuat"]["san_pham"] for x in chon if x["de_xuat"]["san_pham"])),
        "danh_gia": "; ".join(dict.fromkeys(x["de_xuat"]["minh_chung"] for x in chon if x["de_xuat"]["minh_chung"])),
        "cap_hoc": ten_cap(muc_do_lop(lop)),
        "ten_bai": ten_bai,
    }


def _cong_cu(lop):
    if muc_do_lop(lop) == "1-5":
        return ("Thiết bị do giáo viên chuẩn bị và điều khiển (máy tính, máy chiếu); sản phẩm mẫu "
                "của công cụ AI được giáo viên chuẩn bị TRƯỚC giờ học. Không yêu cầu học sinh dùng "
                "tài khoản cá nhân (theo Quyết định 2422/QĐ-BGDĐT).")
    return ("Công cụ AI do nhà trường/giáo viên rà soát trước; học sinh dùng theo hướng dẫn, "
            "không nhập dữ liệu cá nhân và ghi lại câu lệnh đã dùng.")


def _gv(chon, lop, mon):
    cap = muc_do_lop(lop)
    ra = ["Chuẩn bị trước sản phẩm/câu trả lời mẫu của AI (đã kiểm tra chỗ đúng, chỗ sai).",
          "Nêu nhiệm vụ và tiêu chí đánh giá trước khi học sinh làm; nhắc không nhập dữ liệu cá nhân."]
    if cap == "1-5":
        ra.insert(0, "Tổ chức cho học sinh quan sát, thảo luận; giáo viên thao tác trên thiết bị của lớp.")
    if cap == "10-12":
        ra.insert(0, "Giao vấn đề và định hướng; kiểm soát ở khâu đánh giá, phản biện kết quả.")
    ra.append("Chốt lại phần học sinh tự làm được và phần AI chỉ hỗ trợ; hướng dẫn cách ghi nguồn.")
    return " ".join(ra)


def _hs(chon, lop):
    cap = muc_do_lop(lop)
    if cap == "1-5":
        return ("Quan sát, nêu điều nhận ra; đối chiếu với sách giáo khoa; thảo luận nhóm và trả lời "
                "câu hỏi của giáo viên; không tự nhập thông tin cá nhân.")
    if cap == "6-9":
        return ("Thực hiện nhiệm vụ theo hướng dẫn, ghi lại câu lệnh đã dùng và kết quả; kiểm tra lại "
                "kết quả bằng sách giáo khoa/nguồn tham khảo; chỉnh sửa sản phẩm theo phản hồi.")
    return ("Phân tích nhiệm vụ, thử nghiệm, phản biện kết quả của AI; đề xuất phương án; trình bày "
            "phần mình tự quyết định và cách kiểm chứng thông tin.")


def _cac_buoc(chon, lop):
    ten_mach = ", ".join(x["ten_mach"] for x in chon)
    cap = muc_do_lop(lop)
    if cap == "1-5":
        return (f"1) Giáo viên nêu tình huống gắn với bài học ({ten_mach}). "
                "2) Học sinh quan sát sản phẩm mẫu của AI do giáo viên trình chiếu. "
                "3) Học sinh đối chiếu với sách giáo khoa, nêu chỗ chưa đúng và cách kiểm tra lại. "
                "4) Giáo viên chốt: AI có thể sai; người dùng phải kiểm chứng; không chia sẻ thông tin cá nhân.")
    if cap == "6-9":
        return (f"1) Giáo viên giao nhiệm vụ và tiêu chí. 2) Học sinh dùng công cụ AI đã được rà soát "
                f"để hỗ trợ nhiệm vụ ({ten_mach}). 3) Học sinh kiểm chứng kết quả và ghi lại câu lệnh, "
                "kết quả. 4) Nhóm trình bày, giáo viên chốt phần tự làm và phần AI hỗ trợ.")
    return (f"1) Nêu vấn đề/tiêu chí đánh giá. 2) Học sinh thử nghiệm với công cụ AI, thu thập kết quả "
            f"({ten_mach}). 3) Phản biện, so sánh, đánh giá độ tin cậy. 4) Đề xuất cải tiến và trình bày "
            "cách kiểm chứng; ghi rõ mức độ sử dụng AI.")

"""Lớp nhà cung cấp AI — nói thật về cái gì là AI, cái gì không.

BỐI CẢNH TÀI NGUYÊN (đo trên VPS 180.93.0.187 ngày 20/09/2026):
    CPU   : 1 lõi
    RAM   : 961 MB tổng, ~474 MB trống, swap 1 GB
    Đĩa   : ~5,3 GB trống
    Thư viện: CHƯA có torch / onnxruntime / transformers

KẾT LUẬN ĐÃ ĐO, KHÔNG PHỎNG ĐOÁN:
    Không thể chạy mô hình ngôn ngữ thực sự trên máy chủ này.
      - Mô hình sửa chính tả tiếng Việt nhỏ nhất dùng được (seq2seq ~220M tham số)
        cần khoảng 1,5–2 GB RAM ở chế độ float32, cộng ~400 MB nền của Python/torch
        => vượt 961 MB tổng. Cài torch tốn thêm ~2 GB đĩa.
      - Chạy trên 1 lõi CPU cũng quá chậm để dùng trong lớp học.
      - Ép chạy sẽ gây hết RAM, đẩy máy chủ sang swap và làm sập cả web hiện có.
    Vì vậy hệ thống KHÔNG nạp mô hình lớn và KHÔNG hứa huấn luyện LLM tại chỗ.

BA CHẾ ĐỘ ĐƯỢC KHAI BÁO RÕ:
    offline  — luật + từ điển thuật ngữ chạy nội bộ. KHÔNG PHẢI MÔ HÌNH AI.
               Nhãn hiển thị cho giáo viên: "Bộ kiểm tra nội bộ (không phải AI)".
    local    — mô hình mở chạy trong máy chủ, chỉ bật khi đo thấy đủ tài nguyên.
    external — dịch vụ AI của bên thứ ba. CHỈ chạy khi người dùng đã đồng ý;
               phải nêu rõ nhà cung cấp, dữ liệu gửi đi và chi phí.

Không có nhánh nào tự động gửi nội dung giáo án ra ngoài.
"""
import os
import shutil
from pathlib import Path

# --- Hạn mức tài nguyên tối thiểu để cho phép chạy mô hình nội bộ (đã tính dư an toàn) ---
CAN_RAM_MB = 2048      # RAM trống tối thiểu trước khi nạp mô hình
CAN_DIA_MB = 3000      # đĩa trống tối thiểu
CAN_CPU = 2            # số lõi tối thiểu


def do_tai_nguyen():
    """Đo tài nguyên thật của máy đang chạy."""
    ram_tong = ram_trong = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            so = {}
            for dong in f:
                p = dong.split(":")
                if len(p) == 2:
                    so[p[0].strip()] = int(p[1].split()[0])
            ram_tong = so.get("MemTotal", 0) // 1024
            ram_trong = so.get("MemAvailable", 0) // 1024
    except OSError:
        pass
    dia = shutil.disk_usage(str(Path(os.environ.get("DB_DIR", "/tmp")).anchor or "/"))
    return {
        "ram_tong_mb": ram_tong,
        "ram_trong_mb": ram_trong,
        "dia_trong_mb": dia.free // (1024 * 1024),
        "cpu": os.cpu_count() or 1,
    }


def co_mo_hinh_noi_bo():
    """Có mô hình mở nào đã cài sẵn trong máy chủ chưa?"""
    try:
        import onnxruntime  # noqa: F401
        return True, "onnxruntime"
    except ImportError:
        pass
    try:
        import transformers  # noqa: F401
        return True, "transformers"
    except ImportError:
        pass
    return False, ""


def danh_gia_kha_thi():
    """Trả về báo cáo tài nguyên + kết luận có chạy được mô hình nội bộ hay không."""
    tn = do_tai_nguyen()
    co, ten = co_mo_hinh_noi_bo()
    thieu = []
    if tn["ram_trong_mb"] < CAN_RAM_MB:
        thieu.append(f"RAM trống {tn['ram_trong_mb']} MB < {CAN_RAM_MB} MB cần thiết")
    if tn["dia_trong_mb"] < CAN_DIA_MB:
        thieu.append(f"đĩa trống {tn['dia_trong_mb']} MB < {CAN_DIA_MB} MB cần thiết")
    if tn["cpu"] < CAN_CPU:
        thieu.append(f"CPU {tn['cpu']} lõi < {CAN_CPU} lõi cần thiết")
    if not co:
        thieu.append("chưa cài thư viện suy luận (onnxruntime hoặc transformers)")
    return {
        "tai_nguyen": tn,
        "nguong_yeu_cau": {"ram_mb": CAN_RAM_MB, "dia_mb": CAN_DIA_MB, "cpu": CAN_CPU},
        "co_mo_hinh_noi_bo": co,
        "ten_thu_vien": ten,
        "chay_duoc_mo_hinh_noi_bo": not thieu,
        "ly_do_khong_chay_duoc": thieu,
    }


# --- Đăng ký nhà cung cấp ---------------------------------------------------
_NHA_CUNG_CAP = {}


def dang_ky(ma, nhan, la_ai, ham, mo_ta="", can_dong_y=False, nha_cung_cap="", chi_phi=""):
    _NHA_CUNG_CAP[ma] = {"ma": ma, "nhan": nhan, "la_mo_hinh_ai": bool(la_ai), "ham": ham,
                         "mo_ta": mo_ta, "can_dong_y": bool(can_dong_y),
                         "nha_cung_cap": nha_cung_cap, "chi_phi": chi_phi}


def danh_sach():
    """Danh sách nhà cung cấp kèm nhãn trung thực để hiển thị cho giáo viên."""
    ra = []
    for ncc in _NHA_CUNG_CAP.values():
        ra.append({
            "ma": ncc["ma"], "nhan": ncc["nhan"],
            "la_mo_hinh_ai": ncc["la_mo_hinh_ai"],
            "nhan_trung_thuc": ("Mô hình AI" if ncc["la_mo_hinh_ai"]
                                else "Bộ kiểm tra nội bộ (KHÔNG phải mô hình AI)"),
            "mo_ta": ncc["mo_ta"], "can_dong_y": ncc["can_dong_y"],
            "nha_cung_cap": ncc["nha_cung_cap"], "chi_phi": ncc["chi_phi"],
        })
    return ra


def lay(ma):
    return _NHA_CUNG_CAP.get(ma)


class ChuaDongY(RuntimeError):
    """Ném ra khi định dùng dịch vụ ngoài mà người dùng chưa đồng ý."""


def goi(ma, *a, dong_y_gui_du_lieu_ra_ngoai=False, **k):
    """Gọi một nhà cung cấp. Chặn cứng mọi lời gọi ra ngoài khi chưa được đồng ý."""
    ncc = _NHA_CUNG_CAP.get(ma)
    if not ncc:
        raise ValueError(f"Chưa đăng ký nhà cung cấp '{ma}'.")
    if ncc["can_dong_y"] and not dong_y_gui_du_lieu_ra_ngoai:
        raise ChuaDongY(
            f"'{ncc['nhan']}' gửi nội dung giáo án tới {ncc['nha_cung_cap']}. "
            "Cần giáo viên đồng ý trước khi gửi dữ liệu ra ngoài.")
    return ncc["ham"](*a, **k)


# --- Đề xuất dịch vụ ngoài để người dùng quyết định (chưa bật gì) ------------
def de_xuat_dich_vu_ngoai():
    """Trình bày cụ thể để người dùng đồng ý hay không. KHÔNG tự bật."""
    return [
        {"nha_cung_cap": "Google (Gemini API)", "dich_vu": "gemini-2.0-flash / flash-lite",
         "du_lieu_gui_di": "Toàn bộ đoạn văn bản của giáo án cần sửa, kèm môn/lớp và ngữ cảnh câu",
         "du_lieu_khong_gui": "Tệp .docx gốc, hình ảnh, thông tin tài khoản giáo viên",
         "chi_phi": "Có bậc miễn phí hạn mức thấp; trả theo token khi vượt (tham khảo ~0,1 USD/1 triệu token vào)",
         "luu_y": "Nội dung giáo án là dữ liệu của nhà trường — cần nhà trường đồng ý trước khi bật.",
         "can_dong_y": True},
        {"nha_cung_cap": "OpenAI", "dich_vu": "GPT-4o mini",
         "du_lieu_gui_di": "Tương tự: phần văn bản cần sửa và ngữ cảnh",
         "du_lieu_khong_gui": "Tệp gốc, hình ảnh, thông tin tài khoản",
         "chi_phi": "Trả theo token, khoảng vài chục nghìn đồng cho hàng nghìn lượt sửa",
         "luu_y": "Cần khoá API và sự đồng ý của nhà trường.", "can_dong_y": True},
        {"nha_cung_cap": "Máy chủ nội bộ (tự chạy)", "dich_vu": "Mô hình mở tiếng Việt",
         "du_lieu_gui_di": "Không gửi ra ngoài — dữ liệu ở lại máy chủ",
         "du_lieu_khong_gui": "Tất cả",
         "chi_phi": "Không tốn phí API, nhưng cần nâng cấp máy chủ: từ 4 lõi và 8 GB RAM trở lên",
         "luu_y": "VPS hiện tại (1 lõi, 961 MB RAM) KHÔNG đủ. Cần nâng cấp gói trước.",
         "can_dong_y": False},
    ]


def nhan_ban_ket_qua(ma):
    """Nhãn phải in kèm kết quả, để không nhầm bộ luật với AI."""
    ncc = _NHA_CUNG_CAP.get(ma)
    if not ncc:
        return ""
    if ncc["la_mo_hinh_ai"]:
        return f"Do mô hình AI ({ncc['nhan']}) đề xuất — giáo viên phải duyệt trước khi dùng."
    return (f"Do bộ kiểm tra nội bộ ({ncc['nhan']}) đề xuất. Đây KHÔNG phải mô hình AI; "
            "kết quả dựa trên luật và từ điển thuật ngữ, có thể bỏ sót lỗi cần ngữ cảnh.")


def _dang_ky_mac_dinh():
    """Đăng ký sẵn bộ kiểm tra nội bộ để nhãn luôn hiển thị đúng bản chất."""
    if "offline" not in _NHA_CUNG_CAP:
        dang_ky("offline", "Bộ kiểm tra nội bộ EduAssist (luật + từ điển thuật ngữ)",
                False, None,
                mo_ta="Kiểm tra chính tả, tra cứu chỉ báo và kiểm tra cấu trúc bằng luật. "
                      "Không phải mô hình AI đã huấn luyện.")


_dang_ky_mac_dinh()

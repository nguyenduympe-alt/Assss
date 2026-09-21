"""Thiết kế hoạt động tích hợp DỰA TRÊN NỘI DUNG THẬT của từng giáo án.

Nguyên tắc:

1. **Đọc bài trước, thiết kế sau.** Hệ thống đọc giáo án thầy/cô tải lên (tên bài, yêu cầu cần đạt,
   tiến trình, đồ dùng dạy học), rút ra *cụm nội dung* của bài và *các hoạt động thật* đang có,
   rồi mới ghép hoạt động tích hợp bám vào đúng chỗ trong tiến trình đó. Toàn bộ chạy trên máy chủ
   của trường — không gửi nội dung giáo án ra ngoài.
2. **Đa dạng, sinh động.** Có 10 kiểu tổ chức lớp học khác nhau (trạm, trò chơi tiếp sức, phiếu
   ba cột, cặp đôi chia sẻ, đóng vai, sản phẩm số nhỏ, kiểm chứng chéo hai nguồn, sơ đồ tư duy,
   phóng viên nhỏ, hội đồng phản biện), cùng phần mở đầu và phần chốt riêng cho tiểu học và
   THCS–THPT. Kiểu được chọn theo (tên bài + mã tiêu chí/mạch + cấp học) nên **hai giáo án khác
   nhau cho ra thiết kế khác nhau**, và **hai mạch trong cùng một bài cũng không trùng kiểu**.
   Cách chọn là tất định (hash nội dung): chạy lại một giáo án luôn ra đúng thiết kế cũ.
3. **Không tự đặt mã, không bịa số liệu.** Thiết kế chỉ mô tả việc dạy–học; mã vẫn lấy từ kho của
   văn bản (xem `nld_tich_hop` / `ai_giao_duc`).
"""

import hashlib
import re

from .giao_an import gon, khong_dau

# ------------------------------------------------------------------ đọc bài

TB_TU = [("máy chiếu", "máy chiếu"), ("máy tính bảng", "máy tính bảng"),
         ("máy tính", "máy tính"), ("điện thoại", "điện thoại"),
         ("phiếu học tập", "phiếu học tập"), ("bảng con", "bảng con"),
         ("sách giáo khoa", "sách giáo khoa"), ("tranh ảnh", "tranh ảnh"),
         ("video", "video/clip"), ("bảng nhóm", "bảng nhóm"), ("thẻ màu", "thẻ màu"),
         ("loa", "loa")]

# Từ khoá chỉ hoạt động trong tiến trình — dùng để biết hoạt động mới chèn vào chỗ nào.
TU_HOAT_DONG = ("tim", "tra cuu", "thuc hanh", "luyen tap", "van dung", "hinh thanh", "kham pha")

_RE_BAI = re.compile(r"^\s*(?:bài|bai)\s*(?:số\s*)?\d+\s*[:.\-–]?\s*", re.I)


def _ngan(t, n=70):
    """Cắt gọn một cụm nội dung cho vừa câu văn."""
    t = " ".join((t or "").split())
    t = _RE_BAI.sub("", t).strip(" .:;-–")
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0] + "…"
    return t


def _cum_noi_dung(ten_bai, muc_tieu, van_ban):
    """Cụm nội dung ngắn nhất mô tả BÀI NÀY (dùng để viết hoạt động cho sát bài)."""
    if ten_bai and len(ten_bai.strip()) >= 6:
        return _ngan(ten_bai, 64)
    # không có tên bài: lấy mệnh đề đầu của yêu cầu cần đạt
    for dong in (muc_tieu or []):
        t = gon(dong)
        if len(t) < 12:
            continue
        t = re.sub(r"^\s*\d+\s*[.)]\s*", "", t)
        t = re.sub(r"^\s*(?:kiến thức|năng lực|phẩm chất)\s*[:：]\s*", "", t, flags=re.I)
        cau = re.split(r"[.;:]", t)[0]
        if len(cau) >= 12:
            return _ngan(cau, 64)
    return _ngan(van_ban, 48) or "nội dung bài học"


def _thiet_bi_trong_bai(van_ban, thiet_bi="co"):
    """Đồ dùng/thiết bị chính có thật trong giáo án (để hoạt động không “vẽ” ra thứ lớp không có)."""
    kd = khong_dau(van_ban or "")
    co = [ten for tu, ten in TB_TU if khong_dau(tu) in kd]
    if thiet_bi == "khong_co":
        uu_tien = [x for x in co if x in ("phiếu học tập", "bảng con", "tranh ảnh", "thẻ màu",
                                          "sách giáo khoa", "bảng nhóm")]
        return ", ".join(uu_tien[:3]) or "phiếu học tập giấy, tranh ảnh in sẵn"
    if co:
        return ", ".join(dict.fromkeys(co))[:120]
    return "máy chiếu, phiếu học tập" if thiet_bi != "khong_co" else "phiếu học tập giấy"


def _hoat_dong_trong_bai(pt):
    """Danh sách hoạt động thật của bài (tên + vị trí), đọc từ tiến trình đã phân tích."""
    tt = (pt or {}).get("tien_trinh") or {}
    ra = []
    if tt.get("kieu") == "bang":
        vi = tt.get("vi_tri")
        ra = [{"ten": x["ten"], "vi_tri": x["vi_tri"]} for x in (tt.get("hoat_dong") or [])]
    elif tt.get("kieu") == "doan":
        ra = [{"ten": x["ten"], "vi_tri": x["vi_tri"]} for x in (tt.get("hoat_dong") or [])]
    return ra


def _gan_vao_bang(doc, pt):
    """Hoạt động thật mà dòng tích hợp sẽ nằm trong đó (theo đúng cách chèn của hệ thống).

    Bảng tiến trình: hệ thống chèn sau dòng cuối cùng có từ khoá hoạt động học tập, tức là nằm
    trong hoạt động lớn chứa dòng đó. Đọc lại đúng logic đó để nói cho giáo viên biết.
    """
    tt = (pt or {}).get("tien_trinh") or {}
    if tt.get("kieu") != "bang" or not doc.tables:
        return ""
    try:
        table = doc.tables[tt["vi_tri"]]
    except (IndexError, KeyError):
        return ""
    hang = table.rows
    if len(hang) < 2:
        return ""
    vitri = None
    for k in ("hinh thanh kham pha luyen tap thuc hanh tra cuu tim", "van dung"):
        for ri in range(len(hang) - 1, 0, -1):
            noi = khong_dau(" ".join(gon(c.text) for c in hang[ri].cells))
            if any(x in noi for x in k.split()):
                vitri = ri
                break
        if vitri is not None:
            break
    if vitri is None:
        vitri = len(hang) - 2 if len(hang) > 2 else 1
    vitri = max(1, vitri)
    # lùi về đầu hoạt động lớn chứa dòng đó
    dau = vitri
    for ri in range(vitri, 0, -1):
        o = gon(hang[ri].cells[0].text) if hang[ri].cells else ""
        if re.match(r"^\s*\d+\s*\.\s*(?!\d)\S", o):
            dau = ri
            break
    ten = gon(hang[dau].cells[0].text)[:90] if hang[dau].cells else ""
    return ten or f"hoạt động thứ {dau} của tiến trình"


def _gan_vao_doan(pt):
    """Dạng đoạn văn: hệ thống chèn sau hoạt động luyện tập/vận dụng/thực hành cuối cùng."""
    ds = [x for x in _hoat_dong_trong_bai(pt)]
    if not ds:
        return ""
    chon = ds[0]
    for x in ds:
        kd = khong_dau(x["ten"])
        if any(k in kd for k in ("luyen tap", "van dung", "thuc hanh")):
            chon = x
    return chon["ten"][:90]


def doc_bai(doc=None, pt=None, ten_bai="", van_ban="", muc_tieu=None, thiet_bi="co"):
    """Bối cảnh bài học dùng cho việc thiết kế hoạt động."""
    muc_tieu = muc_tieu or []
    if doc is not None and not van_ban:
        try:
            from .nld_tich_hop import noi_dung_bai
            van_ban = noi_dung_bai(doc)
        except Exception:                       # pragma: no cover - chỉ để không vỡ luồng chính
            van_ban = "\n".join(p.text for p in doc.paragraphs)
    gan = _gan_vao_bang(doc, pt) if doc is not None else ""
    if not gan:
        gan = _gan_vao_doan(pt) or "phần hoạt động chính của bài"
    return {
        "bai": _ngan(ten_bai, 70) if ten_bai else "",
        "nd": _cum_noi_dung(ten_bai, muc_tieu, van_ban),
        "tb": _thiet_bi_trong_bai(van_ban, thiet_bi),
        "hoat_dong": _hoat_dong_trong_bai(pt),
        "gan_vao": gan,
        "van_ban": van_ban or "",
    }


# ------------------------------------------------------------------ 10 kiểu tổ chức
# Mỗi kiểu: tên kiểu · mô tả hoạt động (dòng “Mục tiêu:” trong bảng) · cách tổ chức · báo cáo ·
# sản phẩm · minh chứng · việc giáo viên · việc học sinh. Chỗ trống: {nd} {n} {tb} {t2}.

KIEU = [
    {"id": "tram", "ten": "Trạm học tập",
     "muc_tieu": "Học sinh luân phiên qua các trạm nhỏ để xử lý từng phần việc của “{nd}”",
     "than": "chia lớp thành {n} trạm, mỗi trạm một nhiệm vụ nhỏ về “{nd}”, các nhóm luân phiên "
             "rồi ghi kết quả vào phiếu chung của nhóm",
     "bao_cao": "các nhóm treo phiếu trạm lên bảng, cả lớp đi xem và đối chiếu với tiêu chí đã nêu",
     "sp": "Phiếu kết quả của cả {n} trạm", "mc": "Mỗi trạm có ít nhất một ghi chú của nhóm",
     "gv": "Chuẩn bị {n} trạm (phiếu nhiệm vụ ở mỗi trạm) và đặt sẵn đồ dùng: {tb}.",
     "hs": "Làm nhiệm vụ ở từng trạm về “{nd}”, ghi lại kết quả và cách nhóm kiểm tra lại."},
    {"id": "tro_choi", "ten": "Trò chơi tiếp sức",
     "muc_tieu": "Học sinh chơi tiếp sức: mỗi đội hoàn thành một việc về “{nd}”, đội bạn kiểm tra lại",
     "than": "tổ chức tiếp sức theo đội, mỗi lượt một bạn lên thực hiện một việc liên quan tới "
             "“{nd}”, đội sau có nhiệm vụ kiểm tra kết quả của đội trước",
     "bao_cao": "đội kiểm tra nêu chỗ đúng/chỗ cần sửa của đội bạn, giáo viên chốt cách làm đúng",
     "sp": "Bảng kết quả của các đội kèm phần kiểm tra chéo", "mc": "Đội nêu được vì sao chọn "
                                                                 "kết quả đó",
     "gv": "Chuẩn bị thẻ/lượt chơi và bảng ghi điểm; phổ biến luật chơi trước khi bắt đầu.",
     "hs": "Thực hiện lượt của đội mình và kiểm tra lại phần làm của đội bạn về “{nd}”."},
    {"id": "phieu_ba_cot", "ten": "Phiếu học tập ba cột",
     "muc_tieu": "Học sinh điền phiếu ba cột “đã biết – cần kiểm chứng – cách kiểm chứng” cho “{nd}”",
     "than": "phát phiếu ba cột “Điều em đã biết – Điều cần kiểm chứng – Cách kiểm chứng” cho từng "
             "cặp, nội dung xoay quanh “{nd}”",
     "bao_cao": "vài cặp đọc phiếu, cả lớp so cột “cách kiểm chứng” của các cặp với nhau",
     "sp": "Phiếu ba cột đã điền của từng cặp", "mc": "Cột “cách kiểm chứng” nêu được việc làm cụ thể",
     "gv": "In phiếu ba cột và nêu ví dụ một dòng trước khi học sinh làm.",
     "hs": "Điền phiếu theo cặp về “{nd}” và nói rõ cặp sẽ kiểm chứng bằng cách nào."},
    {"id": "cap_doi", "ten": "Cặp đôi – chia sẻ",
     "muc_tieu": "Học sinh làm việc theo cặp: một bạn thực hiện, một bạn quan sát rồi đổi vai",
     "than": "cho học sinh làm theo cặp: một bạn thực hiện nhiệm vụ về “{nd}”, một bạn quan sát và "
             "ghi lại rồi đổi vai",
     "bao_cao": "người quan sát trình bày điều mình ghi được, sau đó cặp nêu kết luận chung",
     "sp": "Ghi chú của người quan sát + phần trình bày của cặp",
     "mc": "Cặp nêu được điều bạn quan sát phát hiện mà bạn làm chưa thấy",
     "gv": "Nêu rõ nhiệm vụ của bạn quan sát (ghi lại điều gì) trước khi cho học sinh làm.",
     "hs": "Lần lượt làm và quan sát bạn mình, ghi lại điều phát hiện về “{nd}”."},
    {"id": "dong_vai", "ten": "Đóng vai xử lý tình huống",
     "muc_tieu": "Học sinh đóng vai hai tình huống (một đúng, một sai) liên quan tới “{nd}”",
     "than": "dựng hai tình huống ngắn liên quan tới “{nd}” (một làm đúng, một làm sai); các nhóm "
             "chuẩn bị rồi đóng vai trước lớp",
     "bao_cao": "cả lớp chỉ ra chỗ làm sai và nói cách sửa; nhóm đóng vai ghi lại nhận xét",
     "sp": "Tiểu phẩm ngắn + bảng nhận xét của lớp",
     "mc": "Nhóm chỉ đúng chỗ sai và nêu cách làm đúng",
     "gv": "Chuẩn bị hai tình huống sát bài, phân vai và giới hạn thời gian rõ ràng.",
     "hs": "Đóng vai tình huống về “{nd}”, sau đó nêu điều nhóm mình rút ra."},
    {"id": "san_pham_so", "ten": "Sản phẩm số nhỏ",
     "muc_tieu": "Học sinh tạo một sản phẩm số ngắn minh hoạ “{nd}” và ghi nguồn tư liệu",
     "than": "mỗi nhóm tạo một sản phẩm số ngắn (một trang trình chiếu, ảnh chụp có chú thích hoặc "
             "bảng số liệu) minh hoạ “{nd}”",
     "bao_cao": "nhóm trình bày sản phẩm, nêu tư liệu đã dùng và cách kiểm tra lại",
     "sp": "Sản phẩm số của nhóm kèm danh mục nguồn",
     "mc": "Sản phẩm bám nội dung bài và có ghi nguồn tư liệu",
     "gv": "Kiểm tra thiết bị và tài khoản dùng chung trước giờ; nhắc không nhập dữ liệu cá nhân.",
     "hs": "Tạo sản phẩm số về “{nd}” theo nhóm, ghi rõ nguồn và nêu phần nào do máy, phần nào do "
           "nhóm làm."},
    {"id": "kiem_chung_cheo", "ten": "Kiểm chứng chéo hai nguồn",
     "muc_tieu": "Học sinh đối chiếu hai nguồn thông tin khác nhau về “{nd}” rồi kết luận",
     "than": "mỗi nhóm nhận hai nguồn thông tin khác nhau về “{nd}”, đối chiếu và ghi lại chỗ khớp, "
             "chỗ chưa khớp",
     "bao_cao": "các nhóm nêu chỗ chưa khớp và cách kiểm tra lại; giáo viên chốt cách chọn nguồn tin",
     "sp": "Bảng đối chiếu hai nguồn", "mc": "Chỉ ra được chỗ chưa khớp và cách kiểm tra lại",
     "gv": "Chuẩn bị hai nguồn (một nguồn có chỗ sai/chưa cập nhật) để học sinh tự phát hiện.",
     "hs": "So hai nguồn về “{nd}”, nêu nguồn nào đáng tin hơn và vì sao."},
    {"id": "so_do", "ten": "Sơ đồ tư duy",
     "muc_tieu": "Học sinh vẽ sơ đồ tư duy cho “{nd}” theo ba nhánh đã biết – cần kiểm chứng – việc sẽ làm",
     "than": "các nhóm vẽ sơ đồ tư duy cho “{nd}” với ba nhánh: “điều đã biết”, “điều cần kiểm chứng”, "
             "“việc sẽ làm trong tiết học”",
     "bao_cao": "nhóm dán sơ đồ, cả lớp xem nhánh “việc sẽ làm” và thống nhất việc cần làm trước",
     "sp": "Sơ đồ tư duy của nhóm", "mc": "Sơ đồ đủ ba nhánh và nêu được việc sẽ làm",
     "gv": "Vẽ mẫu một nhánh nhỏ trên bảng để học sinh biết cách ghi.",
     "hs": "Vẽ sơ đồ cho “{nd}” theo nhóm và giải thích nhánh “việc sẽ làm”."},
    {"id": "phong_van", "ten": "Phóng viên nhỏ",
     "muc_tieu": "Học sinh phỏng vấn nhanh các bạn trong lớp về “{nd}” rồi báo cáo điểm chung",
     "than": "vài học sinh làm “phóng viên” đi phỏng vấn nhanh các bạn về “{nd}” và ghi lại câu trả lời",
     "bao_cao": "nhóm phóng viên báo cáo điểm chung và điểm khác nhau giữa các câu trả lời",
     "sp": "Phiếu ghi câu trả lời phỏng vấn",
     "mc": "Nêu được điểm chung/khác nhau giữa các câu trả lời",
     "gv": "Đưa sẵn 2–3 câu hỏi phỏng vấn sát nội dung bài và giới hạn thời gian đi phỏng vấn.",
     "hs": "Đặt câu hỏi, ghi câu trả lời về “{nd}” rồi tổng hợp lại thành nhận xét."},
    {"id": "phan_bien", "ten": "Hội đồng phản biện",
     "muc_tieu": "Học sinh trình bày kết quả về “{nd}” và bị các nhóm khác phản biện",
     "than": "một nhóm trình bày kết quả về “{nd}”; các nhóm còn lại đặt câu hỏi phản biện theo "
             "tiêu chí đã nêu trước",
     "bao_cao": "nhóm trình bày trả lời từng câu hỏi, cả lớp thống nhất chỗ cần chỉnh lại",
     "sp": "Biên bản phản biện ngắn của lớp",
     "mc": "Câu hỏi phản biện bám vào sản phẩm của nhóm bạn",
     "gv": "Nêu trước tiêu chí phản biện (đúng nội dung, đủ căn cứ, rõ ràng) để học sinh hỏi đúng hướng.",
     "hs": "Trình bày hoặc đặt câu hỏi phản biện về “{nd}”, ghi lại điều nhóm mình cần sửa."},
]

MO_DAU_TIEU_HOC = [
    "giáo viên đưa một vật thật/tranh ảnh hoặc chiếu một mẩu ngắn về “{nd}” và hỏi cả lớp “điều gì "
    "đúng, điều gì chưa chắc”",
    "giáo viên kể một tình huống ngắn trong lớp học có liên quan tới “{nd}” rồi hỏi học sinh nhận "
    "ra điều gì",
    "giáo viên hỏi cả lớp một câu dễ trả lời về “{nd}” để mỗi bạn nói một ý trước khi làm việc nhóm",
]
MO_DAU_LON = [
    "giáo viên nêu một tình huống hoặc số liệu thật về “{nd}” để các nhóm dự đoán kết quả trước "
    "khi làm",
    "giáo viên giao một câu hỏi mở về “{nd}”; các nhóm ghi nhanh điều đã biết và điều cần tra cứu",
    "giáo viên cho xem hai nguồn thông tin khác nhau về “{nd}” và yêu cầu chỉ ra chỗ chưa khớp",
]
KET_TIEU_HOC = [
    "giáo viên hỏi 2–3 học sinh nói lại việc mình vừa làm và chốt một câu dễ nhớ về “{nd}”",
    "giáo viên cho cả lớp nhắc lại quy tắc an toàn và một điều cần nhớ về “{nd}”",
]
KET_LON = [
    "giáo viên chốt cách làm đúng, chỉ ra chỗ dễ sai và nối sang phần tiếp theo của bài",
    "giáo viên tổng kết tiêu chí đánh giá và giao việc vận dụng “{nd}” vào bài tập về nhà",
]


def _kN(khoa, n, da_dung=()):
    """Chọn chỉ số kiểu tổ chức theo hash nội dung — tất định, tránh trùng trong cùng bài."""
    goc = int(hashlib.md5(str(khoa).encode("utf-8")).hexdigest()[8:16], 16) % n
    for k in range(n):
        i = (goc + k) % n
        if i not in da_dung:
            return i
    return goc


def chia_thoi_luong(tong, n):
    """Chia tổng thời lượng cho các tiêu chí/mạch đã chọn — mỗi phần tối thiểu 4 phút.

    Trả về (danh sách số phút theo từng tiêu chí được thiết kế chi tiết, số tiêu chí được
    thiết kế). Tiêu chí còn lại vẫn nêu trong dòng “Mục tiêu:” nhưng không in thêm các bước,
    để tổng thời lượng trong bảng đúng bằng thời lượng thầy/cô đặt.
    """
    tong = max(4, int(tong or 6))
    n = max(1, int(n or 1))
    k = min(n, max(1, tong // 4))
    co_ban = tong // k
    phan = [co_ban] * (k - 1) + [tong - co_ban * (k - 1)]
    return phan, k


def _cat_phut(tong, ti_le):
    """Chia phút cho 4 bước, luôn ≥ 1 phút và tổng đúng bằng `tong`."""
    t1 = max(1, round(tong * ti_le[0]))
    t3 = max(1, round(tong * ti_le[1]))
    t4 = max(1, round(tong * ti_le[2]))
    t2 = max(1, tong - t1 - t3 - t4)
    return t1, t2, t3, t4


def thiet_ke(boi_canh, muc_tieu_chuan="", khoa="", thoi_luong=6, da_dung=(), cap_ngan=None):
    """Thiết kế MỘT hoạt động tích hợp bám nội dung bài.

    Trả về dict cùng cấu trúc hoạt động hiện có (`ten`, `muc_tieu`, `cac_buoc`, `gv`, `hs`,
    `san_pham`, `minh_chung`, `gan_vao`) + `kieu` để kiểm tra tính đa dạng.
    """
    nd = boi_canh.get("nd") or "nội dung bài học"
    tb = boi_canh.get("tb") or "máy chiếu, phiếu học tập"
    n = 3 if cap_ngan == "tieu_hoc" else 4
    khoa = khoa or (str(boi_canh.get("bai") or "") + "|" + nd)
    i = _kN(khoa, len(KIEU), da_dung)
    k = KIEU[i]
    tl = max(4, min(int(thoi_luong or 6), 12))
    t1, t2, t3, t4 = _cat_phut(tl, (0.15, 0.2, 0.15))
    fmt = lambda t: (t or "").format(nd=nd, n=n, tb=tb, t2=t2, bai=boi_canh.get("bai") or nd)
    mo = fmt((MO_DAU_TIEU_HOC if cap_ngan == "tieu_hoc" else MO_DAU_LON)[
        _kN(khoa + "|mở", len(MO_DAU_TIEU_HOC if cap_ngan == "tieu_hoc" else MO_DAU_LON))])
    ket = fmt((KET_TIEU_HOC if cap_ngan == "tieu_hoc" else KET_LON)[
        _kN(khoa + "|kết", len(KET_TIEU_HOC if cap_ngan == "tieu_hoc" else KET_LON))])
    buoc = (f"1) {mo[0].upper() + mo[1:]} ({t1} phút). "
            f"2) Tổ chức: {fmt(k['than'])} ({t2} phút). "
            f"3) Báo cáo: {fmt(k['bao_cao'])} ({t3} phút). "
            f"4) Kết thúc: {ket[0].upper() + ket[1:]} ({t4} phút).")
    return {
        "kieu": k["id"],
        "kieu_i": i,
        "kieu_ten": k["ten"],
        "ten": f"Hoạt động tích hợp — {k['ten'].lower()}",
        "muc_tieu": fmt(k["muc_tieu"]) + (f" (lồng vào: {boi_canh['gan_vao']})"
                                          if boi_canh.get("gan_vao") else ""),
        "cac_buoc": buoc,
        "gv": (fmt(k["gv"]) + (" " + muc_tieu_chuan.strip().rstrip(".") + "."
                               if muc_tieu_chuan else "")),
        "hs": fmt(k["hs"]),
        "san_pham": fmt(k["sp"]),
        "minh_chung": fmt(k["mc"]),
        "gan_vao": boi_canh.get("gan_vao") or "",
        "thoi_luong": tl,
        "dung_cu": tb,
        "nd": nd,
    }

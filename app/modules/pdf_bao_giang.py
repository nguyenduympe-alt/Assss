"""Xuất lịch báo giảng 1 tuần ra PDF theo mẫu trường học (khổ A4 ngang)."""
import io, os, datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

# Font đi kèm trong repo -> chạy được trên mọi máy chủ (Render, Railway, VPS...)
LOCAL_FONTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "fonts")
SYS_FONTS = "/usr/share/fonts/truetype/dejavu"
_reg = False


def _font_path(name):
    p = os.path.join(LOCAL_FONTS, name)
    return p if os.path.exists(p) else os.path.join(SYS_FONTS, name)


def _fonts():
    global _reg
    if _reg:
        return
    pdfmetrics.registerFont(TTFont("VN", _font_path("DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("VN-B", _font_path("DejaVuSans-Bold.ttf")))
    _reg = True


THU_NAME = {2: "Thứ Hai", 3: "Thứ Ba", 4: "Thứ Tư", 5: "Thứ Năm", 6: "Thứ Sáu", 7: "Thứ Bảy", 8: "Chủ Nhật"}


def build_pdf(meta, rows):
    """meta: dict(truong, to, giao_vien, tuan, tu_ngay, den_ngay, noi_dung_khac)
    rows: list dict(thu, buoi, tiet, lop, mon, tiet_pp, ten_bai, ghi_chu)"""
    _fonts()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=10 * mm, bottomMargin=10 * mm,
                            title=f"Lich bao giang tuan {meta.get('tuan','')}")
    S = lambda n, sz, b=False, al=0: ParagraphStyle(n, fontName="VN-B" if b else "VN", fontSize=sz,
                                                    leading=sz + 3, alignment=al)
    el = []
    head = Table([[Paragraph(meta.get("truong", "").upper(), S("a", 9, True, 1)),
                   Paragraph("LỊCH BÁO GIẢNG", S("b", 15, True, 1))],
                  [Paragraph("Tổ: " + meta.get("to", ""), S("c", 9, False, 1)),
                   Paragraph(f"TUẦN {meta.get('tuan','')} "
                             f"(Từ ngày {meta.get('tu_ngay','')} đến ngày {meta.get('den_ngay','')})"
                             + (f" · TKB áp dụng từ tuần {meta['ap_dung_tu_tuan']}" if meta.get("ap_dung_tu_tuan") else ""),
                             S("d", 10, False, 1))]],
                 colWidths=[70 * mm, 200 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    el += [head, Spacer(1, 3 * mm)]
    el.append(Paragraph("Họ và tên giáo viên: <b>%s</b>&nbsp;&nbsp;&nbsp;&nbsp;Môn dạy: <b>%s</b>"
                        % (meta.get("giao_vien", ""), meta.get("mon", "")), S("e", 10)))
    el.append(Spacer(1, 3 * mm))

    hdr = ["Thứ/Ngày", "Buổi", "Tiết", "Lớp", "Môn", "Tiết PPCT", "Tên bài dạy", "Đồ dùng / Ghi chú"]
    data = [[Paragraph(h, S("h", 9, True, 1)) for h in hdr]]
    spans = []
    nghi_rows = []
    ordered = sorted(rows, key=lambda r: (int(r.get("thu") or 9),
                                          0 if (r.get("buoi") or "Sáng").startswith("S") else 1,
                                          int(r.get("tiet") or 0)))
    i = 1
    group_start = {}
    for r in ordered:
        thu = int(r.get("thu") or 9)
        label = THU_NAME.get(thu, "") + (("\n" + r["ngay"]) if r.get("ngay") else "")
        if r.get("nghi"):
            nghi_rows.append(i)
        data.append([Paragraph(label.replace("\n", "<br/>"), S("x", 8.5, True, 1)),
                     Paragraph(r.get("buoi", ""), S("x", 8.5, False, 1)),
                     Paragraph(str(r.get("tiet", "") or ""), S("x", 8.5, False, 1)),
                     Paragraph(str(r.get("lop", "") or ""), S("x", 8.5, False, 1)),
                     Paragraph(str(r.get("mon", "") or ""), S("x", 8.5)),
                     Paragraph(str(r.get("tiet_pp", "") or ""), S("x", 8.5, False, 1)),
                     Paragraph(str(r.get("ten_bai", "") or ""), S("x", 8.5)),
                     Paragraph(str(r.get("ghi_chu", "") or ""), S("x", 8.5))])
        group_start.setdefault(thu, i)
        i += 1
    for thu, start in group_start.items():
        end = start
        while end + 1 < len(data) and int(ordered[end]["thu"] or 9) == thu:
            end += 1
        if end > start:
            spans.append(("SPAN", (0, start), (0, end)))
    if len(data) == 1:
        data.append([Paragraph("(Chưa có dữ liệu thời khoá biểu)", S("x", 9, False, 1))] + [""] * 7)
        spans.append(("SPAN", (0, 1), (-1, 1)))

    t = Table(data, colWidths=[26 * mm, 16 * mm, 12 * mm, 18 * mm, 30 * mm, 18 * mm, 90 * mm, 60 * mm],
              repeatRows=1)
    st = [("GRID", (0, 0), (-1, -1), 0.6, colors.black),
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d6efe6")),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for ri in nghi_rows:
        st.append(("BACKGROUND", (1, ri), (-1, ri), colors.HexColor("#ffe9ec")))
        st.append(("TEXTCOLOR", (6, ri), (6, ri), colors.HexColor("#be123c")))
    t.setStyle(TableStyle(st + spans))
    el.append(t)

    if meta.get("nghi"):
        el += [Spacer(1, 2 * mm), Paragraph("<b>Ghi chú:</b> Tuần này trùng kỳ nghỉ - " + meta["nghi"], S("n", 9))]
    if meta.get("noi_dung_khac"):
        el += [Spacer(1, 3 * mm), Paragraph("<b>Nội dung công tác khác:</b> " + meta["noi_dung_khac"], S("k", 9))]

    el.append(Spacer(1, 6 * mm))
    sign = Table([[Paragraph("DUYỆT CỦA TỔ TRƯỞNG CM", S("s", 9, True, 1)),
                   Paragraph(f"{meta.get('dia_danh','Sóc Trăng')}, ngày {meta.get('ngay_ky','....')} tháng {meta.get('thang_ky','....')} năm {meta.get('nam_ky','......')}<br/><b>GIÁO VIÊN</b>", S("s2", 9, False, 1))],
                  ["", Paragraph("<br/><br/><br/>" + meta.get("giao_vien", ""), S("s3", 9, True, 1))]],
                 colWidths=[135 * mm, 135 * mm])
    sign.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el.append(sign)

    doc.build(el)
    buf.seek(0)
    return buf

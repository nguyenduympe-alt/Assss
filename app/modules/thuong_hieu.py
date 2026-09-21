"""(LOGO-B) Thương hiệu EduAssist in lên tệp Word xuất ra.

Yêu cầu của thầy/cô: in logo lên tệp Word xuất ra (và trên hoá đơn/thông báo nâng VIP).

Cách làm: mỗi tệp Word do hệ thống xuất ra được gắn
  · DÒNG ĐẦU TRANG: logo EduAssist (ảnh thật) + tên hệ thống + đường dẫn website, kèm tên tài liệu nếu có;
  · CHÂN TRANG: “Hệ thống EduAssist — edugiaovien.com” + số trang (khi có nhiều trang).

Lưu ý an toàn: mọi thao tác đều nằm trong try/except — **không bao giờ** để việc in logo làm hỏng
việc xuất tệp của thầy/cô. Logo chỉ là dòng đầu/chân trang, KHÔNG chen vào nội dung bài soạn.
"""
import os

from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

_GOC = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))       # .../app
LOGO = os.path.join(_GOC, "static", "logo", "ea-mark-b-word.png")
TEN = "EduAssist"
PHU = "Trợ lý giáo viên"
WEB = "edugiaovien.com"
MAU_MUC = RGBColor(0x0F, 0x17, 0x2A)
MAU_PHU = RGBColor(0x64, 0x74, 0x8B)
CAO_LOGO_CM = 0.52


def _ke_duoi(p, mau="D6E7E3", day=6):
    """Kẻ một đường mảnh dưới dòng đầu trang cho gọn gàng."""
    pPr = p._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    bot = OxmlElement("w:bottom")
    bot.set(qn("w:val"), "single")
    bot.set(qn("w:sz"), str(day))
    bot.set(qn("w:space"), "4")
    bot.set(qn("w:color"), mau)
    bdr.append(bot)
    pPr.append(bdr)


def _so_trang(p):
    """Chèn số trang (trường PAGE của Word tự cập nhật khi mở/in)."""
    r = p.add_run()._r
    for loai, chu in (("begin", None), ("instr", "PAGE"), ("end", None)):
        if loai == "instr":
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = chu
            r.append(it)
        else:
            f = OxmlElement("w:fldChar")
            f.set(qn("w:fldCharType"), loai)
            r.append(f)
    return p


def _rong_trang_cm(section):
    try:
        return section.page_width.cm - section.left_margin.cm - section.right_margin.cm
    except Exception:
        return 16.0


def gan_dau_trang(doc, tieu_de="", phu=None, logo=True):
    """Gắn dòng thương hiệu (logo + tên + website + tên tài liệu) vào đầu trang Word."""
    section = doc.sections[0]
    header = section.header
    p = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
    for r in list(p.runs):                       # dọn dòng cũ (nếu mẫu đã có chữ)
        r._r.getparent().remove(r._r)
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.tab_stops.add_tab_stop(Cm(_rong_trang_cm(section)), WD_TAB_ALIGNMENT.RIGHT)
    if logo and os.path.isfile(LOGO):
        p.add_run().add_picture(LOGO, height=Cm(CAO_LOGO_CM))
        p.add_run("  ")
    r = p.add_run(TEN)
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.color.rgb = MAU_MUC
    r2 = p.add_run("  ·  %s — %s" % (phu or PHU, WEB))
    r2.font.size = Pt(8)
    r2.font.color.rgb = MAU_PHU
    if tieu_de:
        p.add_run("\t")
        r3 = p.add_run(tieu_de[:120])
        r3.font.size = Pt(8.5)
        r3.font.color.rgb = MAU_PHU
    _ke_duoi(p)
    return p


def gan_chan_trang(doc, ghi_chu="", so_trang=True):
    """Gắn chân trang: nguồn tài liệu + số trang."""
    section = doc.sections[0]
    footer = section.footer
    p = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    for r in list(p.runs):
        r._r.getparent().remove(r._r)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("%s — %s%s" % (TEN, ghi_chu or ("Hệ thống soạn tài liệu cho giáo viên · " + WEB), ""))
    r.font.size = Pt(7.5)
    r.font.color.rgb = MAU_PHU
    if so_trang:
        r2 = p.add_run("  ·  Trang ")
        r2.font.size = Pt(7.5)
        r2.font.color.rgb = MAU_PHU
        _so_trang(p)
        r3 = p.add_run("/")
        r3.font.size = Pt(7.5)
        r3.font.color.rgb = MAU_PHU
        _so_trang_tong(p)
    return p


def _so_trang_tong(p):
    r = p.add_run()._r
    for loai, chu in (("begin", None), ("instr", "NUMPAGES"), ("end", None)):
        if loai == "instr":
            it = OxmlElement("w:instrText")
            it.set(qn("xml:space"), "preserve")
            it.text = chu
            r.append(it)
        else:
            f = OxmlElement("w:fldChar")
            f.set(qn("w:fldCharType"), loai)
            r.append(f)
    for run in p.runs:
        run.font.size = Pt(7.5)
        run.font.color.rgb = MAU_PHU


def gan(doc, tieu_de="", ghi_chu="", logo=True, so_trang=True):
    """Gắn CẢ đầu trang và chân trang. Không bao giờ làm hỏng việc xuất tệp."""
    try:
        gan_dau_trang(doc, tieu_de=tieu_de, logo=logo)
    except Exception:
        pass
    try:
        gan_chan_trang(doc, ghi_chu=ghi_chu, so_trang=so_trang)
    except Exception:
        pass
    return doc


def co_logo(doc):
    """Dùng cho bộ kiểm: tệp Word này đã có dòng thương hiệu chưa?"""
    try:
        h = doc.sections[0].header
        chu = "\n".join(p.text for p in h.paragraphs)
        return TEN in chu
    except Exception:
        return False

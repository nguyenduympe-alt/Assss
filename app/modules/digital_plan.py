"""Word plans: preserve the supplied layout and provide editable teaching ideas."""
import copy
import io
import re
import unicodedata
import zipfile
from pathlib import Path
from docx import Document
from docx.shared import Pt, RGBColor

from . import ai_giao_duc as AIGD

SOURCE = 'https://congbao.chinhphu.vn/van-ban/thong-tu-so-02-2025-tt-bgddt-44148.htm'
# Màu phân biệt nội dung hệ thống đề xuất: năng lực số đỏ FF0000, giáo dục AI xanh dương 0000FF
DO = RGBColor(0xFF, 0x00, 0x00)
XANH = RGBColor(0x00, 0x00, 0xFF)
MAU_COT = {'digital': DO, 'ai': XANH}


def _to_mau(cell, key, item):
    """Tô màu ô vừa ghi nếu là cột năng lực số / AI do hệ thống đề xuất (không tô nội dung gốc)."""
    mau = MAU_COT.get(key)
    if mau is None or not item.get('_themmoi', {}).get(key):
        return
    for p in cell.paragraphs:
        for run in p.runs:
            if (run.text or '').strip():
                run.font.color.rgb = mau
DOMAINS = ['Khai thác dữ liệu và thông tin', 'Giao tiếp và hợp tác trong môi trường số',
           'Sáng tạo nội dung số', 'An toàn', 'Giải quyết vấn đề', 'Ứng dụng trí tuệ nhân tạo']
TEMPLATE = Path(__file__).resolve().parents[1] / 'assets' / 'khgd-template.docx'


def plain(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.lower().replace('đ', 'd')) if not unicodedata.combining(c))


def read_word(data):
    if len(data) > 8 * 1024 * 1024:
        raise ValueError('File Word tối đa 8 MB.')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if sum(f.file_size for f in z.infolist()) > 40 * 1024 * 1024 or len(z.infolist()) > 3000:
                raise ValueError('File Word quá lớn sau giải nén.')
            if 'word/document.xml' not in z.namelist():
                raise ValueError('File không có cấu trúc Word hợp lệ.')
        doc = Document(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError):
        raise ValueError('Không đọc được file Word. Hãy lưu lại dưới dạng .docx.') from None
    return doc


def suggestions(title, grade='', subject=''):
    """Conservative rules, explicitly labelled as editable suggestions, not AI."""
    t = plain(title)
    result = {'digital': '', 'ai': '', 'stem': '', 'notes': ''}
    if any(k in t for k in ('an toan', 'bao ve', 'mat khau', 'thong tin ca nhan', 'phan cung', 'ban phim')):
        result['digital'] = 'An toàn: thực hành sử dụng thiết bị đúng cách; nhận biết thông tin cần bảo vệ; nêu một quy tắc an toàn phù hợp bài học.'
    elif any(k in t for k in ('tim kiem', 'thong tin', 'internet', 'du lieu', 'bang tinh')):
        result['digital'] = 'Khai thác dữ liệu và thông tin: tìm hoặc đọc học liệu số do giáo viên lựa chọn; so sánh nguồn, ghi lại thông tin cần dùng và nguồn tham khảo.'
    elif any(k in t for k in ('ve', 'trinh chieu', 'van ban', 'thiep', 'thiet ke', 'soan thao', 'hinh anh')):
        result['digital'] = 'Sáng tạo nội dung số: tạo một sản phẩm số minh họa nội dung bài học; ghi nguồn hình ảnh và trình bày sản phẩm cho nhóm.'
    elif any(k in t for k in ('lap trinh', 'scratch', 'robot', 'thuat toan')):
        result['digital'] = 'Giải quyết vấn đề: chia nhiệm vụ thành các bước, thử nghiệm chương trình hoặc mô hình, phát hiện lỗi và điều chỉnh dựa trên kết quả.'
    elif any(k in t for k in ('hop tac', 'chia se', 'thu dien tu', 'giao tiep')):
        result['digital'] = 'Giao tiếp và hợp tác trong môi trường số: chia sẻ sản phẩm trong nhóm dưới sự hướng dẫn của giáo viên, phản hồi lịch sự và không công khai dữ liệu cá nhân.'
    if any(k in t for k in ('tri tue nhan tao', 'ai ', 'chatbot')):
        result['ai'] = 'Giáo viên minh họa một phản hồi AI, học sinh đối chiếu với học liệu đã xác minh và chỉ ra điểm cần kiểm tra; không nhập dữ liệu cá nhân.'
        result['digital'] = result['digital'] or 'Ứng dụng trí tuệ nhân tạo: nhận biết sản phẩm AI và kiểm tra độ phù hợp trước khi sử dụng.'
    if any(k in t for k in ('robot', 'lap trinh', 'scratch', 'mach dien', 'nang luong', 'tai che', 'trong cay', 'do nhiet', 'do do dai')):
        result['stem'] = 'Gợi ý STEM: tổ chức nhiệm vụ thiết kế hoặc thử nghiệm gắn với bài học; kết hợp kiến thức khoa học, đo lường và công nghệ; học sinh tạo sản phẩm, thử, ghi kết quả và cải tiến. Chỉ áp dụng khi đủ thời gian và học liệu.'
    elif any(k in t for k in ('ve tranh', 'thiep', 'thiet ke', 'trang tri')):
        result['stem'] = 'Gợi ý STEAM: thiết kế sản phẩm trực quan gắn nội dung bài học; kết hợp công nghệ, bố cục/hình học và thẩm mỹ; trình bày lựa chọn thiết kế, nhận phản hồi và cải tiến.'
    if any(result.values()):
        result['notes'] = f'Đề xuất tham khảo cho lớp {grade}, môn {subject}. GV xác nhận mục tiêu, học liệu và thời lượng; chưa tự gán mã chỉ báo.'
    return result


def extract_rows(doc):
    result = []
    for table in doc.tables:
        rows = table.rows
        header_index, columns = None, {}
        for ri, row in enumerate(rows[:5]):
            headers = [plain(c.text) for c in row.cells]
            for ci, value in enumerate(headers):
                if 'ten bai' in value or value.strip() in ('bai hoc', 'noi dung bai hoc'):
                    header_index = ri
                    columns['title'] = ci
            if header_index is not None:
                # Include the preceding merged header (e.g. Tuần) when needed.
                for ci, value in enumerate(headers):
                    prior = plain(rows[ri - 1].cells[ci].text) if ri > 0 and ci < len(rows[ri-1].cells) else ''
                    value = value + ' ' + prior
                    for key, terms in {'week': ['tuan'], 'topic': ['chu de', 'mach noi dung'],
                        'periods': ['thoi luong', 'so tiet', 'tiet hoc'], 'digital': ['nang luc so', 'nang luc so', 'nang luc so'],
                        'ai': ['tri tue nhan tao'], 'stem': ['stem', 'steam'], 'notes': ['ghi chu']}.items():
                        if any(x in value for x in terms):
                            columns.setdefault(key, ci)
                break
        if header_index is None:
            continue
        seen_cells = {}
        for row in rows[header_index+1:]:
            cells = row.cells
            item = {k: cells[i].text.strip() if i < len(cells) else '' for k,i in columns.items()}
            if not any(item.get(k) for k in ('title','week','periods','notes')) or 'ten bai' in plain(item.get('title','')):
                continue
            entry = {k: item.get(k,'') for k in ('week','topic','title','periods','digital','ai','stem','notes')}
            entry['_merge'] = {}
            for key, ci in columns.items():
                if ci < len(cells):
                    element = cells[ci]._tc
                    lookup = (key, element)
                    if lookup in seen_cells:
                        entry['_merge'][key] = seen_cells[lookup]
                    else:
                        seen_cells[lookup] = len(result)
            result.append(entry)
    if not result:
        for p in doc.paragraphs:
            if re.match(r'^(bài|bai|chủ đề)\s*\d+', p.text.strip(), re.I):
                result.append(dict(week='',topic='',title=p.text.strip(),periods='',digital='',ai='',stem='',notes=''))
    if not result:
        raise ValueError('Chưa nhận diện được bảng phân phối chương trình. File cần cột “Tên bài học” hoặc các dòng bắt đầu bằng “Bài 1…”.')
    if len(result) > 180:
        raise ValueError('Mỗi lần hỗ trợ tối đa 180 dòng bài học. Hãy chia file theo học kỳ.')
    return result


def preview(data, mode, grade, subject, chon=None):
    """chon: tập nội dung cần đề xuất — 'digital' (năng lực số), 'ai' (giáo dục AI), 'stem'."""
    chon = set(chon or ('digital', 'ai', 'stem'))
    doc = read_word(data)
    if mode == 'ppct':
        rows = extract_rows(doc)
    else:
        text = '\n'.join(p.text for p in doc.paragraphs)
        for table in doc.tables:
            text += '\n' + '\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows)
        if not text.strip():
            raise ValueError('Không tìm thấy văn bản trong file; file ảnh quét chưa được hỗ trợ.')
        title = next((p.text.strip() for p in doc.paragraphs if re.search(r'(bài|chủ đề|tên bài)', p.text, re.I)), '')
        title = title or next((p.text.strip() for p in doc.paragraphs if p.text.strip()), 'Giáo án')
        rows = [dict(week='', topic='', title=title[:500], periods='', digital='', ai='', stem='', notes='')]
    from .framework_match import match
    if 'digital' not in chon:
        text = ''                      # không đề xuất năng lực số: bỏ luôn phần đối chiếu chỉ báo
    for row in rows:
        row['original'] = {k: row[k] for k in ('digital','ai','stem','notes')}
        proposal = suggestions(row['title'], grade, subject)
        for key, value in proposal.items():
            if key == 'notes':
                if 'digital' in chon and not row[key]:
                    row[key] = value
            elif key in chon and not row[key]:
                row[key] = value
        if 'digital' not in chon:
            row['digital'] = row['original']['digital']
        if 'stem' not in chon:
            row['stem'] = row['original']['stem']
        # ---- mã giáo dục AI theo Quyết định 2422/QĐ-BGDĐT (không tự đặt mã) ----
        row['ma_ai'] = []
        row['canh_bao_ai'] = []
        if 'ai' in chon and not row['original']['ai']:
            ds_ma, canh_bao_ai = AIGD.goi_y_ma(grade, ten_bai=row['title'],
                                               van_ban=row.get('topic', ''), mon=subject)
            row['ai'] = AIGD.dong_ma(ds_ma)
            row['ma_ai'] = [{'ma': x['ma'], 'yccd': x['yccd'], 'noi_dung': x.get('noi_dung', ''),
                             'chu_de_ten': x['chu_de_ten'], 'mach_ten': x['mach_ten'],
                             'mo_rong': x['mo_rong'], 'khop': x.get('khop', []),
                             'nguon': AIGD.NGUON_MA} for x in ds_ma]
            row['canh_bao_ai'] = canh_bao_ai
            if ds_ma:
                row['notes'] = ((row['notes'] + '\n') if row['notes'] else '') + \
                    'Giáo dục AI (Quyết định 2422/QĐ-BGDĐT + Công văn 5588/BGDĐT-GDPT): ' + \
                    '; '.join(x['yccd'][:110] for x in ds_ma) + \
                    '\nGiáo viên rà soát mã và nội dung AI trước khi dùng.'
        elif 'ai' not in chon:
            row['ai'] = row['original']['ai']
        references = match(text if mode == 'lesson' else row['title'], grade)
        row['references'] = references
        if 'digital' in chon and references and not row['original']['digital']:
            row['digital'] = '\n'.join(x['code'] + ': ' + x['description'] for x in references)
            row['notes'] = '\n'.join(dict.fromkeys(x['activity'] for x in references)) + '\nĐề xuất tự động theo khung; giáo viên rà soát trước khi sử dụng.'
        row['chon'] = sorted(chon)
    return rows


def export(data, mode, rows, grade, subject):
    if mode == 'ppct':
        doc = Document(TEMPLATE)
        doc.paragraphs[0].text = f'Môn học, hoạt động giáo dục: {subject} — Lớp {grade}'
        doc.paragraphs[1].text = 'Thời lượng và tuần học: theo các dòng phân phối chương trình bên dưới; giáo viên rà soát trước khi sử dụng.'
        table = doc.tables[0]
        while len(table.rows) > 2:
            table._tbl.remove(table.rows[-1]._tr)
        for item in rows:
            cells = table.add_row().cells
            for cell, key in zip(cells, ('week','topic','title','periods','digital','ai','stem','notes')):
                cell.text = item.get(key, '')
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.name = 'Times New Roman'
                        run.font.size = Pt(11)
                _to_mau(cell, key, item)      # đỏ: năng lực số, xanh dương: giáo dục AI
        keys = ('week','topic','title','periods','digital','ai','stem','notes')
        # Recreate source vertical merges only if the teacher kept matching values.
        groups = {}
        for ri, item in enumerate(rows):
            for key, first in item.get('_merge', {}).items():
                if key in keys and 0 <= first < ri:
                    groups.setdefault((key, first), []).append(ri)
        for (key, first), rest in groups.items():
            last = max(rest)
            if rest == list(range(first+1,last+1)) and all(rows[x].get(key,'') == rows[first].get(key,'') for x in rest):
                ci = keys.index(key)
                cell = table.cell(first+2, ci).merge(table.cell(last+2, ci))
                cell.text = rows[first].get(key,'')
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.name = 'Times New Roman'
                        run.font.size = Pt(11)
                _to_mau(cell, key, rows[first])
    else:
        doc = read_word(data)
        # Append a reviewed integration section so original lesson tables/runs remain intact.
        doc.add_heading('TÍCH HỢP NĂNG LỰC SỐ, AI VÀ STEM/STEAM', level=1)
        doc.add_paragraph(f'Môn {subject} — Lớp {grade}')
        for item in rows:
            for label, key in (('Năng lực số','digital'),('Trí tuệ nhân tạo (AI)','ai'),('STEM/STEAM','stem'),('Tổ chức và đánh giá','notes')):
                if item.get(key):
                    doc.add_heading(label, level=2)
                    p = doc.add_paragraph()
                    run = p.add_run(item[key])
                    mau = MAU_COT.get(key)
                    if mau is not None and item.get('_themmoi', {}).get(key):
                        run.font.color.rgb = mau
    doc.add_paragraph('Tham chiếu Thông tư 02/2025/TT-BGDĐT và hướng dẫn theo khối lớp tại Công văn 3456/BGDĐT-GDPT (mã năng lực số). Mã giáo dục AI lấy theo Quyết định 2422/QĐ-BGDĐT ngày 18/8/2026 (Khung nội dung giáo dục AI cho học sinh phổ thông; quy ước mã [Lớp].[Mã chủ đề].[Số thứ tự], nội dung mở rộng thêm tiền tố “MR”) và hướng dẫn triển khai tại Công văn 5588/BGDĐT-GDPT ngày 19/8/2026. Các mã và hoạt động tích hợp cần được giáo viên rà soát theo thực tế lớp học.')
    output = io.BytesIO()
    doc.save(output)
    output.seek(0)
    return output

"""Đọc / sinh đề trắc nghiệm nội bộ — không gửi file giáo viên ra ngoài.

· File câu hỏi Word: đáp án là chỗ in đậm hoặc gạch chân (hoặc dòng “Đáp án: A”).
· Tài liệu bài học: khung suy luận 4 bước kiểu LLM (rút ý → đặt câu → nhiễu → kiểm),
  chạy local (máy chủ không đủ RAM cho LLM lớn). Giáo viên chọn số câu và số đáp án.
· Sắp tên học sinh theo TÊN → TÊN LÓT → HỌ.
"""
import hashlib
import io
import json
import random
import re
import unicodedata
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import ai_nhanxet as NX

# A–F: cho phép 2–6 đáp án mỗi câu (nghiên cứu MCQ: số nhiễu n thay đổi được).
CHU = ('A', 'B', 'C', 'D', 'E', 'F')
RE_CAU = re.compile(
    r'^\s*(?:câu\s*)?(\d+)\s*[\.\)\:\-–]\s*(.+)$', re.I | re.S)
RE_PA = re.compile(
    r'^\s*[\(\[]?([A-Fa-f])[\)\]\.\:\-–]\s*(.+)$', re.S)
RE_DAP = re.compile(
    r'(?:đáp\s*án|dap\s*an|câu\s*trả\s*lời)\s*[:\-–]?\s*[\(\[]?([A-Fa-f])\b', re.I)
RE_LA = re.compile(
    r'([A-ZÀ-ỴĐ][^.]{2,70}?)\s+(?:là|chính là|được gọi là|có nghĩa là)\s+([^.]{8,180})\.',
    re.I)
RE_CAU_VAN = re.compile(r'[^.!?…\n]+[.!?…]?')


def _khong_dau(s):
    t = unicodedata.normalize('NFD', (s or '').replace('Đ', 'D').replace('đ', 'd'))
    return ''.join(c for c in t if not unicodedata.combining(c)).lower()


def tach_ten(ho_ten):
    """Họ / tên lót / tên. 'Nguyễn Văn An' → (Nguyễn, Văn, An)."""
    tu = [x for x in re.split(r'\s+', (ho_ten or '').strip()) if x]
    if not tu:
        return '', '', ''
    if len(tu) == 1:
        return '', '', tu[0]
    return tu[0], ' '.join(tu[1:-1]), tu[-1]


def khoa_sap_xep(ho_ten):
    ho, lot, ten = tach_ten(ho_ten)
    return (_khong_dau(ten), _khong_dau(lot), _khong_dau(ho), (ho_ten or '').lower())


def sap_xep_hs(ds, key='ho_ten'):
    return sorted(ds, key=lambda r: khoa_sap_xep(r.get(key) if isinstance(r, dict) else r[key]))


def ten_chuan(ho_ten):
    return re.sub(r'\s+', ' ', (ho_ten or '').strip()).lower()


def _run_danh_dau(run):
    if not run or not (run.text or '').strip():
        return False
    if run.bold:
        return True
    u = run.underline
    if u in (True,):
        return True
    if u in (None, False):
        return False
    ten = str(getattr(u, 'name', u) or '').upper()
    return ten not in ('NONE', 'FALSE', '0')


def _para_danh_dau(para):
    """True nếu đoạn có run in đậm / gạch chân (không tính cả đoạn trống)."""
    return any(_run_danh_dau(r) for r in para.runs)


def _dong_tu_para(para):
    return {
        'text': (para.text or '').strip(),
        'danh_dau': _para_danh_dau(para),
        'chu_danh_dau': ''.join(r.text for r in para.runs if _run_danh_dau(r)).strip(),
    }


def _duyet_para(doc):
    def walk(c):
        for p in c.paragraphs:
            yield p
        for t in getattr(c, 'tables', []):
            for row in t.rows:
                for cell in row.cells:
                    yield from walk(cell)
    yield from walk(doc)


def _gop_lua_chon(q, so_dap_an=None):
    lc = dict(q.get('lua_chon') or {})
    anh_pa = {}
    for k, v in (q.get('anh_pa') or {}).items():
        chu = str(k).upper()[:1]
        token = str(v or '').strip()[:80]
        if chu in CHU and token:
            anh_pa[chu] = token
            lc.setdefault(chu, '')
    thu_tu = [k for k in CHU if k in lc]
    if so_dap_an:
        so_dap_an = max(2, min(6, int(so_dap_an)))
        thu_tu = thu_tu[:so_dap_an]
    if len(thu_tu) < 2:
        return False
    q['lua_chon'] = {k: lc.get(k) or '' for k in thu_tu}
    q['anh_pa'] = {k: anh_pa[k] for k in thu_tu if k in anh_pa}
    da = (q.get('dap_an') or '').upper()[:1]
    if da not in q['lua_chon']:
        return False
    q['dap_an'] = da
    q['cau'] = re.sub(r'\s+', ' ', (q.get('cau') or '').strip())
    return bool(q['cau'])


def doc_docx_cau_hoi(blob):
    """Đọc đề trắc nghiệm từ Word: đáp án = in đậm hoặc gạch chân."""
    from docx import Document
    doc = Document(io.BytesIO(blob))
    dong = [_dong_tu_para(p) for p in _duyet_para(doc) if (p.text or '').strip()]
    return _phan_tich_dong(dong)


def _phan_tich_dong(dong):
    ds, cur = [], None
    dap_cuoi = {}  # số câu → chữ đáp án (khi đáp án ghi riêng ở cuối)

    def flush():
        nonlocal cur
        if cur and _gop_lua_chon(cur):
            ds.append(cur)
        cur = None

    for d in dong:
        t = d['text']
        m_dap = RE_DAP.search(t)
        m_cau = RE_CAU.match(t)
        m_pa = RE_PA.match(t)

        if m_cau and (m_cau.group(1) and len(m_cau.group(2) or '') >= 2):
            flush()
            so = int(m_cau.group(1))
            cur = {'id': so, 'cau': m_cau.group(2).strip(), 'lua_chon': {}, 'dap_an': ''}
            if m_dap:
                cur['dap_an'] = m_dap.group(1).upper()
            continue
        if m_pa:
            if cur is None:
                continue
            chu = m_pa.group(1).upper()
            nd = m_pa.group(2).strip()
            cur['lua_chon'][chu] = nd
            if d['danh_dau'] or (d['chu_danh_dau'] and (
                    chu in d['chu_danh_dau'].upper() or nd[:8] in (d['chu_danh_dau'] or ''))):
                cur['dap_an'] = chu
            if m_dap:
                cur['dap_an'] = m_dap.group(1).upper()
            continue
        if m_dap:
            chu = m_dap.group(1).upper()
            so_cau = None
            mso = re.search(r'(?:câu\s*)(\d+)', t, re.I)
            if mso:
                so_cau = int(mso.group(1))
            if cur and not so_cau:
                cur['dap_an'] = chu
            elif so_cau:
                dap_cuoi[so_cau] = chu
            continue
        if cur and not cur['lua_chon'] and t:
            cur['cau'] = (cur['cau'] + ' ' + t).strip()
    flush()
    for q in ds:
        if not q.get('dap_an') and q['id'] in dap_cuoi:
            q['dap_an'] = dap_cuoi[q['id']]
    ra = []
    for i, q in enumerate(ds, 1):
        if _gop_lua_chon(q):
            q['id'] = i
            ra.append(q)
    return ra


def doc_pdf_chu(blob):
    from .doc_ai_check import doc_pdf
    phan, loi = doc_pdf(blob)
    return phan, loi


def _tron(lc, dap_an, seed, so_dap_an=4):
    """Trộn phương án, giữ đúng số đáp án giáo viên chọn."""
    so_dap_an = max(2, min(6, int(so_dap_an or 4)))
    items = [(k, lc[k]) for k in CHU if k in lc]
    if len(items) < 2:
        return lc, dap_an
    dung = lc.get(dap_an, items[0][1])
    r = random.Random(seed)
    noi = [v for _, v in items if v != dung]
    r.shuffle(noi)
    chon = [dung] + noi[:so_dap_an - 1]
    r.shuffle(chon)
    moi = {CHU[i]: chon[i] for i in range(len(chon))}
    da = next(k for k, v in moi.items() if v == dung)
    return moi, da


def _tu_noi_dung(s):
    return [w for w in re.findall(r'[A-Za-zÀ-ỹĐđ]{3,}', (s or '').lower())
            if w not in ('các', 'những', 'một', 'được', 'trong', 'với', 'của',
                         'là', 'cho', 'khi', 'này', 'đó', 'và', 'hay')]


def _diem_nhieu(dung, sai, cau_hoi):
    """Chấm đáp án nhiễu theo tiêu chí nghiên cứu: gần nghĩa, gần độ dài, bám bài, dễ nhầm.

    ACL 2025 BiFlow / student-choice: nhiễu phải plausibly sai, không quá lộ, không trùng đáp án.
    """
    if not sai or _khong_dau(sai) == _khong_dau(dung):
        return -99
    kd, ks = _khong_dau(dung), _khong_dau(sai)
    if ks in kd or kd in ks:
        return -40
    diem = 0
    ld, ls = max(len(dung), 1), len(sai)
    ti = ls / float(ld)
    if 0.55 <= ti <= 1.8:
        diem += 3
    elif 0.4 <= ti <= 2.2:
        diem += 1
    else:
        diem -= 2
    chung = set(_tu_noi_dung(dung)) & set(_tu_noi_dung(sai))
    diem += min(3, len(chung))
    chu_cau = set(_tu_noi_dung(cau_hoi))
    diem += min(2, len(chu_cau & set(_tu_noi_dung(sai))))
    reu = ('không phải ý trên', 'tất cả các ý trên', 'chưa đủ căn cứ', 'phương án')
    if any(x in ks for x in reu):
        diem -= 8
    return diem


def _loc_nhieu(dung, ung_vien, cau_hoi, can, seed):
    """Over-generate rồi xếp hạng (overgenerate-and-rank) — lấy nhiễu khó nhất."""
    seen, uniq = set(), []
    kd = _khong_dau(dung)[:50]
    for s in ung_vien:
        s = re.sub(r'\s+', ' ', (s or '').strip().rstrip('.'))
        if not s or len(s) < 4:
            continue
        k = _khong_dau(s)[:50]
        if k == kd or k in seen:
            continue
        seen.add(k)
        uniq.append(s)
    uniq.sort(key=lambda s: -_diem_nhieu(dung, s, cau_hoi))
    uniq = [s for s in uniq if _diem_nhieu(dung, s, cau_hoi) > -20]
    r = random.Random(seed)
    # PathFinder: giữ top + một ít đa dạng
    top, rest = uniq[:can + 3], uniq[can + 3:]
    r.shuffle(rest)
    gop = top + rest[:2]
    ra = []
    seen2 = set()
    for s in gop:
        k = _khong_dau(s)[:40]
        if k in seen2:
            continue
        seen2.add(k)
        ra.append(s)
        if len(ra) >= can:
            break
    return ra


def _nhieu_lua_chon(cau, dung, sai, seed, so_dap_an=4):
    so_dap_an = max(2, min(6, int(so_dap_an or 4)))
    can = so_dap_an - 1
    uniq = _loc_nhieu(dung, sai, cau, can, seed)
    i = 0
    pad = ['Ý trái với nội dung bài', 'Chi tiết không có trong bài', 'Kết luận ngược với bài học']
    while len(uniq) < can and i < len(pad):
        if _khong_dau(pad[i]) != _khong_dau(dung):
            uniq.append(pad[i])
        i += 1
    lc = {'A': dung}
    for j, s in enumerate(uniq[:can]):
        lc[CHU[j + 1]] = s
    return _tron(lc, 'A', seed, so_dap_an)


RE_TAI = re.compile(
    r'([A-ZÀ-ỴĐ][^.]{2,55}?)\s+(?:xảy ra|diễn ra|diễn ra chủ yếu)\s+'
    r'(?:ở|tại|trong)\s+([^.]{3,80})\.', re.I)
RE_GOM = re.compile(
    r'([A-ZÀ-ỴĐ][^.]{2,55}?)\s+gồm\s+([^.]{6,120})\.', re.I)
RE_DE = re.compile(
    r'([A-ZÀ-ỴĐ][^.]{2,55}?)\s+(?:để|nhằm|giúp)\s+([^.]{6,100})\.', re.I)
RE_NG = re.compile(
    r'(?:nguyên liệu|nguyên nhân|điều kiện)\s+(?:của|cho)?\s*([^.]{3,40}?)\s+là\s+([^.]{6,100})\.',
    re.I)


def _giao_vien_rut_y(text):
    """Bước 1 — teacher reasoning: rút đơn vị kiến thức bám văn bản."""
    y = []
    for m in RE_LA.finditer(text):
        chu, nghia = m.group(1).strip(' :-–'), m.group(2).strip(' :-–')
        if 3 <= len(chu) <= 70 and 8 <= len(nghia) <= 180:
            y.append({'kieu': 'dinh_nghia', 'chu': chu, 'dung': nghia,
                      'cau': '%s là gì?' % chu.rstrip('?')})
    for m in RE_TAI.finditer(text):
        chu, noi = m.group(1).strip(), m.group(2).strip()
        y.append({'kieu': 'noi', 'chu': chu, 'dung': noi,
                  'cau': '%s xảy ra ở đâu / khi nào?' % chu.rstrip('?')})
    for m in RE_GOM.finditer(text):
        chu, gom = m.group(1).strip(), m.group(2).strip()
        y.append({'kieu': 'gom', 'chu': chu, 'dung': gom,
                  'cau': '%s gồm những gì?' % chu.rstrip('?')})
    for m in RE_DE.finditer(text):
        chu, de = m.group(1).strip(), m.group(2).strip()
        y.append({'kieu': 'muc_dich', 'chu': chu, 'dung': de,
                  'cau': 'Theo bài, %s để làm gì?' % chu.rstrip('?')})
    for m in RE_NG.finditer(text):
        chu, ng = m.group(1).strip(), m.group(2).strip()
        y.append({'kieu': 'nguyen', 'chu': chu, 'dung': ng,
                  'cau': 'Nguyên liệu / nguyên nhân của %s là gì?' % chu})
    return y


def _hoc_sinh_kiem(q):
    """Bước 4 — student reasoning: loại câu quá lộ, trùng, thiếu nhiễu."""
    lc = q.get('lua_chon') or {}
    da = q.get('dap_an')
    if da not in lc or len(lc) < 2:
        return False
    dung = lc[da]
    for k, v in lc.items():
        if k == da:
            continue
        if _khong_dau(v) == _khong_dau(dung):
            return False
        if _diem_nhieu(dung, v, q.get('cau') or '') < -25:
            return False
    return True


def sinh_tu_tai_lieu(text, so=10, so_dap_an=4):
    """Sinh MCQ theo khung suy luận kiểu LLM, chạy local, không gọi mạng.

    4 bước (ACL 2025 BiFlow teacher↔student + overgenerate-and-rank):
      1) Giáo viên ảo rút ý từ bài
      2) Đặt nhiều dạng câu (định nghĩa / vị trí / gồm / mục đích)
      3) Sinh đáp án nhiễu gần nghĩa, cùng bài — xếp hạng độ dễ nhầm
      4) Học sinh ảo loại câu quá lộ hoặc trùng đáp án
    Máy chủ hiện không đủ RAM để chạy LLM lớn; đây là suy luận có cấu trúc, bám văn bản.
    """
    so = max(1, min(40, int(so or 10)))
    so_dap_an = max(2, min(6, int(so_dap_an or 4)))
    text = re.sub(r'[ \t]+', ' ', (text or '').replace('\r', '\n')).strip()
    if len(text) < 80:
        return []
    cau = [c.strip() for c in RE_CAU_VAN.findall(text) if len(c.strip()) >= 20]
    y = _giao_vien_rut_y(text)
    ra = []
    dung_theo_kieu = {}
    for u in y:
        dung_theo_kieu.setdefault(u['kieu'], []).append(u['dung'])

    def them(cau_hoi, dung, sai, seed, kieu=''):
        if len(ra) >= so:
            return
        if any(_khong_dau(cau_hoi)[:50] == _khong_dau(x['cau'])[:50] for x in ra):
            return
        lc, da = _nhieu_lua_chon(cau_hoi, dung, sai, seed, so_dap_an)
        q = {'id': len(ra) + 1, 'cau': cau_hoi, 'lua_chon': lc, 'dap_an': da,
             'kieu': kieu}
        if _hoc_sinh_kiem(q) and _gop_lua_chon(q, so_dap_an):
            ra.append(q)

    for u in y:
        sai = list(dung_theo_kieu.get(u['kieu']) or [])
        sai += [x['dung'] for x in y if x is not u]
        them(u['cau'], u['dung'], sai, hash(u['cau'] + u['dung']) & 0xFFFFFFFF, u['kieu'])

    for i, c in enumerate(cau):
        if len(ra) >= so:
            break
        c0 = c.strip()
        if len(c0) < 25 or c0.endswith('?'):
            continue
        sai = [x.strip().rstrip('.') for j, x in enumerate(cau) if j != i]
        them('Ý nào sau đây đúng theo bài học?', c0.rstrip('.'), sai,
             hash(c0) & 0xFFFFFFFF, 'y_dung')

    for i, q in enumerate(ra, 1):
        q['id'] = i
        q.pop('kieu', None)
    return ra[:so]


def _tach_json_llm(s):
    """Tách object JSON đầu tiên trong văn bản AI trả về (bỏ lời dẫn)."""
    s = (s or '').replace('```json', '```')
    if '```' in s:
        for phan in s.split('```'):
            phan = phan.strip()
            if phan.startswith('{'):
                s = phan
                break
    dau = s.find('{')
    cuoi = s.rfind('}')
    if dau < 0 or cuoi <= dau:
        return None
    try:
        obj = json.loads(s[dau:cuoi + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        return None


def sinh_cau_hoi_llm(text, so=10, so_dap_an=4):
    """Sinh câu hỏi trắc nghiệm bằng AI cục bộ (Qwen2.5, chạy trên máy chủ).

    Sinh 1 câu/lần gọi (JSON ngắn — model nhỏ bám nội dung tốt hơn), chặn lặp,
    tổng thời gian có hạn. Trả LIST câu hỏi (rỗng nếu AI không dùng được →
    caller tự bù bằng sinh_tu_tai_lieu, nguồn hiển thị 'tai_lieu').
    """
    try:
        from . import llm_cuc_bo as LB
    except Exception:  # noqa: BLE001
        return []
    text = (text or '').strip()
    if len(text) < 80:
        return []
    text = text[:6000]
    so = max(1, min(40, int(so or 10)))
    so_dap_an = max(2, min(6, int(so_dap_an or 4)))
    p_he = ('Bạn là giáo viên tiểu học tạo câu hỏi trắc nghiệm tiếng Việt bám bài học. '
            'CHỈ trả về MỘT object JSON, không giải thích, dạng: '
            '{"cau": "câu hỏi", "lua_chon": {"A": "...", "B": "...", "C": "...", "D": "..."}, '
            '"dap_an": "A"}. Đáp án đúng phải có thật trong bài học.')
    ds, da_co = [], set()
    vong = 0
    from time import time as _now
    bat_dau = _now()
    while len(ds) < so and vong < so * 3 and _now() - bat_dau < 95:
        vong += 1
        p_user = ('Bài học:\n"""\n%s\n"""\n\nTạo 1 câu hỏi trắc nghiệm %s đáp án bám sát bài trên. '
                  'Các câu đã có (tránh lặp): %s'
                  % (text, so_dap_an, ' | '.join(sorted(da_co)[:8]) or '(chưa có)'))
        kq = LB.sinh(p_he, p_user, toi_da_token=280, nhiet_do=0.7, han=25)
        if not kq.get('ok'):
            if kq.get('loai_loi') in ('het_ram', 'ban', 'loi_dich_vu', 'het_han'):
                break
            continue
        obj = _tach_json_llm(kq.get('text') or '')
        if not obj or not str(obj.get('cau') or '').strip():
            continue
        cau = re.sub(r'\s+', ' ', str(obj['cau']).strip())
        if len(cau) < 12 or cau.lower().startswith(('xin chào', 'i ')):
            continue
        khoa = _khong_dau(cau)[:50]
        if khoa in da_co:
            continue
        # lua_chon: nhận cả dict {A:..} lẫn list ["A. ..", ...]
        goc = obj.get('lua_chon') or {}
        lc = {}
        if isinstance(goc, dict):
            for k, v in goc.items():
                chu = str(k).strip().upper()[:1]
                if chu in CHU and str(v or '').strip():
                    lc[chu] = re.sub(r'\s+', ' ', str(v).strip()).lstrip('A-Fa-f.):–- ')
        elif isinstance(goc, list):
            for item in goc:
                m = re.match(r'^\s*([A-Fa-f])[\.\)\:\-–]\s*(.+)$', str(item or '').strip())
                if m:
                    lc[m.group(1).upper()] = re.sub(r'\s+', ' ', m.group(2).strip())
        da = str(obj.get('dap_an') or '').strip().upper()[:1]
        if not da or da not in CHU:
            da = 'A' if 'A' in lc else (sorted(lc)[0] if lc else '')
        if len(lc) < 2 or not da:
            continue
        q = {'cau': cau, 'lua_chon': lc, 'dap_an': da, 'loai': 'tn'}
        if _gop_lua_chon(q, so_dap_an):
            da_co.add(khoa)
            q['id'] = len(ds) + 1
            ds.append(q)
    return ds


def chuan_so(so_cau, so_dap_an):
    try:
        so_cau = int(so_cau or 10)
    except (TypeError, ValueError):
        so_cau = 10
    try:
        so_dap_an = int(so_dap_an or 4)
    except (TypeError, ValueError):
        so_dap_an = 4
    return max(1, min(40, so_cau)), max(2, min(6, so_dap_an))


def doc_file(blob, ten_tep, so_cau=10, so_dap_an=4):
    """Trả (ds_cau, nguon, loi). nguon = 'file_cau_hoi' | 'tai_lieu'."""
    so_cau, so_dap_an = chuan_so(so_cau, so_dap_an)
    ten = (ten_tep or '').lower()
    if ten.endswith('.docx'):
        ds = doc_docx_cau_hoi(blob)
        if len(ds) >= 2 and sum(1 for q in ds if q.get('dap_an')) >= max(2, len(ds) // 2):
            return ds[:so_cau] if so_cau else ds, 'file_cau_hoi', ''
        from docx import Document
        doc = Document(io.BytesIO(blob))
        text = '\n'.join(p.text for p in doc.paragraphs)
        for t in doc.tables:
            for row in t.rows:
                text += '\n' + ' '.join(c.text for c in row.cells)
        gen, nguon_gen = sinh_cau_hoi_llm(text, so=so_cau, so_dap_an=so_dap_an), 'ai_cuc_bo'
        if gen and len(gen) < so_cau:
            for q in sinh_tu_tai_lieu(text, so=so_cau, so_dap_an=so_dap_an):
                if len(gen) >= so_cau:
                    break
                if all(_khong_dau(q['cau'])[:50] != _khong_dau(x['cau'])[:50] for x in gen):
                    gen.append(q)
        if not gen:
            gen = sinh_tu_tai_lieu(text, so=so_cau, so_dap_an=so_dap_an)
            nguon_gen = 'tai_lieu'
        if gen:
            for i, q in enumerate(gen, 1):
                q['id'] = i
            return gen[:so_cau] if so_cau else gen, nguon_gen, ''
        if ds:
            thieu = [q['id'] for q in ds if not q.get('dap_an')]
            if thieu:
                return [], '', ('File câu hỏi nhưng chưa thấy đáp án in đậm/gạch chân '
                                '(câu %s). Hãy in đậm hoặc gạch chân đáp án đúng.'
                                % ', '.join(str(x) for x in thieu[:8]))
        return [], '', 'Không đọc được câu hỏi trắc nghiệm và cũng chưa đủ nội dung để sinh đề.'
    if ten.endswith('.pdf'):
        phan, loi = doc_pdf_chu(blob)
        if loi:
            return [], '', loi
        text = '\n'.join(phan)
        dong = [{'text': x.strip(), 'danh_dau': False, 'chu_danh_dau': ''}
                for x in text.split('\n') if x.strip()]
        ds = _phan_tich_dong(dong)
        if len(ds) >= 2 and all(q.get('dap_an') for q in ds):
            return ds[:so_cau], 'file_cau_hoi', ''
        gen, nguon_gen = sinh_cau_hoi_llm(text, so=so_cau, so_dap_an=so_dap_an), 'ai_cuc_bo'
        if gen and len(gen) < so_cau:
            for q in sinh_tu_tai_lieu(text, so=so_cau, so_dap_an=so_dap_an):
                if len(gen) >= so_cau:
                    break
                if all(_khong_dau(q['cau'])[:50] != _khong_dau(x['cau'])[:50] for x in gen):
                    gen.append(q)
        if not gen:
            gen = sinh_tu_tai_lieu(text, so=so_cau, so_dap_an=so_dap_an)
            nguon_gen = 'tai_lieu'
        if gen:
            for i, q in enumerate(gen, 1):
                q['id'] = i
            return gen[:so_cau] if so_cau else gen, nguon_gen, ''
        if ds:
            return [], '', ('PDF câu hỏi cần dòng “Đáp án: A” (PDF không giữ in đậm/gạch chân). '
                            'Nên dùng file Word.')
        return [], '', 'Không đọc được đề từ PDF này.'
    return [], '', 'Chỉ nhận file Word .docx hoặc PDF.'


LOAI_CAU = ('tn', 'ds', 'dk', 'tl', 'gc')
NHAN_LOAI = {
    'tn': 'Trắc nghiệm',
    'ds': 'Đúng / Sai',
    'dk': 'Điền khuyết',
    'tl': 'Tự luận',
    'gc': 'Ghép cột',
}
CHU_GC = 'abcdefgh'
ANH_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
ANH_MAX = 2 * 1024 * 1024


def loai_cau(q):
    l = (q.get('loai') if isinstance(q, dict) else '') or 'tn'
    return l if l in LOAI_CAU else 'tn'


def kiem_anh(blob, ten):
    """Kiểm tra file ảnh. Trả (đuôi, lỗi)."""
    ext = ('.' + (ten or '').rsplit('.', 1)[-1].lower()) if '.' in (ten or '') else ''
    if ext not in ANH_EXT:
        return '', 'Chỉ nhận ảnh jpg, png, webp hoặc gif.'
    if not blob:
        return '', 'Ảnh trống.'
    if len(blob) > ANH_MAX:
        return '', 'Mỗi ảnh tối đa 2 MB.'
    dau = blob[:16]
    ok = (dau.startswith(b'\xff\xd8\xff') or dau.startswith(b'\x89PNG\r\n\x1a\n')
          or dau.startswith(b'GIF87a') or dau.startswith(b'GIF89a')
          or (dau.startswith(b'RIFF') and b'WEBP' in blob[:16]))
    if not ok:
        return '', 'File không phải ảnh hợp lệ.'
    if ext == '.jpeg':
        ext = '.jpg'
    return ext, ''


def _nen_tra_loi(s):
    return re.sub(r'\s+', ' ', _khong_dau(s or '').strip())


def khop_dien(chon, dap):
    """Điền khuyết: nhiều đáp án cách nhau bởi |, không phân biệt hoa/dấu."""
    c = _nen_tra_loi(chon)
    if not c:
        return False
    return any(_nen_tra_loi(x) == c for x in str(dap or '').split('|') if x.strip())


def parse_ghep(s):
    """'1a,2c,3b' hoặc dict → {1:'a', 2:'c', 3:'b'}."""
    if isinstance(s, dict):
        ra = {}
        for k, v in s.items():
            try:
                i = int(k)
            except (TypeError, ValueError):
                continue
            chu = str(v or '').strip().lower()[:1]
            if chu in CHU_GC:
                ra[i] = chu
        return ra
    ra = {}
    for m in re.finditer(r'(\d+)\s*[-:.]?\s*([a-hA-H])', str(s or '')):
        ra[int(m.group(1))] = m.group(2).lower()
    return ra


def dumps_ghep(mp):
    return ','.join('%d%s' % (i, mp[i]) for i in sorted(mp) if mp.get(i) in CHU_GC)


def _tron_dap_mot(q, rng):
    """Trộn phương án 1 câu, giữ đáp án đúng (kèm ảnh phương án nếu có)."""
    loai = loai_cau(q)
    if loai == 'tn':
        lc = dict(q.get('lua_chon') or {})
        keys = [k for k in CHU if k in lc]
        if len(keys) < 2:
            return
        anh_pa = dict(q.get('anh_pa') or {})
        da_cu = q.get('dap_an')
        rng.shuffle(keys)
        q['lua_chon'] = {CHU[i]: lc[keys[i]] for i in range(len(keys))}
        q['anh_pa'] = {CHU[i]: anh_pa[keys[i]]
                       for i in range(len(keys)) if anh_pa.get(keys[i])}
        if da_cu in keys:
            q['dap_an'] = CHU[keys.index(da_cu)]
        return
    if loai != 'gc':
        return
    a = list(q.get('cot_a') or [])
    b = list(q.get('cot_b') or [])
    mp = parse_ghep(q.get('dap_an'))
    if len(a) < 2 or len(b) < 2:
        return
    anh_a = (list(q.get('anh_a') or []) + [''] * len(a))[:len(a)]
    anh_b = (list(q.get('anh_b') or []) + [''] * len(b))[:len(b)]
    idx = list(range(len(b)))
    rng.shuffle(idx)
    b_moi = [b[i] for i in idx]
    anh_b_moi = [anh_b[i] for i in idx]
    cu_sang_moi = {CHU_GC[i]: CHU_GC[idx.index(i)] for i in range(len(b))}
    cap = [(a[i], anh_a[i], mp.get(i + 1)) for i in range(len(a))]
    rng.shuffle(cap)
    q['cot_a'] = [t for t, _, _ in cap]
    q['anh_a'] = [x for _, x, _ in cap]
    q['cot_b'] = b_moi
    q['anh_b'] = anh_b_moi
    q['dap_an'] = dumps_ghep({i + 1: cu_sang_moi.get(chu, chu) for i, (_, _, chu) in enumerate(cap)})


def tron_de(ds, tron_cau=True, tron_dap=True, seed=None):
    """Trộn thứ tự câu và/hoặc đáp án. Trả bản sao, đánh lại id 1..n."""
    ra = json.loads(json.dumps(ds or []))
    rng = random.Random(seed)
    if tron_dap:
        for q in ra:
            _tron_dap_mot(q, rng)
    if tron_cau:
        rng.shuffle(ra)
    for i, q in enumerate(ra, 1):
        q['id'] = i
    return ra


def seed_de_hs(khoa, ten_chuan):
    """Seed ổn định theo mã đề + tên học sinh (không dùng hash() của Python)."""
    raw = ('%s|%s' % (khoa or '', ten_chuan or '')).encode('utf-8')
    return int(hashlib.md5(raw).hexdigest()[:12], 16)


def de_cho_hs(ds, khoa, ten_chuan):
    """Đề trộn riêng cho từng học sinh khi vào làm bài."""
    return tron_de(ds, tron_cau=True, tron_dap=True, seed=seed_de_hs(khoa, ten_chuan))


def chuan_cau_soan(q, stt=1):
    """Chuẩn hoá 1 câu soạn tay. Trả (q, lỗi)."""
    loai = loai_cau(q)
    cau = re.sub(r'\s+', ' ', (q.get('cau') or '').strip())
    if loai == 'gc' and len(cau) < 2:
        cau = 'Ghép cột A với cột B'
    if len(cau) < 2 and q.get('anh'):
        cau = 'Nhìn hình rồi trả lời'
    if len(cau) < 2:
        return None, 'Câu %d: hãy nhập nội dung câu hỏi hoặc chèn hình.' % stt
    ra = {'id': int(q.get('id') or stt), 'loai': loai, 'cau': cau[:800],
          'anh': (q.get('anh') or '')[:80]}
    if loai == 'tn':
        ra['lua_chon'] = dict(q.get('lua_chon') or {})
        ra['anh_pa'] = dict(q.get('anh_pa') or {})
        ra['dap_an'] = str(q.get('dap_an') or '').upper()[:1]
        if not _gop_lua_chon(ra):
            return None, 'Câu %d: trắc nghiệm cần ít nhất 2 phương án (chữ hoặc hình) và 1 đáp án đúng.' % stt
        return ra, ''
    if loai == 'ds':
        da = str(q.get('dap_an') or '').upper()[:1]
        if da in ('A', 'D'):
            da = 'D'
        elif da in ('B', 'S'):
            da = 'S'
        if da not in ('D', 'S'):
            return None, 'Câu %d: chọn đáp án Đúng hoặc Sai.' % stt
        ra['dap_an'] = da
        ra['lua_chon'] = {'A': 'Đúng', 'B': 'Sai'}
        return ra, ''
    if loai == 'gc':
        def _hang(texts, anhs):
            tt, aa = [], []
            anhs = list(anhs or [])
            for i, x in enumerate(texts or []):
                t = re.sub(r'\s+', ' ', str(x)).strip()[:200]
                a = str(anhs[i] if i < len(anhs) else '')[:80]
                if t or a:
                    tt.append(t)
                    aa.append(a)
            return tt, aa
        a, anh_a = _hang(q.get('cot_a'), q.get('anh_a'))
        b, anh_b = _hang(q.get('cot_b'), q.get('anh_b'))
        if len(a) < 2:
            return None, 'Câu %d: cột A cần ít nhất 2 ý (chữ hoặc hình).' % stt
        if len(b) < 2:
            return None, 'Câu %d: cột B cần ít nhất 2 ý (chữ hoặc hình).' % stt
        if len(a) > 8 or len(b) > 8:
            return None, 'Câu %d: mỗi cột tối đa 8 ý.' % stt
        if len(b) < len(a):
            return None, 'Câu %d: cột B không được ít ý hơn cột A.' % stt
        mp = parse_ghep(q.get('dap_an'))
        chu = CHU_GC[:len(b)]
        for i in range(1, len(a) + 1):
            if mp.get(i) not in chu:
                return None, 'Câu %d: chọn chữ cột B cho ý %d cột A.' % (stt, i)
        if len(set(mp[i] for i in range(1, len(a) + 1))) != len(a):
            return None, 'Câu %d: mỗi ý cột A phải ghép một chữ cột B khác nhau.' % stt
        ra['cot_a'] = a
        ra['cot_b'] = b
        ra['anh_a'] = anh_a
        ra['anh_b'] = anh_b
        ra['dap_an'] = dumps_ghep({i: mp[i] for i in range(1, len(a) + 1)})
        ra['lua_chon'] = {}
        return ra, ''
    da = str(q.get('dap_an') or '').strip()[:500]
    if loai == 'dk' and not da:
        return None, 'Câu %d: nhập đáp án điền khuyết (nhiều đáp án cách nhau bởi |).' % stt
    ra['dap_an'] = da
    ra['lua_chon'] = {}
    return ra, ''


def khop_tra_loi(q, chon):
    loai = loai_cau(q)
    da = q.get('dap_an') or ''
    chon = '' if chon is None else str(chon).strip()
    if loai == 'tn':
        return chon.upper()[:1] == str(da).upper()[:1]
    if loai == 'ds':
        c = chon.upper()[:1]
        d = str(da).upper()[:1]
        if c in ('A', 'D'):
            c = 'D'
        elif c in ('B', 'S'):
            c = 'S'
        if d in ('A',):
            d = 'D'
        elif d in ('B',):
            d = 'S'
        return c in ('D', 'S') and c == d
    if loai == 'gc':
        dung = parse_ghep(da)
        chon_mp = parse_ghep(chon)
        if not dung:
            return False
        return all(chon_mp.get(i) == dung[i] for i in dung)
    if loai in ('dk', 'tl'):
        if not str(da).strip():
            return False
        return khop_dien(chon, da)
    return False


def an_dap_an(ds):
    """Bản cho học sinh: không lộ đáp án, giữ loại câu, ảnh câu / ảnh đáp án."""
    ra = []
    for q in ds:
        d = {
            'id': q['id'], 'cau': q.get('cau') or '',
            'loai': loai_cau(q),
            'anh': q.get('anh') or '',
            'lua_chon': dict(q.get('lua_chon') or {}),
            'anh_pa': dict(q.get('anh_pa') or {}),
        }
        if d['loai'] == 'gc':
            d['cot_a'] = list(q.get('cot_a') or [])
            d['cot_b'] = list(q.get('cot_b') or [])
            d['anh_a'] = list(q.get('anh_a') or [])
            d['anh_b'] = list(q.get('anh_b') or [])
        ra.append(d)
    return ra


def cham_diem(ds, tra_loi):
    """tra_loi: {id: 'A'|chữ}. Điểm thang 10, làm tròn 0.25.

    Tự luận không có đáp án mẫu thì không tính vào điểm (thầy/cô xem bài nộp).
    """
    mp = {}
    if isinstance(tra_loi, dict):
        mp = {str(k): v for k, v in tra_loi.items()}
    elif isinstance(tra_loi, list):
        for i, v in enumerate(tra_loi, 1):
            mp[str(i)] = v
    dung = 0
    n = 0
    ct = []
    for q in ds:
        loai = loai_cau(q)
        chon = mp.get(str(q['id']), '')
        chon = '' if chon is None else str(chon)
        tinh = not (loai == 'tl' and not str(q.get('dap_an') or '').strip())
        ok = khop_tra_loi(q, chon) if tinh else False
        if tinh:
            n += 1
            if ok:
                dung += 1
        ct.append({'id': q['id'], 'chon': chon, 'dung': q.get('dap_an'),
                   'ok': ok, 'loai': loai, 'tinh': tinh})
    if n <= 0:
        return None, 0, 0, ct
    diem = round(10.0 * dung / n * 4) / 4.0
    return diem, dung, n, ct


def nhan_xet_bai(diem, mon=''):
    md = NX.diem_to_mucdo(diem) or 'HT'
    return NX.sinh_nhan_xet({'diem': diem, 'muc_do': md, 'mon': mon or 'bài kiểm tra',
                             'hien_diem': True}), md


def xuat_excel(hang, meta=None):
    """hang đã sắp theo tên, lót, họ. Cột tách Họ / Tên lót / Tên."""
    meta = meta or {}
    hang = sap_xep_hs(hang)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Ket qua'
    tieu = meta.get('tieu_de') or 'KẾT QUẢ BÀI KIỂM TRA'
    hdr = ['STT', 'Họ', 'Tên lót', 'Tên', 'Họ và tên', 'Điểm', 'Mức đạt', 'Nhận xét', 'Nộp lúc']
    ws.append([tieu])
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(hdr))
    ws['A1'].font = Font(bold=True, size=14)
    ws['A1'].alignment = Alignment(horizontal='center')
    sub = '%s%s' % (meta.get('lop') or '',
                    (' · ' + meta['mon']) if meta.get('mon') else '')
    ws.append([sub])
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(hdr))
    ws.append(hdr)
    fill = PatternFill('solid', fgColor='D6EFE6')
    for c in range(1, len(hdr) + 1):
        cell = ws.cell(row=3, column=c)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.alignment = Alignment(horizontal='center')
    for i, r in enumerate(hang, 1):
        ho, lot, ten = tach_ten(r.get('ho_ten') or '')
        ws.append([i, ho, lot, ten, r.get('ho_ten') or '',
                   r.get('diem'), r.get('muc_do') or '',
                   r.get('nhan_xet') or '', r.get('created') or ''])
    for i, w in enumerate([6, 16, 16, 12, 28, 8, 10, 48, 20], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=4):
        row[7].alignment = Alignment(wrap_text=True, vertical='top')
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def dumps_cau(ds):
    return json.dumps(ds, ensure_ascii=False)


def loads_cau(s):
    try:
        ds = json.loads(s or '[]')
    except Exception:
        return []
    return ds if isinstance(ds, list) else []


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M')

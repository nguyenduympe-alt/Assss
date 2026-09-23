"""Gửi email (SMTP). Chưa khai máy chủ thì chỉ ghi nhật ký — không gửi thật."""
import datetime
import logging
import re
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from . import config as CFG

log = logging.getLogger("mailer")
RE_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+$")


def chuan(s):
    s = (s or "").strip().lower()
    return s if s and len(s) <= 254 and RE_EMAIL.fullmatch(s) else None


def _tg():
    return CFG.get_int("SMTP_TIMEOUT", 15)


def _from():
    frm = (CFG.get("SMTP_FROM") or CFG.get("SMTP_USER") or "").strip()
    ten = CFG.get("SITE_NAME", "EduAssist")
    if not frm:
        frm = "noreply@localhost"
    return formataddr((str(Header(ten, "utf-8")), frm))


def _log_db(db, teacher_id, to, subject, text, loai, ok, msg):
    if db is not None:
        try:
            db.execute(
                "INSERT INTO sms_log(teacher_id,phone,noi_dung,loai,provider,ok,ket_qua,created)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (teacher_id, to, (subject + "\n" + text)[:4000], loai,
                 "smtp" if CFG.get("SMTP_HOST") else "log",
                 1 if ok else 0, msg,
                 datetime.datetime.now().isoformat(timespec="seconds")))
            db.commit()
        except Exception as e:
            log.warning("Không ghi được nhật ký email: %s", e)
    return ok, msg


def send(to, subject, text, html=None, db=None, teacher_id=None, loai="mail"):
    """Trả (ok, thông_điệp)."""
    to = chuan(to)
    if not to:
        return _log_db(db, teacher_id, to or "", subject, text, loai, False,
                       "Địa chỉ email không hợp lệ")
    host = (CFG.get("SMTP_HOST") or "").strip()
    if not host:
        log.info("[MAIL-GIẢ LẬP] tới %s | %s\n%s", to, subject, text)
        return _log_db(db, teacher_id, to, subject, text, loai, True,
                       "Chế độ giả lập — chưa cấu hình SMTP, thư được ghi nhật ký")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = _from()
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg.attach(MIMEText(text, "plain", "utf-8"))
    if html:
        msg.attach(MIMEText(html, "html", "utf-8"))

    port = CFG.get_int("SMTP_PORT", 587)
    user = (CFG.get("SMTP_USER") or "").strip()
    pw = CFG.get("SMTP_PASS") or ""
    try:
        if port == 465:
            smtp = smtplib.SMTP_SSL(host, port, timeout=_tg())
        else:
            smtp = smtplib.SMTP(host, port, timeout=_tg())
            if CFG.get_bool("SMTP_TLS", True):
                smtp.starttls()
        if user:
            smtp.login(user, pw)
        smtp.sendmail(msg["From"], [to], msg.as_string())
        smtp.quit()
    except Exception as e:
        log.warning("SMTP lỗi: %s", e)
        return _log_db(db, teacher_id, to, subject, text, loai, False, "SMTP lỗi: %s" % e)
    return _log_db(db, teacher_id, to, subject, text, loai, True, "Đã gửi email")

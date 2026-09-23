"""Điểm nhận dữ liệu giao dịch từ dịch vụ đối soát ngân hàng.

SePay (khuyến nghị, tài liệu hiện hành):
    POST https://<tên-miền>/webhook/sepay
    Header: Authorization: Apikey <SEPAY_API_KEY>
    SEPAY_API_KEY chỉ đặt trong biến môi trường máy chủ — không đưa ra giao diện.

Casso / SMS / đường cũ:
    POST https://<tên-miền>/webhook/bank
    Header: Authorization: Apikey <BANK_WEBHOOK_TOKEN>
"""
import json
import logging

from flask import Blueprint, request, jsonify

from .db import get_db
from .modules import bank_webhook as BW
from .modules import sepay as SP

log = logging.getLogger("webhook")
bp = Blueprint("webhook", __name__, url_prefix="/webhook")


@bp.route("/bank", methods=["POST", "GET"])
def bank():
    if request.method == "GET":
        return jsonify(success=True, message="EduAssist webhook đang hoạt động")

    raw = request.get_data() or b""
    ok, msg = BW.check_auth(request.headers, raw)
    if not ok:
        log.warning("Webhook bị từ chối: %s — IP %s", msg, request.remote_addr)
        return jsonify(success=False, message=msg), 401

    try:
        data = request.get_json(force=True, silent=True)
        if data is None:
            data = json.loads(raw.decode("utf-8", "ignore") or "{}")
    except Exception as e:
        return jsonify(success=False, message=f"Dữ liệu không phải JSON hợp lệ: {e}"), 400

    try:
        ket_qua = BW.xu_ly_tat_ca(get_db(), data)
    except Exception as e:
        log.exception("Lỗi xử lý giao dịch")
        return jsonify(success=False, message=f"Lỗi xử lý: {e}"), 500

    log.info("Webhook xử lý %d giao dịch: %s", len(ket_qua),
             [k["trang_thai"] for k in ket_qua])
    return jsonify(success=True, so_giao_dich=len(ket_qua), ket_qua=ket_qua)


@bp.route("/sepay", methods=["POST", "GET"])
def sepay():
    """Webhook SePay — chỉ bật khi có SEPAY_API_KEY trên máy chủ."""
    if request.method == "GET":
        # SePay / vận hành kiểm tra URL sống. Không tiết lộ trạng thái khoá.
        return jsonify(success=True)

    ok, st, msg = SP.check_auth(request.headers)
    if not ok:
        log.warning("SePay từ chối: %s — IP %s", msg, request.remote_addr)
        return jsonify(success=False), st

    raw = request.get_data() or b""
    ctype = (request.content_type or "").split(";")[0].strip().lower()
    data = None
    if ctype in ("application/x-www-form-urlencoded", "multipart/form-data") and request.form:
        data = request.form.to_dict()
    else:
        data = request.get_json(silent=True, force=False)
        if data is None:
            if not raw.strip():
                data = {}
            else:
                try:
                    data = json.loads(raw.decode("utf-8"))
                except Exception:
                    return jsonify(success=False), 400

    try:
        SP.xu_ly(get_db(), data if isinstance(data, dict) else {})
    except Exception:
        log.exception("SePay: lỗi xử lý")
        return jsonify(success=False), 500

    return jsonify(success=True)

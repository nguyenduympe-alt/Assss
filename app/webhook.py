"""Điểm nhận dữ liệu giao dịch từ dịch vụ đối soát ngân hàng.

Khai báo URL này trong bảng điều khiển SePay / Casso:
    https://<tên-miền>/webhook/bank
Kèm khoá bí mật BANK_WEBHOOK_TOKEN:
    SePay: gửi header  Authorization: Apikey <token>
    Casso: gửi header  Secure-Token: <token>
"""
import json
import logging

from flask import Blueprint, request, jsonify

from .db import get_db
from .modules import bank_webhook as BW

log = logging.getLogger("webhook")
bp = Blueprint("webhook", __name__, url_prefix="/webhook")


@bp.route("/bank", methods=["POST", "GET"])
def bank():
    if request.method == "GET":
        # để dịch vụ kiểm tra URL sống hay chưa
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
    # SePay/Casso cần nhận HTTP 200 kèm success=true, nếu không sẽ gửi lại
    return jsonify(success=True, so_giao_dich=len(ket_qua), ket_qua=ket_qua)

"""SePay payload adapters and HTTP client (https://docs.sepay.vn)."""
from datetime import datetime

import pytz
import requests

API_URL = "https://my.sepay.vn/userapi/transactions/list"
SEPAY_TZ = pytz.timezone("Asia/Ho_Chi_Minh")  # SePay dates carry no offset; they are VN local time
TIMEOUT = 15


def _to_utc(value):
    local = SEPAY_TZ.localize(datetime.strptime(value, "%Y-%m-%d %H:%M:%S"))
    return local.astimezone(pytz.utc).replace(tzinfo=None)


def sepay_webhook_to_vals(p):
    return {
        "external_id": str(p["id"]),
        "date": _to_utc(p["transactionDate"]),
        "amount": float(p["transferAmount"]),
        "content": p.get("content") or "",
        "reference": p.get("referenceCode") or "",
        "account_number": p.get("accountNumber") or "",
        "gateway": p.get("gateway") or "",
        "raw_payload": p,
    }


def sepay_api_to_vals(t):
    """Return vals for an incoming API transaction, or None for outgoing ones."""
    amount_in = float(t.get("amount_in") or 0)
    if amount_in <= 0:
        return None
    return {
        "external_id": str(t["id"]),
        "date": _to_utc(t["transaction_date"]),
        "amount": amount_in,
        "content": t.get("transaction_content") or "",
        "reference": t.get("reference_number") or "",
        "account_number": t.get("account_number") or "",
        "gateway": t.get("bank_brand_name") or "",
        "raw_payload": t,
    }


def fetch_transactions(token, account_number, since_id):
    """Transactions with id >= since_id (SePay semantics), newest first."""
    params = {"since_id": since_id, "limit": 5000}
    if account_number:
        params["account_number"] = account_number
    response = requests.get(
        API_URL,
        params=params,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("transactions") or []

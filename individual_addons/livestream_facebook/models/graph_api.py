"""Thin Graph API client. Every call goes through `_request` (patched in tests)."""
import json as jsonlib
from datetime import datetime, timezone

import requests

from odoo.exceptions import UserError

GRAPH_VERSION = "v27.0"  # latest on developers.facebook.com/docs/graph-api/changelog (Nov 2026)
GRAPH_URL = f"https://graph.facebook.com/{GRAPH_VERSION}"
TIMEOUT = 20


class MetaApiError(UserError):
    """Graph API error, keeping Meta's numeric error code (190 = invalid/expired token)."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _request(method, path, token, params=None, json=None, data=None, files=None):
    params = dict(params or {}, access_token=token)
    try:
        response = requests.request(
            method, f"{GRAPH_URL}/{path}", params=params, json=json, data=data, files=files, timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        # never propagate the exception text: it contains the full URL with tokens/secrets
        raise MetaApiError(f"Facebook: network error ({type(e).__name__}) contacting graph.facebook.com") from None
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code >= 400 or "error" in body:
        error = body.get("error") or {}
        raise MetaApiError(f"Facebook: {error.get('message') or response.text[:300]}", code=error.get("code"))
    return body


def parse_time(value):
    """Graph returns unix seconds in webhooks and ISO-8601 (+0000) in the API."""
    if value in (None, ""):
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if isinstance(value, (int, float)) or str(value).isdigit():
        return datetime.fromtimestamp(int(value), timezone.utc).replace(tzinfo=None)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z").astimezone(timezone.utc).replace(tzinfo=None)


def send_text(token, page_id, recipient, text, messaging_type=None):
    body = {"recipient": recipient, "message": {"text": text}}
    if messaging_type:
        body["messaging_type"] = messaging_type
    return _request("POST", f"{page_id}/messages", token, json=body)


def send_image(token, page_id, psid, filename, content, mimetype):
    return _request(
        "POST", f"{page_id}/messages", token,
        data={
            "recipient": jsonlib.dumps({"id": psid}),
            "messaging_type": "RESPONSE",
            "message": jsonlib.dumps({"attachment": {"type": "image", "payload": {"is_reusable": False}}}),
        },
        files={"filedata": (filename, content, mimetype)},
    )

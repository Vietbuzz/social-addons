"""Instagram messaging via the linked Facebook Page (Facebook Login flow)."""
import json

from odoo.addons.livestream_facebook.models import graph_api

TEXT_LIMIT = 1000  # bytes, UTF-8


def split_utf8(text, limit=TEXT_LIMIT):
    """Split text into chunks of at most `limit` UTF-8 bytes, on whitespace when possible."""
    text = (text or "").strip()
    if len(text.encode()) <= limit:
        return [text] if text else []
    parts, current = [], ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if len(candidate.encode()) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        current = ""
        while len(word.encode()) > limit:  # a single overlong "word": cut on characters
            chunk = ""
            for ch in word:
                if len((chunk + ch).encode()) > limit:
                    break
                chunk += ch
            parts.append(chunk)
            word = word[len(chunk):]
        current = word
    if current:
        parts.append(current)
    return parts


def send_text(token, page_id, recipient, text, messaging_type=None):
    body = {"recipient": recipient, "message": {"text": text}}
    if messaging_type:
        body["messaging_type"] = messaging_type
    return graph_api._request("POST", f"{page_id}/messages", token, json=body)


def send_image(token, page_id, igsid, filename, content, mimetype):
    """Upload the image as an Instagram attachment, then send it (file names must be ASCII)."""
    safe_name = filename.encode("ascii", "ignore").decode() or "image.png"
    uploaded = graph_api._request(
        "POST", f"{page_id}/message_attachments", token,
        data={
            "platform": "instagram",
            "message": json.dumps({"attachment": {"type": "image", "payload": {"is_reusable": False}}}),
        },
        files={"filedata": (safe_name, content, mimetype)},
    )
    return graph_api._request("POST", f"{page_id}/messages", token, json={
        "recipient": {"id": igsid},
        "message": {"attachment": {"type": "image", "payload": {"attachment_id": uploaded["attachment_id"]}}},
    })

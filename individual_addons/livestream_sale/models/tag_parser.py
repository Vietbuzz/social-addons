"""Parse a product tag (and optional quantity) out of a livestream comment.

Accepted shapes: ``69``, ``#69``, ``ma 69``, ``mã69``, ``69 x2``, ``69x2``,
``69 sl 3``, ``69*2``, ``69 - 2c``.  Digit runs of 8+ characters (phone
numbers) and digits glued to other words are never taken as tags.
"""
import re

_TAG_RE = re.compile(
    r"(?<!\w)(?:#|m[aã]\s*)?"
    r"(?P<code>\d{1,7})"
    r"(?:\s*(?:x|\*|sl|-)\s*(?P<qty>\d{1,3})\s*c?)?"
    r"(?!\w)",
    re.IGNORECASE,
)


def parse_tag(message, codes=None):
    """Return ``(code, qty)``; ``code`` is None when no tag is found.

    :param str message: raw comment text
    :param set codes: when given, only codes in this set are accepted
    """
    for match in _TAG_RE.finditer(message or ""):
        code = match.group("code")
        if codes is not None and code not in codes:
            continue
        qty = int(match.group("qty") or 1)
        return code, max(qty, 1)
    return None, 1

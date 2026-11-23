"""Parse a product tag (and optional quantity) out of a livestream comment.

Accepted shapes: ``69``, ``#69``, ``ma 69``, ``mã69``, ``69 x2``, ``69x2``,
``69 sl 3``, ``69*2``, ``69 - 2c``.  Phone numbers (also written with
spaces/dots/dashes or +84) are removed first; a number followed by a
quantity word (``2 cái``) is a quantity, never a tag; tags introduced by
``#`` / ``mã`` win over bare numbers.
"""
import re

_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
_QTY_WORD = r"(?:c[aá]i|chi[eế]c|sp|b[oộ]|c)\b"
_TAG_RE = re.compile(
    r"(?<!\w)(?P<prefix>#|m[aã]\s*)?"
    r"(?P<code>\d{1,7})"
    r"(?:\s*(?:x|\*|sl)\s*(?P<qty>\d{1,3})|\s*-\s*(?P<qty2>\d{1,3})\s*c\b)?"
    r"(?!\w)(?!\s*" + _QTY_WORD + r")",
    re.IGNORECASE,
)
_LEADING_QTY_RE = re.compile(r"(?<!\w)(\d{1,3})\s*" + _QTY_WORD, re.IGNORECASE)


def parse_tag(message, codes=None):
    """Return ``(code, qty)``; ``code`` is None when no tag is found.

    :param str message: raw comment text
    :param set codes: when given, only codes in this set are accepted
    """
    text = _PHONE_RE.sub(" ", message or "")
    candidates = []
    for match in _TAG_RE.finditer(text):
        code = match.group("code")
        if codes is not None and code not in codes:
            continue
        qty = int(match.group("qty") or match.group("qty2") or 0)
        candidates.append((bool(match.group("prefix")), code, qty))
    if not candidates:
        return None, 1
    prefixed = [c for c in candidates if c[0]]
    _prefix, code, qty = (prefixed or candidates)[0]
    if not qty:
        leading = _LEADING_QTY_RE.search(text)
        qty = int(leading.group(1)) if leading else 1
    return code, max(qty, 1)

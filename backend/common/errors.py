"""Closed error codes and response shapes (PRD §6). Frozen contract."""

CODES = frozenset({
    "IDENTITY_REVOKED", "UNAUTHORIZED_TOOL", "INVALID_ARGS", "NOT_FOUND", "AMBIGUOUS_NAME",
    "IBAN_MISMATCH", "AMOUNT_MISMATCH", "DUPLICATE", "INVOICE_NOT_VERIFIED",
    "APPROVAL_REQUIRED", "UPSTREAM_UNAVAILABLE",
})
# Client-side only: an unknown tool fails at the MCP layer and the caller reports this.
NO_SUCH_TOOL = "NO_SUCH_TOOL"

DENIED_MESSAGE = "Blocked by policy. Do not retry with other values. The invoice is on HOLD."
NOTICE = "Built from an untrusted document. Only extracted fields are shown, so this view may be incomplete."

_ERROR_MESSAGES = {
    "INVALID_ARGS": "Invalid arguments.",
    "NOT_FOUND": "Not found.",
    "AMBIGUOUS_NAME": "Name matches more than one record.",
    "UPSTREAM_UNAVAILABLE": "A required service is unavailable. Nothing was changed.",
}


def denied(*codes: str) -> dict:
    assert codes and all(c in CODES for c in codes), codes
    return {"status": "DENIED", "code": codes[0], "codes": list(codes), "message": DENIED_MESSAGE}


def error(code: str) -> dict:
    assert code in CODES, code
    return {"status": "ERROR", "code": code, "codes": [code], "message": _ERROR_MESSAGES.get(code, "Request failed.")}

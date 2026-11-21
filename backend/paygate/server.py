"""paygate: FastMCP server exposing exactly six task tools (PRD §6). Descriptions are frozen contract text.

The decorated functions only publish name, arguments and description. Every call to one of the six tools is
intercepted by GateMiddleware and answered by Gate.call (F0–F2 on the raw arguments, then the handler), so no
handler runs before the firewall. Unknown tool names fall through to FastMCP and fail at the MCP layer.
"""
import json
import threading
import time
from datetime import datetime, timezone

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware
from fastmcp.tools.base import ToolResult

from backend.common import config
from backend.common.events import emit, tool_line
from backend.paygate.firewall import ARGS, Gate

mcp = FastMCP("paygate")
_gate: Gate | None = None


def gate() -> Gate:
    global _gate
    if _gate is None:
        from backend.paygate.policy import load_policy
        from backend.paygate.store import FirestoreStore
        _gate = Gate(load_policy(), FirestoreStore(), config.TOKENS, config.APPROVAL_SECRET, config.APPROVER_UID)
    return _gate


class GateMiddleware(Middleware):
    async def on_call_tool(self, context, call_next):
        name, args = context.message.name, context.message.arguments or {}
        if name not in ARGS:
            return await call_next(context)
        auth = get_http_headers(include={"authorization"}).get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else None
        tool_line(name, **{k: v for k, v in args.items() if k in ("invoice", "amount_eur", "iban", "vendor", "title")})
        res = gate().call(token, name, dict(args))
        return ToolResult(content=[mt.TextContent(type="text", text=json.dumps(res, ensure_ascii=False))],
                          structured_content=res)


mcp.add_middleware(GateMiddleware())

DESC = {
    "get_invoice": "Get the extracted fields and status of an invoice. Pass the invoice number, e.g. INV-1002. "
                   "The result may be incomplete; never guess missing values.",
    "verify_invoice": "Run every payment check on an invoice and get each result. Pass the invoice number. "
                      "Call this before request_payment.",
    "get_payment_history": "List recent payments to a vendor. Pass the vendor's name. "
                           "The result says how many payments exist and how many are shown.",
    "place_hold": "Stop an invoice from being paid and alert a human. Pass the invoice number and a short reason.",
    "raise_alert": "Send a short alert to the human approver.",
    "request_payment": "Ask a human to approve paying a verified invoice. Pass the invoice number, the exact amount "
                       "in EUR and the IBAN. DENIED means a payment rule failed and the invoice is now on hold; "
                       "do not retry.",
}


def _unreachable(*_a, **_k) -> dict:  # GateMiddleware answers every call to these six tools
    raise RuntimeError("paygate tool reached without firewall")


@mcp.tool(description=DESC["get_invoice"])
def get_invoice(invoice: str) -> dict:
    return _unreachable()


@mcp.tool(description=DESC["verify_invoice"])
def verify_invoice(invoice: str) -> dict:
    return _unreachable()


@mcp.tool(description=DESC["get_payment_history"])
def get_payment_history(vendor: str) -> dict:
    return _unreachable()


@mcp.tool(description=DESC["place_hold"])
def place_hold(invoice: str, reason: str) -> dict:
    return _unreachable()


@mcp.tool(description=DESC["raise_alert"])
def raise_alert(title: str, detail: str) -> dict:
    return _unreachable()


@mcp.tool(description=DESC["request_payment"])
def request_payment(invoice: str, amount_eur: str, iban: str) -> dict:
    return _unreachable()


def approval_listener(poll_s: float = 1.0):
    """L6 listener: APPROVED -> sign + execute; REJECTED -> invoice REJECTED; PENDING past TTL -> EXPIRED.
    ponytail: 1 s polling instead of on_snapshot; robust against silent listener-thread death."""
    from backend.paygate import approvals
    g = gate()
    col = g.store.db.collection("approvals")
    while True:
        try:
            for snap in col.where("status", "in", ["PENDING", "APPROVED", "REJECTED"]).stream():
                a, aid = snap.to_dict(), snap.id
                if a["status"] == "APPROVED":
                    approvals.on_approved(g, aid)
                elif a["status"] == "REJECTED":
                    inv = g.store.invoice(a["invoice_id"]) or {}
                    if inv.get("status") == "PENDING_APPROVAL":
                        g.store.update_invoice(a["invoice_id"], status="REJECTED")
                        emit(a.get("run_id") or "run-0000", "human", "DECISION", "DENY", f"Rejected by CFO: {a['invoice_no']}",
                             f"Approval {aid}", invoice_id=a["invoice_id"], layer="L6", amount_cents=a["amount_cents"])
                elif a["expires_at"] < datetime.now(timezone.utc):
                    g.store.update_approval(aid, status="EXPIRED")
                    inv = g.store.invoice(a["invoice_id"]) or {}
                    if inv.get("status") == "PENDING_APPROVAL":  # nobody approved in time: hold, a human looks
                        g._hold(a.get("run_id") or "run-0000", inv, "Approval expired")
        except Exception as e:  # keep listening; execution itself fails closed
            print(f"approval listener: {e.__class__.__name__}: {e}")
        time.sleep(poll_s)


if __name__ == "__main__":
    if config.GCP_PROJECT:
        threading.Thread(target=approval_listener, daemon=True).start()
    mcp.run(transport="http", host="0.0.0.0", port=8001, path="/mcp")

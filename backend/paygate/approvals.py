"""L6: approval token (HMAC), internal payment execution with F7 + F3–F5 re-check, and the Firestore listener.
No agent can reach any of this: it is not an MCP tool.
"""
import hashlib
import hmac
import time
from datetime import datetime, timezone

from backend.common import iban as ib
from backend.common.errors import denied
from backend.common.events import emit


def _unix(v) -> int:
    return int(v.timestamp()) if hasattr(v, "timestamp") else int(v)


def token_for(gate, approval_id: str) -> str:
    a = gate.store.approval(approval_id)
    inv = gate.store.invoice(a["invoice_id"])
    msg = f"{approval_id}|{a['invoice_id']}|{ib.normalize(inv['iban'])}|{a['amount_cents']}|{_unix(a['expires_at'])}"
    return hmac.new(gate.approval_secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def sign(gate, approval_id: str) -> str | None:
    """Signer: only for APPROVED approvals decided by the approver account."""
    a = gate.store.approval(approval_id)
    if not a or a["status"] != "APPROVED" or not gate.approver_uid or a.get("decided_by") != gate.approver_uid:
        return None
    return token_for(gate, approval_id)


def execute(gate, approval_id: str, token: str) -> dict:
    """Executor (the mock bank). F7, then F3–F5 again, then one atomic claim so the token is single use."""
    store = gate.store
    a = store.approval(approval_id)
    run_id = (a or {}).get("run_id") or store.run().get("current_run_id") or "run-0000"
    inv = store.invoice(a["invoice_id"]) if a else None
    f7_ok = bool(
        a and inv and gate.approval_secret and a["status"] == "APPROVED"
        and inv["status"] == "PENDING_APPROVAL"  # a HOLD placed after the request stops the payment
        and gate.approver_uid and a.get("decided_by") == gate.approver_uid
        and _unix(a["expires_at"]) > time.time()
        and hmac.compare_digest(token or "", token_for(gate, approval_id))
    )
    if not f7_ok:
        emit(run_id, "firewall", "DECISION", "DENY", "DENY execute APPROVAL_REQUIRED", "Token invalid, expired or unused approval",
             invoice_id=(a or {}).get("invoice_id"), layer="L6", codes=["APPROVAL_REQUIRED"])
        store.incr_stats(denied_actions=1)
        return denied("APPROVAL_REQUIRED")

    iban = ib.normalize(inv["iban"])
    codes = gate.policy.failed(gate.rule_activation(iban, a["amount_cents"], inv, exclude_approval=approval_id),
                               only=("IBAN_MISMATCH", "AMOUNT_MISMATCH", "DUPLICATE"))
    if codes:
        store.update_approval(approval_id, status="REJECTED")
        gate._hold(run_id, inv, f"Re-check at execution failed: {', '.join(codes)}",
                   rule_block=bool({"IBAN_MISMATCH", "AMOUNT_MISMATCH"} & set(codes)))
        gate._decide(run_id, "executor", "execute", inv["invoice_id"], "DENY", codes, a["amount_cents"])
        return denied(*codes)

    if not store.claim_approval(approval_id):  # transaction: APPROVED -> EXECUTED, reuse fails
        store.incr_stats(denied_actions=1)
        return denied("APPROVAL_REQUIRED")

    now = datetime.now(timezone.utc)
    store.add_payment({"invoice_no": inv["invoice_no"], "vendor_id": inv["vendor_id"], "amount_cents": a["amount_cents"],
                       "iban_last4": iban[-4:], "executed_at": now, "historic": False})
    store.reduce_po(inv["po_number"], a["amount_cents"])
    store.update_invoice(inv["invoice_id"], status="PAID")
    store.incr_stats(paid_cents=a["amount_cents"])
    gate._decide(run_id, "executor", "execute", inv["invoice_id"], "ALLOW", [], a["amount_cents"],
                 f"F7 token valid · re-check F3–F5 pass · {ib.mask(iban)}")
    emit(run_id, "bank", "DECISION", "ALLOW", f"Paid €{a['amount_cents'] / 100:,.2f}",
         f"{inv['invoice_no']} → {ib.mask(iban)} (simulated bank)", invoice_id=inv["invoice_id"],
         amount_cents=a["amount_cents"])
    return {"status": "EXECUTED", "invoice_id": inv["invoice_id"]}


def on_approved(gate, approval_id: str) -> dict:
    """Listener step for one APPROVED approval: human event, sign, execute."""
    a = gate.store.approval(approval_id)
    run_id = a.get("run_id") or "run-0000"
    emit(run_id, "human", "DECISION", "ALLOW", f"Approved by CFO: {a['invoice_no']}", f"Approval {approval_id}",
         invoice_id=a["invoice_id"], layer="L6", amount_cents=a["amount_cents"])
    token = sign(gate, approval_id)
    res = execute(gate, approval_id, token or "")
    if res["status"] != "EXECUTED" and (gate.store.approval(approval_id) or {}).get("status") == "APPROVED":
        gate.store.update_approval(approval_id, status="REJECTED")  # never retried by the listener
    return res

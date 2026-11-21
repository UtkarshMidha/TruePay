"""Action Firewall (L5): F0–F2 before every handler, F3–F6 on request_payment, the six tool handlers,
checks C1–C6, events and ledger rows. Pure logic over a store (Firestore/Sheets in prod, fakes in tests).
"""
import re
import traceback
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from backend.common import iban as ib
from backend.common.errors import NOTICE, denied, error
from backend.common.events import emit
from backend.common.money import eur, to_cents

INV_SHORT = re.compile(r"^INV-\d{4}$")
INV_FULL = re.compile(r"^INV-\d{4}-\d{2}$")

# tool -> {arg: max length or None}. Exactly the six agent-facing tools (PRD §6).
ARGS = {
    "get_invoice": {"invoice": 40},
    "verify_invoice": {"invoice": 40},
    "get_payment_history": {"vendor": 120},
    "place_hold": {"invoice": 40, "reason": 200},
    "raise_alert": {"title": 60, "detail": 200},
    "request_payment": {"invoice": 40, "amount_eur": 32, "iban": 64},
}
HOLDABLE_BLOCK_CHECKS = {"C3", "C4", "C5"}


class Deny(Exception):
    def __init__(self, *codes: str):
        self.codes = codes


def _fold(s: str) -> str:
    return " ".join(str(s).split()).casefold()


class Gate:
    def __init__(self, policy, store, tokens: dict, approval_secret: str = "", approver_uid: str = ""):
        self.policy, self.store, self.tokens = policy, store, tokens
        self.approval_secret, self.approver_uid = approval_secret, approver_uid
        self.unauthorized = Counter()  # ((session, run_id), identity) -> count. ponytail: in-memory, fine for one process

    # ------------------------------------------------------------------ entry point
    def call(self, token: str | None, tool: str, args: dict) -> dict:
        identity = self.tokens.get(token or "")
        run_id, inv_id, amount = "run-0000", None, None
        try:
            rt = self.store.run()
            run_id = rt.get("current_run_id") or run_id
            # F0
            if identity and identity in (rt.get("revoked") or []):
                raise Deny("IDENTITY_REVOKED")
            # F1
            if not identity or tool not in self.policy.identities.get(identity, []):
                self._unauthorized((str(rt.get("session_started_at")), run_id), identity)
                raise Deny("UNAUTHORIZED_TOOL")
            # F2
            a = self._validate(tool, args)
            inv = self._resolve(a["invoice"], run_id) if "invoice" in a else None
            if inv:
                inv_id, amount = inv["invoice_id"], inv.get("amount_cents")
            result = getattr(self, "_" + tool)(identity, run_id, a, inv)
            self._decide(run_id, identity, tool, inv_id, "ALLOW", [], result.pop("_amount", amount),
                         result.pop("_detail", ""))
            return result
        except Deny as d:
            self._decide(run_id, identity, tool, inv_id, "DENY", list(d.codes), amount)
            return denied(*d.codes)
        except Exception as e:  # Sheets/Firestore/anything down: fail closed, no stack trace to the agent
            print(f"paygate: {tool} failed closed: {e.__class__.__name__}: {e}")
            traceback.print_exc()
            try:
                self._decide(run_id, identity, tool, inv_id, "DENY", ["UPSTREAM_UNAVAILABLE"], amount)
            except Exception:
                pass
            return error("UPSTREAM_UNAVAILABLE")

    def _unauthorized(self, key, identity):
        """key = (session_started_at, run_id): make reset restarts run ids, so the session is part of the key."""
        if not identity:
            return
        run_id = key[1]
        self.unauthorized[(key, identity)] += 1
        if self.unauthorized[(key, identity)] >= self.policy.revoke_after_unauthorized:
            self.store.revoke(identity)
            emit(run_id, "firewall", "ALERT", "BLOCK", f"Identity revoked: {identity}",
                 f"{self.policy.revoke_after_unauthorized} unauthorized tool calls", layer="L5",
                 codes=["UNAUTHORIZED_TOOL"])

    def _validate(self, tool: str, args) -> dict:
        spec = ARGS[tool]
        if not isinstance(args, dict) or set(args) != set(spec):
            raise Deny("INVALID_ARGS")
        out = {}
        for k, maxlen in spec.items():
            v = args[k]
            if k == "amount_eur" and isinstance(v, (int, float)) and not isinstance(v, bool):
                v = repr(v)  # shortest round-trip repr of what the model typed, e.g. 18950.0
            if not isinstance(v, str) or not v.strip() or len(v) > maxlen:
                raise Deny("INVALID_ARGS")
            out[k] = v.strip()
        if "invoice" in out and not (INV_SHORT.match(out["invoice"]) or INV_FULL.match(out["invoice"])):
            raise Deny("INVALID_ARGS")
        if "iban" in out:
            out["iban"] = ib.normalize(out["iban"])
            if not ib.IBAN_RE.match(out["iban"]):
                raise Deny("INVALID_ARGS")
        if "amount_eur" in out:
            try:
                out["amount_cents"] = to_cents(out["amount_eur"])
            except ValueError:
                raise Deny("INVALID_ARGS")
            if not 0 < out["amount_cents"] <= self.policy.payment_limit_cents:
                raise Deny("INVALID_ARGS")
        if "vendor" in out:
            out["vendor_row"] = self._vendor(out["vendor"])
        return out

    def _resolve(self, ref: str, run_id: str) -> dict:
        inv = self.store.invoice(ref) if INV_FULL.match(ref) else next(iter(self.store.invoices_by_no(ref, run_id)), None)
        if not inv:
            raise Deny("NOT_FOUND")
        return inv

    def _vendor(self, ref: str) -> dict:
        hits = [v for v in self.store.vendors() if _fold(ref) in (_fold(v["name"]), _fold(v["vendor_id"]))]
        if not hits:
            raise Deny("NOT_FOUND")
        if len(hits) > 1:
            raise Deny("AMBIGUOUS_NAME")
        return hits[0]

    def _decide(self, run_id, identity, tool, inv_id, verdict, codes, amount, detail=""):
        if verdict == "DENY":
            self.store.incr_stats(denied_actions=1)
        title = f"{verdict} {tool}" + (f" {codes[0]}" if codes else "")
        emit(run_id, "firewall", "DECISION", verdict, title, detail or f"{identity or 'unknown'} · {tool} · {inv_id or '-'}",
             invoice_id=inv_id, layer="L5", tool=tool, codes=codes, amount_cents=amount)
        self.store.ledger({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": run_id,
                           "invoice_id": inv_id or "", "identity": identity or "unknown", "tool": tool,
                           "verdict": verdict, "codes": ",".join(codes),
                           "amount_eur": eur(amount) if amount is not None else ""})

    # ------------------------------------------------------------------ shared logic
    def _hold(self, run_id, inv: dict, reason: str, *, rule_block: bool = False):
        """Set HOLD (any state before PAID) and count blocked cents the first time (PRD §8 Counters)."""
        if inv["status"] == "PAID":
            return
        failed = {c["check"] for c in inv.get("checks") or [] if not c["pass"]}
        count = not inv.get("blocked_counted") and (
            inv["status"] == "QUARANTINED" or failed & HOLDABLE_BLOCK_CHECKS or rule_block)
        upd = {"status": "HOLD", "hold_reason": reason[:200]}
        if count:
            upd["blocked_counted"] = True
            self.store.incr_stats(blocked_cents=inv["amount_cents"])
        self.store.update_invoice(inv["invoice_id"], **upd)
        inv.update(upd)
        # no layer: the L5 row shows firewall decisions (ALLOW/DENY), not the hold itself
        emit(run_id, "firewall", "ALERT", "BLOCK", f"Invoice on HOLD: {inv['invoice_no']}", reason,
             invoice_id=inv["invoice_id"], tool="place_hold", amount_cents=inv["amount_cents"])

    def rule_activation(self, req_iban: str, req_cents: int, inv: dict, exclude_approval=None) -> dict:
        vendor = self._invoice_vendor(inv) or {}
        po = self.store.po(inv.get("po_number") or "") or {}
        po_ok = bool(vendor) and po.get("vendor_id") == vendor.get("vendor_id") and po.get("status") == "open"
        return {
            "iban_checksum_ok": ib.checksum_ok(req_iban),
            "already_paid_or_pending": self.store.already_paid_or_pending(inv["invoice_no"], exclude_approval),
            "req": {"iban": req_iban, "amount_cents": req_cents},
            "vendor": {"iban": ib.normalize(vendor.get("iban", "")) or "<none>"},
            "invoice": {"iban": ib.normalize(inv.get("iban", "")), "amount_cents": inv.get("amount_cents") or 0,
                        "status": inv["status"]},
            "po": {"remaining_cents": po.get("remaining_cents", 0) if po_ok else 0},
            "limit_cents": self.policy.payment_limit_cents,
        }

    def _invoice_vendor(self, inv: dict) -> dict | None:
        """The one vendor-master row whose name matches the invoice's vendor_name (C1), else None."""
        hits = [v for v in self.store.vendors() if _fold(v["name"]) == _fold(inv.get("vendor_name") or "")]
        return hits[0] if len(hits) == 1 else None

    def checks(self, inv: dict) -> list[dict]:
        """C1–C6 (PRD §6)."""
        vendor = self._invoice_vendor(inv)
        po = self.store.po(inv.get("po_number") or "")
        i = ib.normalize(inv.get("iban", ""))
        master = ib.normalize(vendor["iban"]) if vendor else ""
        c4 = bool(po and vendor and po["vendor_id"] == vendor["vendor_id"] and po["status"] == "open")
        c5 = bool(po and inv.get("amount_cents") and inv["amount_cents"] <= po["remaining_cents"])
        dup = self.store.already_paid_or_pending(inv["invoice_no"])
        return [
            {"check": "C1", "pass": bool(vendor), "detail": f"Vendor {'known' if vendor else 'unknown'}: {inv.get('vendor_name', '')}"[:120]},
            {"check": "C2", "pass": ib.checksum_ok(i), "detail": "IBAN checksum valid" if ib.checksum_ok(i) else "IBAN checksum invalid"},
            {"check": "C3", "pass": bool(master) and i == master,
             "detail": "IBAN = master" if master and i == master else f"IBAN ≠ master …{master[-4:] or '????'}"},
            {"check": "C4", "pass": c4, "detail": f"{inv.get('po_number')} {'open, belongs to vendor' if c4 else 'missing, closed or other vendor'}"},
            {"check": "C5", "pass": c5, "detail": "Amount within PO remaining" if c5 else "Amount exceeds PO remaining"},
            {"check": "C6", "pass": not dup, "detail": "Not a duplicate" if not dup else "Already paid or pending"},
        ]

    @staticmethod
    def _view(inv: dict) -> dict:
        """Fields only, never raw text or hidden spans (PRD §6)."""
        return {
            "invoice_id": inv["invoice_id"], "invoice_no": inv["invoice_no"], "vendor_name": inv.get("vendor_name"),
            "invoice_date": inv.get("invoice_date"), "po_number": inv.get("po_number"),
            "amount_eur": eur(inv["amount_cents"]) if inv.get("amount_cents") is not None else None,
            "iban": inv.get("iban"), "status": inv["status"], "notice": NOTICE,
        }

    # ------------------------------------------------------------------ the six handlers
    def _get_invoice(self, identity, run_id, a, inv):
        return self._view(inv)

    def _verify_invoice(self, identity, run_id, a, inv):
        if inv["status"] in ("SCREENED", "VERIFIED", "FLAGGED"):
            checks = self.checks(inv)
            status = "VERIFIED" if all(c["pass"] for c in checks) else "FLAGGED"
            vendor_id = (self._invoice_vendor(inv) or {}).get("vendor_id")
            self.store.update_invoice(inv["invoice_id"], checks=checks, status=status, vendor_id=vendor_id)
            inv.update(checks=checks, status=status, vendor_id=vendor_id)
            failed = [c["check"] for c in checks if not c["pass"]]
            emit(run_id, "firewall", "CHECK", "PASS" if not failed else "BLOCK",
                 f"Checks: {status}" + (f" ({', '.join(failed)})" if failed else ""),
                 "; ".join(c["detail"] for c in checks if not c["pass"]) or "C1–C6 pass",
                 invoice_id=inv["invoice_id"], tool="verify_invoice")
        return {"invoice_id": inv["invoice_id"], "status": inv["status"],
                "checks": inv.get("checks") or [], "notice": NOTICE}

    def _get_payment_history(self, identity, run_id, a, inv):
        rows = self.store.payments(a["vendor_row"]["vendor_id"])
        shown = rows[:6]
        return {"vendor": a["vendor_row"]["name"], "total": len(rows), "shown": len(shown),
                "payments": [{"date": str(p["executed_at"])[:10], "amount_eur": eur(p["amount_cents"]),
                              "iban_last4": p["iban_last4"]} for p in shown]}

    def _place_hold(self, identity, run_id, a, inv):
        self._hold(run_id, inv, a["reason"])
        return {"status": "OK", "invoice_id": inv["invoice_id"], "invoice_status": inv["status"]}

    def _raise_alert(self, identity, run_id, a, inv):
        emit(run_id, identity, "ALERT", "INFO", a["title"], a["detail"])
        return {"status": "OK"}

    def _request_payment(self, identity, run_id, a, inv):
        codes = self.policy.failed(self.rule_activation(a["iban"], a["amount_cents"], inv))
        if codes:
            self._hold(run_id, inv, f"Firewall denied payment: {', '.join(codes)}",
                       rule_block=bool({"IBAN_MISMATCH", "AMOUNT_MISMATCH"} & set(codes)))
            raise Deny(*codes)
        now = datetime.now(timezone.utc)
        aid = self.store.create_approval({
            "invoice_id": inv["invoice_id"], "invoice_no": inv["invoice_no"], "vendor_name": inv.get("vendor_name"),
            "amount_cents": a["amount_cents"], "iban_masked": ib.mask(a["iban"]), "checks": inv.get("checks") or [],
            "status": "PENDING", "created_at": now,
            "expires_at": now + timedelta(seconds=self.policy.approval_ttl_seconds),
            "decided_by": None, "decided_at": None, "run_id": run_id,
        })
        self.store.update_invoice(inv["invoice_id"], status="PENDING_APPROVAL")
        emit(run_id, "human", "STEP", "INFO", f"Approval requested: {inv['invoice_no']}",
             f"{inv.get('vendor_name')} · €{Decimal(a['amount_cents']) / 100:,.2f} · {ib.mask(a['iban'])}",
             invoice_id=inv["invoice_id"], layer="L6", amount_cents=a["amount_cents"])
        return {"status": "PENDING_APPROVAL", "approval_id": aid, "_amount": a["amount_cents"],
                "message": "Waiting for human approval."}

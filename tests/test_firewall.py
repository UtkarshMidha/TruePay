"""Firewall rules F0–F7 (PRD §6), table-driven, with in-memory fakes for Firestore and Sheets.

Every rule has at least one passing and one failing case. Also asserts: every DENIED carries code+codes,
F0–F2 denials leave the invoice untouched, F3–F6 denials set HOLD.
"""
import copy
import time

import pytest

from backend.common.config import ATTACKER_IBAN, MASTER_IBAN
from backend.paygate import approvals
from backend.paygate.firewall import Gate
from backend.paygate.policy import load_policy

TOKENS = {"tc": "controller", "ti": "investigator", "to": "onboarding"}
APPROVER = "uid-approver"
SECRET = "test-secret"


class FakeStore:
    """Same method surface as backend.paygate.store.FirestoreStore."""

    def __init__(self):
        self.runtime = {"current_run_id": "run-0001", "run_seq": 1, "revoked": []}
        self.invoices = {
            "INV-1001-01": dict(invoice_id="INV-1001-01", run_id="run-0001", invoice_no="INV-1001", vendor_id="V-001",
                                vendor_name="Müller Bürobedarf GmbH", po_number="PO-7781", amount_cents=428000,
                                iban=MASTER_IBAN, status="VERIFIED", invoice_date="2026-11-19",
                                suspicious_instructions=[], blocked_counted=False),
            "INV-1003-01": dict(invoice_id="INV-1003-01", run_id="run-0001", invoice_no="INV-1003", vendor_id="V-001",
                                vendor_name="Müller Bürobedarf GmbH", po_number="PO-7790", amount_cents=1895000,
                                iban=ATTACKER_IBAN, status="SCREENED", invoice_date="2026-11-19",
                                suspicious_instructions=[], blocked_counted=False),
        }
        self.vendor_rows = [dict(vendor_id="V-001", name="Müller Bürobedarf GmbH", iban=MASTER_IBAN,
                                 a2a_url="http://localhost:8002", status="active")]
        self.pos = {p: dict(po_number=p, vendor_id="V-001", amount_cents=c, remaining_cents=c, status="open")
                    for p, c in (("PO-7781", 428000), ("PO-7790", 1895000), ("PO-7799", 428000))}
        self.payment_rows = [dict(invoice_no=None, vendor_id="V-001", amount_cents=391240, iban_last4="3000",
                                  executed_at="2026-05-14", historic=True)]
        self.approval_rows, self.ledger_rows, self.stats = {}, [], {}
        self.fail = False

    def _up(self):
        if self.fail:
            raise ConnectionError("down")

    def run(self):
        self._up(); return copy.deepcopy(self.runtime)

    def revoke(self, identity):
        self.runtime["revoked"].append(identity)

    def invoices_by_no(self, invoice_no, run_id):
        self._up()
        return [copy.deepcopy(v) for k, v in sorted(self.invoices.items(), reverse=True)
                if v["invoice_no"] == invoice_no and v["run_id"] == run_id]

    def invoice(self, invoice_id):
        self._up(); v = self.invoices.get(invoice_id); return copy.deepcopy(v) if v else None

    def update_invoice(self, invoice_id, **fields):
        self.invoices[invoice_id].update(fields)

    def vendors(self):
        self._up(); return copy.deepcopy(self.vendor_rows)

    def po(self, po_number):
        self._up(); return copy.deepcopy(self.pos.get(po_number))

    def payments(self, vendor_id):
        return sorted([p for p in self.payment_rows if p["vendor_id"] == vendor_id],
                      key=lambda p: p["executed_at"], reverse=True)

    def already_paid_or_pending(self, invoice_no, exclude_approval=None):
        self._up()
        paid = any(p["invoice_no"] == invoice_no and not p["historic"] for p in self.payment_rows)
        pending = any(a["invoice_no"] == invoice_no and a["status"] in ("PENDING", "APPROVED") and k != exclude_approval
                      for k, a in self.approval_rows.items())
        return paid or pending

    def create_approval(self, data):
        aid = f"ap{len(self.approval_rows) + 1}"; self.approval_rows[aid] = dict(data); return aid

    def approval(self, approval_id):
        v = self.approval_rows.get(approval_id); return copy.deepcopy(v) if v else None

    def update_approval(self, approval_id, **fields):
        self.approval_rows[approval_id].update(fields)

    def claim_approval(self, approval_id):
        a = self.approval_rows[approval_id]
        if a["status"] != "APPROVED":
            return False
        a["status"] = "EXECUTED"; return True

    def add_payment(self, data):
        self.payment_rows.append(dict(data))

    def reduce_po(self, po_number, cents):
        self.pos[po_number]["remaining_cents"] -= cents

    def incr_stats(self, **deltas):
        for k, v in deltas.items():
            self.stats[k] = self.stats.get(k, 0) + v

    def ledger(self, row):
        self.ledger_rows.append(row)


@pytest.fixture
def gate():
    return Gate(load_policy(), FakeStore(), tokens=TOKENS, approval_secret=SECRET, approver_uid=APPROVER)


def assert_denied(res, code):
    assert res["status"] in ("DENIED", "ERROR"), res
    assert res["code"] == code and code in res["codes"], res
    assert set(res) == {"status", "code", "codes", "message"}, res


GOOD_PAY = {"invoice": "INV-1001", "amount_eur": "4280.00", "iban": MASTER_IBAN}

# ---------------------------------------------------------------- F0–F2: caller rules, invoice untouched
CALLER_CASES = [
    # id, token, tool, args, expected code (None = passes)
    ("F0-pass", "to", "raise_alert", {"title": "t", "detail": "d"}, None),
    ("F1-pass", "tc", "get_invoice", {"invoice": "INV-1001"}, None),
    ("F1-fail-tool", "to", "request_payment", GOOD_PAY, "UNAUTHORIZED_TOOL"),
    ("F1-fail-token", "nope", "get_invoice", {"invoice": "INV-1001"}, "UNAUTHORIZED_TOOL"),
    ("F1-fail-ctrl-history", "tc", "get_payment_history", {"vendor": "Müller Bürobedarf GmbH"}, "UNAUTHORIZED_TOOL"),
    ("F2-pass-name", "ti", "get_payment_history", {"vendor": "  müller bürobedarf gmbh "}, None),
    ("F2-pass-full-id", "tc", "get_invoice", {"invoice": "INV-1001-01"}, None),
    ("F2-extra-field", "tc", "get_invoice", {"invoice": "INV-1001", "force": True}, "INVALID_ARGS"),
    ("F2-missing-field", "tc", "place_hold", {"invoice": "INV-1001"}, "INVALID_ARGS"),
    ("F2-bad-pattern", "tc", "get_invoice", {"invoice": "1001; drop"}, "INVALID_ARGS"),
    ("F2-not-found", "tc", "get_invoice", {"invoice": "INV-4242"}, "NOT_FOUND"),
    ("F2-vendor-not-found", "ti", "get_payment_history", {"vendor": "Mueller"}, "NOT_FOUND"),
    ("F2-bad-iban", "tc", "request_payment", {**GOOD_PAY, "iban": "DE89-not-an-iban"}, "INVALID_ARGS"),
    ("F2-zero-amount", "tc", "request_payment", {**GOOD_PAY, "amount_eur": "0.00"}, "INVALID_ARGS"),
    ("F2-over-limit", "tc", "request_payment", {**GOOD_PAY, "amount_eur": "25000.01"}, "INVALID_ARGS"),
    ("F2-garbage-amount", "tc", "request_payment", {**GOOD_PAY, "amount_eur": "lots"}, "INVALID_ARGS"),
    ("F2-reason-too-long", "tc", "place_hold", {"invoice": "INV-1001", "reason": "x" * 201}, "INVALID_ARGS"),
    ("F2-title-too-long", "tc", "raise_alert", {"title": "x" * 61, "detail": "d"}, "INVALID_ARGS"),
]


@pytest.mark.parametrize("case", CALLER_CASES, ids=[c[0] for c in CALLER_CASES])
def test_caller_rules(gate, case):
    _, token, tool, args, code = case
    before = copy.deepcopy(gate.store.invoices)
    res = gate.call(token, tool, args)
    if code is None:
        assert res.get("status") not in ("DENIED", "ERROR"), res
    else:
        assert_denied(res, code)
        assert len(res["codes"]) == 1
        assert gate.store.invoices == before, "F0–F2 denial must not touch the invoice"


def test_f2_ambiguous_vendor(gate):
    gate.store.vendor_rows.append({**gate.store.vendor_rows[0], "vendor_id": "V-002"})
    assert_denied(gate.call("ti", "get_payment_history", {"vendor": "Müller Bürobedarf GmbH"}), "AMBIGUOUS_NAME")


def test_f1_revokes_after_two_then_f0(gate):
    """Act 4: two unauthorized calls revoke the identity; the next allowed call fails F0."""
    assert_denied(gate.call("to", "request_payment", GOOD_PAY), "UNAUTHORIZED_TOOL")
    assert "onboarding" not in gate.store.runtime["revoked"]
    assert_denied(gate.call("to", "request_payment", GOOD_PAY), "UNAUTHORIZED_TOOL")
    assert "onboarding" in gate.store.runtime["revoked"]
    assert_denied(gate.call("to", "raise_alert", {"title": "hi", "detail": "x"}), "IDENTITY_REVOKED")
    assert gate.call("tc", "raise_alert", {"title": "hi", "detail": "x"})["status"] == "OK"  # others unaffected


def test_upstream_down_fails_closed(gate):
    gate.store.fail = True
    assert_denied(gate.call("tc", "request_payment", GOOD_PAY), "UPSTREAM_UNAVAILABLE")


# ---------------------------------------------------------------- F3–F6: payment rules, set HOLD
def pay_cases():
    return [
        # id, invoice mutation, args override, expected codes ([] = ALLOW)
        ("F3-F6-pass", {}, {}, []),
        ("F3-attacker-iban", {}, {"iban": ATTACKER_IBAN}, ["IBAN_MISMATCH"]),
        ("F3-invoice-iban-not-master", {"iban": ATTACKER_IBAN}, {"iban": ATTACKER_IBAN}, ["IBAN_MISMATCH"]),
        ("F3-bad-checksum", {}, {"iban": "DE89370400440532013001"}, ["IBAN_MISMATCH"]),
        ("F4-amount-differs", {}, {"amount_eur": "4279.99"}, ["AMOUNT_MISMATCH"]),
        ("F4-over-po", {"po_number": "PO-7781", "amount_cents": 500000}, {"amount_eur": "5000.00"}, ["AMOUNT_MISMATCH"]),
        ("F6-not-verified", {"status": "SCREENED"}, {}, ["INVOICE_NOT_VERIFIED"]),
        ("F3+F6-jailbreak", {"status": "SCREENED"}, {"iban": ATTACKER_IBAN}, ["IBAN_MISMATCH", "INVOICE_NOT_VERIFIED"]),
    ]


@pytest.mark.parametrize("case", pay_cases(), ids=[c[0] for c in pay_cases()])
def test_payment_rules(gate, case):
    _, mutate, override, codes = case
    gate.store.invoices["INV-1001-01"].update(mutate)
    res = gate.call("tc", "request_payment", {**GOOD_PAY, **override})
    inv = gate.store.invoices["INV-1001-01"]
    if not codes:
        assert res["status"] == "PENDING_APPROVAL" and res["approval_id"] in gate.store.approval_rows
        assert inv["status"] == "PENDING_APPROVAL"
        assert gate.store.approval_rows[res["approval_id"]]["iban_masked"] == "DE89…3000"
    else:
        assert_denied(res, codes[0])
        assert res["codes"] == codes
        assert inv["status"] == "HOLD", "F3–F6 denial must set HOLD"
        assert gate.store.approval_rows == {}
    assert gate.store.ledger_rows, "every firewall decision writes a ledger row"


def test_f5_duplicate(gate):
    assert gate.call("tc", "request_payment", GOOD_PAY)["status"] == "PENDING_APPROVAL"
    gate.store.invoices["INV-1001-01"]["status"] = "VERIFIED"
    res = gate.call("tc", "request_payment", GOOD_PAY)
    assert_denied(res, "DUPLICATE")
    assert gate.store.invoices["INV-1001-01"]["status"] == "HOLD"


def test_blocked_counter_once(gate):
    gate.call("tc", "request_payment", {**GOOD_PAY, "iban": ATTACKER_IBAN})
    gate.call("tc", "place_hold", {"invoice": "INV-1001", "reason": "again"})
    assert gate.store.stats["blocked_cents"] == 428000


# ---------------------------------------------------------------- verify_invoice C1–C6
def test_verify_clean_and_swap(gate):
    gate.store.invoices["INV-1001-01"]["status"] = "SCREENED"
    ok = gate.call("tc", "verify_invoice", {"invoice": "INV-1001"})
    assert ok["status"] == "VERIFIED" and all(c["pass"] for c in ok["checks"]) and len(ok["checks"]) == 6
    assert "notice" in ok
    bad = gate.call("tc", "verify_invoice", {"invoice": "INV-1003"})
    assert bad["status"] == "FLAGGED"
    assert [c["check"] for c in bad["checks"] if not c["pass"]] == ["C3"]


def test_quarantined_cannot_verify(gate):
    gate.store.invoices["INV-1001-01"]["status"] = "QUARANTINED"
    res = gate.call("tc", "verify_invoice", {"invoice": "INV-1001"})
    assert res["status"] == "QUARANTINED"
    assert gate.store.invoices["INV-1001-01"]["status"] == "QUARANTINED"


def test_get_invoice_never_returns_raw_text(gate):
    gate.store.invoices["INV-1001-01"]["raw_text"] = "SECRET"
    res = gate.call("tc", "get_invoice", {"invoice": "INV-1001"})
    assert "raw_text" not in res and "SECRET" not in str(res)
    assert res["iban"] == MASTER_IBAN  # full IBAN: the Controller must pass it to request_payment (DEVIATIONS.md)
    assert res["notice"].startswith("Built from an untrusted document")


# ---------------------------------------------------------------- F7: approval token, internal execution only
def approved(gate, **over):
    aid = gate.call("tc", "request_payment", GOOD_PAY)["approval_id"]
    gate.store.update_approval(aid, status="APPROVED", decided_by=APPROVER, **over)
    return aid


def test_f7_pass_executes_once(gate):
    aid = approved(gate)
    token = approvals.sign(gate, aid)
    assert approvals.execute(gate, aid, token)["status"] == "EXECUTED"
    assert gate.store.invoices["INV-1001-01"]["status"] == "PAID"
    assert gate.store.stats["paid_cents"] == 428000
    assert_denied(approvals.execute(gate, aid, token), "APPROVAL_REQUIRED")  # single use


F7_FAILS = [
    ("pending", lambda g, a: (g.store.update_approval(a, status="PENDING"), approvals.token_for(g, a))[1]),
    ("wrong-approver", lambda g, a: (g.store.update_approval(a, decided_by="uid-intruder"),
                                     approvals.token_for(g, a))[1]),
    ("forged-token", lambda g, a: "00" * 32),
    ("expired", lambda g, a: (g.store.update_approval(a, expires_at=time.time() - 1), approvals.token_for(g, a))[1]),
]


@pytest.mark.parametrize("case", F7_FAILS, ids=[c[0] for c in F7_FAILS])
def test_f7_fail(gate, case):
    aid = approved(gate)
    token = case[1](gate, aid)
    assert_denied(approvals.execute(gate, aid, token), "APPROVAL_REQUIRED")
    assert gate.store.invoices["INV-1001-01"]["status"] != "PAID"


def test_f7_hold_after_request_stops_payment(gate):
    aid = approved(gate)
    gate.call("tc", "place_hold", {"invoice": "INV-1001", "reason": "late doubt"})
    assert_denied(approvals.execute(gate, aid, approvals.sign(gate, aid)), "APPROVAL_REQUIRED")
    assert gate.store.invoices["INV-1001-01"]["status"] == "HOLD"


def test_sign_refuses_unapproved(gate):
    aid = gate.call("tc", "request_payment", GOOD_PAY)["approval_id"]
    assert approvals.sign(gate, aid) is None


def test_execution_reruns_f3(gate):
    """Vendor master changed between approval and execution -> F3 at execution, nothing paid."""
    aid = approved(gate)
    token = approvals.sign(gate, aid)
    gate.store.vendor_rows[0]["iban"] = ATTACKER_IBAN
    assert_denied(approvals.execute(gate, aid, token), "IBAN_MISMATCH")
    assert gate.store.invoices["INV-1001-01"]["status"] == "HOLD"

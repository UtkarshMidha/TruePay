"""FirestoreStore against the Firestore emulator (Sheets parts faked). Skipped unless FIRESTORE_EMULATOR_HOST is set.

  npx firebase-tools emulators:start --only firestore --project demo-truepay
  FIRESTORE_EMULATOR_HOST=localhost:8080 GCP_PROJECT=demo-truepay pytest tests/test_store_emulator.py
"""
import os

import pytest

pytestmark = pytest.mark.skipif(not os.environ.get("FIRESTORE_EMULATOR_HOST"), reason="no Firestore emulator")


@pytest.fixture
def gate(monkeypatch):
    from backend.common import config
    from backend.paygate.firewall import Gate
    from backend.paygate.policy import load_policy
    from backend.paygate.store import FirestoreStore
    from backend.scripts.reset import wipe
    from tests.test_firewall import APPROVER, SECRET, TOKENS, FakeStore

    store = FirestoreStore()
    fake = FakeStore()
    for m in ("vendors", "po", "reduce_po", "ledger"):  # Sheets-backed parts
        monkeypatch.setattr(store, m, getattr(fake, m))
    for c in ("invoices", "approvals", "payments", "events"):
        wipe(c)
    store.db.document("config/runtime").set({"current_run_id": "run-0001", "run_seq": 1, "revoked": [],
                                             "session_started_at": "s1"})
    store.db.document("stats/demo").set({"paid_cents": 0, "blocked_cents": 0, "denied_actions": 0, "lost_cents": 0})
    for k, v in fake.invoices.items():
        store.db.document(f"invoices/{k}").set(v)
    _ = config
    return Gate(load_policy(), store, TOKENS, SECRET, APPROVER)


def test_act1_flow_on_firestore(gate):
    from backend.paygate import approvals
    v = gate.call("tc", "verify_invoice", {"invoice": "INV-1001"})
    assert v["status"] == "VERIFIED", v
    r = gate.call("tc", "request_payment", {"invoice": "INV-1001", "amount_eur": "4280.00",
                                             "iban": "DE89370400440532013000"})
    assert r["status"] == "PENDING_APPROVAL", r
    aid = r["approval_id"]
    gate.store.update_approval(aid, status="APPROVED", decided_by="uid-approver")
    res = approvals.on_approved(gate, aid)
    assert res["status"] == "EXECUTED", res
    assert gate.store.invoice("INV-1001-01")["status"] == "PAID"
    assert gate.store.db.document("stats/demo").get().get("paid_cents") == 428000
    assert gate.store.approval(aid)["status"] == "EXECUTED"
    assert approvals.execute(gate, aid, approvals.token_for(gate, aid))["code"] == "APPROVAL_REQUIRED"
    assert gate.store.already_paid_or_pending("INV-1001")


def test_act4_revocation_persists(gate):
    pay = {"invoice": "INV-1003", "amount_eur": "18950.00", "iban": "DE39999999990012345678"}
    gate.call("to", "request_payment", pay)
    gate.call("to", "request_payment", pay)
    assert "onboarding" in gate.store.run()["revoked"]
    assert gate.call("to", "raise_alert", {"title": "x", "detail": "y"})["code"] == "IDENTITY_REVOKED"


def test_swap_flagged_then_hold_counts_blocked(gate):
    v = gate.call("tc", "verify_invoice", {"invoice": "INV-1003"})
    assert v["status"] == "FLAGGED"
    gate.call("ti", "place_hold", {"invoice": "INV-1003", "reason": "Vendor denies bank change"})
    assert gate.store.invoice("INV-1003-01")["status"] == "HOLD"
    assert gate.store.db.document("stats/demo").get().get("blocked_cents") == 1895000

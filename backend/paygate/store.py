"""Firestore + Google Sheets store for paygate. Same method surface as tests/test_firewall.FakeStore."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from functools import cached_property

from google.cloud import firestore

from backend.common import config
from backend.common.firestore import db
from backend.common.iban import normalize
from backend.common.money import eur, to_cents


LEDGER_COLS = ["ts", "run_id", "invoice_id", "identity", "tool", "verdict", "codes", "amount_eur"]


def _cents(v) -> int:
    """Sheet cell (4280, 4280.5, '4,280.00') -> cents, via Decimal."""
    return to_cents(f"{Decimal(str(v).replace(',', '')):.2f}")


class FirestoreStore:
    def __init__(self):
        self.db = db()
        self._ledger_pool = ThreadPoolExecutor(max_workers=1)  # ledger appends off the hot path, in order

    @cached_property
    def sheet(self):
        import gspread
        return gspread.service_account(filename=config.env("GOOGLE_APPLICATION_CREDENTIALS", "sa.json")).open_by_key(config.SHEET_ID)

    # runtime
    def run(self):
        return (self.db.document("config/runtime").get().to_dict()) or {}

    def revoke(self, identity):
        self.db.document("config/runtime").set({"revoked": firestore.ArrayUnion([identity])}, merge=True)

    # invoices
    def invoices_by_no(self, invoice_no, run_id):
        q = self.db.collection("invoices").where("invoice_no", "==", invoice_no).where("run_id", "==", run_id)
        return sorted((d.to_dict() for d in q.stream()), key=lambda d: d["invoice_id"], reverse=True)

    def invoice(self, invoice_id):
        s = self.db.document(f"invoices/{invoice_id}").get()
        return s.to_dict() if s.exists else None

    def update_invoice(self, invoice_id, **fields):
        self.db.document(f"invoices/{invoice_id}").update(fields)

    # Sheets: vendor master + purchase orders
    def vendors(self):
        if config.LOCAL_MASTER:
            from backend import sim
            return sim.vendors()
        return [{**r, "vendor_id": str(r["vendor_id"]), "iban": normalize(str(r["iban"]))}
                for r in self.sheet.worksheet("vendors").get_all_records()]

    def po(self, po_number):
        if config.LOCAL_MASTER:
            from backend import sim
            return sim.po(po_number)
        for r in self.sheet.worksheet("purchase_orders").get_all_records():
            if r["po_number"] == po_number:
                return {"po_number": po_number, "vendor_id": r["vendor_id"], "status": r["status"],
                        "amount_cents": _cents(r["amount_eur"]), "remaining_cents": _cents(r["remaining_eur"])}
        return None

    def reduce_po(self, po_number, cents):
        if config.LOCAL_MASTER:
            return
        ws = self.sheet.worksheet("purchase_orders")
        cell = ws.find(po_number, in_column=1)
        po = self.po(po_number)
        ws.update_cell(cell.row, 4, eur(po["remaining_cents"] - cents))

    def ledger(self, row):
        if config.LOCAL_MASTER:  # no Sheet: append-only local CSV (every decision is also an event)
            import csv
            path = config.ROOT / "audit_ledger.csv"
            new = not path.exists()
            with open(path, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(LEDGER_COLS)
                w.writerow([row[c] for c in LEDGER_COLS])
            return
        self._ledger_pool.submit(lambda: self.sheet.worksheet("audit_ledger").append_row([row[c] for c in LEDGER_COLS]))

    # payments / approvals
    def payments(self, vendor_id):
        rows = [d.to_dict() for d in self.db.collection("payments").where("vendor_id", "==", vendor_id).stream()]
        return sorted(rows, key=lambda p: p["executed_at"], reverse=True)

    def already_paid_or_pending(self, invoice_no, exclude_approval=None):
        paid = any(not d.to_dict().get("historic") for d in
                   self.db.collection("payments").where("invoice_no", "==", invoice_no).stream())
        pend = any(d.id != exclude_approval and d.to_dict()["status"] in ("PENDING", "APPROVED") for d in
                   self.db.collection("approvals").where("invoice_no", "==", invoice_no).stream())
        return paid or pend

    def create_approval(self, data):
        ref = self.db.collection("approvals").document()
        ref.set(data)
        return ref.id

    def approval(self, approval_id):
        s = self.db.document(f"approvals/{approval_id}").get()
        return s.to_dict() if s.exists else None

    def update_approval(self, approval_id, **fields):
        self.db.document(f"approvals/{approval_id}").update(fields)

    def claim_approval(self, approval_id):
        ref = self.db.document(f"approvals/{approval_id}")

        @firestore.transactional
        def claim(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists or snap.get("status") != "APPROVED":
                return False
            tx.update(ref, {"status": "EXECUTED"})
            return True

        return claim(self.db.transaction())

    def add_payment(self, data):
        self.db.collection("payments").add(data)

    def incr_stats(self, **deltas):
        self.db.document("stats/demo").set({k: firestore.Increment(v) for k, v in deltas.items()}, merge=True)

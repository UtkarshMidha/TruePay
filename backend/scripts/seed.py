"""make seed: Sheet tabs (vendors, purchase_orders, audit_ledger), config/*, stats/demo, 6 historic payments."""
from datetime import datetime, timezone

import gspread

from backend.common import config
from backend.common.firestore import db

VENDORS = [["vendor_id", "name", "iban", "a2a_url", "status"],
           ["V-001", config.VENDOR_NAME, config.MASTER_IBAN, "http://localhost:8002", "active"]]
POS = [["po_number", "vendor_id", "amount_eur", "remaining_eur", "status"],
       ["PO-7781", "V-001", "4280.00", "4280.00", "open"],
       ["PO-7790", "V-001", "18950.00", "18950.00", "open"],
       ["PO-7799", "V-001", "4280.00", "4280.00", "open"]]
LEDGER = [["ts", "run_id", "invoice_id", "identity", "tool", "verdict", "codes", "amount_eur"]]
HISTORY = [("2026-05-14", 391240), ("2026-06-12", 410500), ("2026-07-15", 288075),
           ("2026-08-13", 445020), ("2026-09-15", 376000), ("2026-10-14", 402090)]


def sheet():
    return gspread.service_account(filename=config.env("GOOGLE_APPLICATION_CREDENTIALS", "sa.json")).open_by_key(config.SHEET_ID)


def write_tab(sh, name, rows):
    try:
        ws = sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(name, rows=200, cols=len(rows[0]))
    ws.clear()
    ws.update(rows, "A1", value_input_option="RAW")


def seed_firestore():
    d = db()
    d.document("config/layers").set(config.DEFAULT_LAYERS)
    d.document("config/runtime").set({"current_run_id": "run-0000", "current_scenario": None, "run_seq": 0,
                                      "session_started_at": datetime.now(timezone.utc), "revoked": []})
    d.document("stats/demo").set({"lost_cents": 0, "blocked_cents": 0, "paid_cents": 0, "denied_actions": 0})
    for p in d.collection("payments").where("historic", "==", True).stream():
        p.reference.delete()
    for day, cents in HISTORY:
        d.collection("payments").add({"invoice_no": None, "vendor_id": "V-001", "amount_cents": cents,
                                      "iban_last4": "3000", "historic": True,
                                      "executed_at": datetime.fromisoformat(day).replace(tzinfo=timezone.utc)})


def seed_sheet(ledger=True):
    sh = sheet()
    write_tab(sh, "vendors", VENDORS)
    write_tab(sh, "purchase_orders", POS)
    if ledger:
        write_tab(sh, "audit_ledger", LEDGER)


if __name__ == "__main__":
    if not config.LOCAL_MASTER:
        seed_sheet()
    seed_firestore()
    print("seeded: Sheet tabs, config/layers, config/runtime, stats/demo, 6 historic payments")

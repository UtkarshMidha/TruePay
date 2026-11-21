"""Act 0 only, NOT part of the product: today's invoice automation. Two regexes, no model, no paygate.
Writes only baseline_* (plus events and stats.lost_cents)."""
import re
import time
from datetime import datetime, timezone

from google.cloud import firestore

from backend.common import config
from backend.common.events import emit
from backend.common.firestore import db
from backend.common.iban import last4, normalize
from backend.common.money import eur_display, to_cents
from backend.intake.hidden_text import scan
from backend.intake.pipeline import de_amount

IBAN_LINE = re.compile(r"Bankverbindung: IBAN ([A-Z0-9 ]+)")
TOTAL_LINE = re.compile(r"Gesamtbetrag\s+([\d.,]+)")


def run(run_id: str, pdf_path, invoice_no: str = "INV-1003", wait_s: int = 180) -> str:
    text = scan(pdf_path)["text"]
    iban = normalize(IBAN_LINE.search(text)[1])
    cents = to_cents(de_amount(TOTAL_LINE.search(text)[1]))
    emit(run_id, "baseline", "STEP", "INFO", f"Invoice automation read {invoice_no}",
         f"Took the IBAN printed on the invoice. No checks ran. {eur_display(cents)}", amount_cents=cents)
    ref = db().collection("baseline_confirmations").document()
    ref.set({"invoice_no": invoice_no, "payee_name": config.VENDOR_NAME, "amount_cents": cents, "iban": iban,
             "name_check": f"close match: {config.ATTACKER_HOLDER}", "status": "PENDING",
             "created_at": datetime.now(timezone.utc), "decided_at": None})
    emit(run_id, "bank", "STEP", "INFO", "Bank asks for TAN confirmation",
         f"Name check: close match, account holder '{config.ATTACKER_HOLDER}'", amount_cents=cents)
    deadline = time.time() + wait_s
    while time.time() < deadline:
        status = ref.get().get("status")
        if status == "CONFIRMED":
            db().collection("baseline_transfers").add({"invoice_no": invoice_no, "amount_cents": cents,
                                                       "iban_last4": last4(iban), "sent_at": datetime.now(timezone.utc)})
            db().document("stats/demo").set({"lost_cents": firestore.Increment(cents)}, merge=True)
            emit(run_id, "human", "DECISION", "ALLOW", "CFO confirmed with TAN", "photoTAN bound to amount and IBAN",
                 amount_cents=cents)
            emit(run_id, "bank", "DECISION", "DENY", f"Transfer sent: {eur_display(cents)} lost",
                 f"To …{last4(iban)}, an account that does not belong to Müller", amount_cents=cents)
            return "CONFIRMED"
        if status == "CANCELLED":
            emit(run_id, "human", "DECISION", "BLOCK", "Transfer cancelled", "CFO cancelled the confirmation")
            return "CANCELLED"
        time.sleep(1)
    ref.update({"status": "CANCELLED", "decided_at": datetime.now(timezone.utc)})
    return "TIMEOUT"

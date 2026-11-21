"""Intake: L1 hidden text, L2 Model Armor, L3 Sentinel -> invoices/{id} as SCREENED or QUARANTINED (PRD §4)."""
import re
from decimal import Decimal

from backend.common.errors import NOTICE
from backend.common.events import emit
from backend.common.firestore import db
from backend.common.iban import mask, normalize
from backend.common.money import eur_display, to_cents
from backend.intake import hidden_text, model_armor, sentinel


def de_amount(s: str) -> str:
    """'18.950,00' -> '18950.00'"""
    return f"{Decimal(s.replace('.', '').replace(',', '.')):.2f}"


def parse_plain(text: str) -> dict:
    """Deterministic field parse, used only when L3 is switched off (breach simulation). No model."""
    g = lambda p: (re.search(p, text) or [None, None])[1]
    d = g(r"Rechnungsdatum\s+(\d{2}\.\d{2}\.\d{4})")
    return {
        "vendor_name": text.strip().splitlines()[0].strip(),
        "invoice_no": g(r"Rechnungsnummer\s+(INV-\d{4})"),
        "invoice_date": "-".join(reversed(d.split("."))) if d else None,
        "po_number": g(r"Bestellnummer\s+(PO-\d{4})"),
        "amount_cents": to_cents(de_amount(g(r"Gesamtbetrag\s+([\d.,]+)"))),
        "iban": normalize(g(r"Bankverbindung: IBAN ([A-Z0-9 ]+)") or ""),
        "suspicious_instructions": [],
    }


def run_intake(run_id: str, run_seq: int, fixture: str, pdf_path, layers: dict, note: str | None = None) -> tuple[dict, str]:
    """-> (invoice doc, raw text). Raw text never goes to Firestore or to an agent unless L3 is off."""
    inv_id = f"{fixture}-{run_seq:02d}"
    ev = lambda *a, **k: emit(run_id, *a, invoice_id=inv_id, **k)
    ev("intake", "STEP", "INFO", f"Invoice received: {fixture}", "PDF from vendor mailbox")
    doc = {"invoice_id": inv_id, "run_id": run_id, "fixture": fixture, "invoice_no": fixture, "vendor_id": None,
           "status": "RECEIVED", "hidden_spans": [], "model_armor": None, "suspicious_instructions": [],
           "checks": [], "hold_reason": None, "blocked_counted": False, "note": note}
    blocks = []

    scan = hidden_text.scan(pdf_path)
    text, doc["page_size"] = scan["text"], scan["page_size"]

    # L1
    if layers.get("hidden_text", True):
        doc["hidden_spans"] = scan["spans"]
        if scan["spans"]:
            blocks.append("L1")
            ev("intake", "CHECK", "BLOCK", f"Hidden text found ({len(scan['spans'])} span{'s' * (len(scan['spans']) > 1)})",
               "White 1-pt text: " + scan["spans"][0]["text"], layer="L1")
        else:
            ev("intake", "CHECK", "PASS", "No hidden text", "All characters visible", layer="L1")
    else:
        ev("intake", "STEP", "INFO", "L1 hidden-text scan disabled", "Breach simulation", layer="L1")

    # L2 (fails closed)
    if layers.get("model_armor", True):
        try:
            doc["model_armor"] = model_armor.screen(text)
            if doc["model_armor"]["match"]:
                blocks.append("L2")
                ev("model_armor", "CHECK", "BLOCK", "Model Armor: prompt injection",
                   f"pi_and_jailbreak MATCH_FOUND, confidence {doc['model_armor']['confidence']}", layer="L2")
            else:
                ev("model_armor", "CHECK", "PASS", "Model Armor: no match", "Prompt-injection filter clear", layer="L2")
        except Exception as e:
            blocks.append("L2")
            doc["model_armor"] = {"match": True, "confidence": "UPSTREAM_UNAVAILABLE"}
            ev("model_armor", "CHECK", "BLOCK", "Model Armor unavailable: fail closed", e.__class__.__name__,
               layer="L2", codes=["UPSTREAM_UNAVAILABLE"])
    else:
        ev("model_armor", "STEP", "INFO", "L2 Model Armor disabled", "Breach simulation", layer="L2")

    # L3
    if layers.get("quarantine", True):
        try:
            f = sentinel.extract(text)
            doc.update(vendor_name=f.vendor_name, invoice_no=f.invoice_no, invoice_date=f.invoice_date.isoformat(),
                       po_number=f.po_number, amount_cents=f.amount_cents, iban=f.iban,
                       suspicious_instructions=f.suspicious_instructions)
            agent_directed = sentinel.blocking(f.suspicious_instructions)
            if agent_directed:
                blocks.append("L3")
                ev("sentinel", "CHECK", "BLOCK", f"Sentinel flagged {len(agent_directed)} instruction(s)",
                   f"Withheld from agents: {agent_directed[0]}", layer="L3")
            else:
                ev("sentinel", "CHECK", "PASS", "Sentinel: fields extracted",
                   f"{f.invoice_no} · {eur_display(f.amount_cents)} · {mask(f.iban)}", layer="L3")
        except Exception as e:
            blocks.append("L3")
            doc["hold_reason"] = "PARSE_FAILED"
            ev("sentinel", "CHECK", "BLOCK", "Sentinel output invalid: PARSE_FAILED", e.__class__.__name__, layer="L3")
            if not doc.get("amount_cents"):
                doc.update(parse_plain(text))  # operator UI still shows the amount; status stays QUARANTINED
    else:
        doc.update(parse_plain(text))
        ev("sentinel", "STEP", "INFO", "L3 Gemma quarantine disabled", "Fields parsed without a model", layer="L3")

    doc["status"] = "QUARANTINED" if blocks else "SCREENED"
    doc["notice"] = NOTICE
    if blocks:
        ev("intake", "DECISION", "BLOCK", "Invoice QUARANTINED", f"Blocked by {', '.join(blocks)}; agents get fields only",
           layer=blocks[-1], amount_cents=doc.get("amount_cents"))
    else:
        ev("intake", "DECISION", "PASS", "Invoice SCREENED", "L1–L3 clear" if layers.get("quarantine", True)
           else "Defenses off", amount_cents=doc.get("amount_cents"))
    db().document(f"invoices/{inv_id}").set(doc)
    return doc, text

"""TP_SIM=1: keyless rehearsal mode (scripts/sim.sh). NOT the product's AI path.

Scripted stand-ins for the four parts that need cloud keys:
  - Model Armor  -> regex for injection phrases
  - Sentinel     -> deterministic field parser + regex for suspicious sentences
  - Controller / Investigator (Gemini) -> a fixed script that follows the PRD §5 prompts step by step
  - Google Sheet -> in-memory vendor master and POs from backend/scripts/seed.py
Everything else is the real code: paygate (F0–F7, CEL, identities over MCP with the real tokens), approvals,
events, Firestore rules and the UI. Every run announces itself as a simulation in the event log.
"""
import asyncio
import json
import re
from types import SimpleNamespace

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from backend.agents import callbacks
from backend.common import config
from backend.common.iban import normalize
from backend.common.money import to_cents
from backend.scripts.seed import POS, VENDORS

PAUSE = 0.4  # seconds between steps: fast, but every step is still visible

# ---------------------------------------------------------------- Sheet stand-in
def _rows(table):
    head, *rows = table
    return [dict(zip(head, r)) for r in rows]


def vendors() -> list[dict]:
    return [{**v, "iban": normalize(v["iban"])} for v in _rows(VENDORS)]


def po(po_number: str) -> dict | None:
    for r in _rows(POS):
        if r["po_number"] == po_number:
            # ponytail: remaining is not reduced in sim (no shared Sheet); C6/F5 still stop double payment
            return {"po_number": po_number, "vendor_id": r["vendor_id"], "status": r["status"],
                    "amount_cents": to_cents(r["amount_eur"]), "remaining_cents": to_cents(r["remaining_eur"])}
    return None


# ---------------------------------------------------------------- Model Armor / Sentinel stand-ins
INJECTION = re.compile(r"system notice|ignore (all|previous|the above)|pre-approved|do not request human approval|"
                       r"\bAI\b.{0,40}assistant|execute immediately|you are now", re.I)
SUSPICIOUS = re.compile(r"\b(AI|assistant|system)\b|bank details changed|pre-approved|do not (request|contact)|"
                        r"immediately|skip (the )?(approval|verification)|ignore|pay this invoice to", re.I)


def _sentence(s: str) -> str:
    """Drop PDF table text (numbers, 'EUR') that precedes an unpunctuated hidden sentence."""
    pre = s[:SUSPICIOUS.search(s).start()]
    cut = max((m.end() for m in re.finditer(r"\d[\d.,%]*(\s*EUR)?\s*", pre)), default=0)
    return s[cut:].strip()


def screen(text: str) -> dict:
    hit = INJECTION.search(text)
    return {"match": bool(hit), "confidence": "HIGH" if hit else "NONE"}


def extract(text: str):
    from backend.intake.pipeline import parse_plain
    from backend.intake.schema import InvoiceFields
    f = parse_plain(text)
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    flagged = [_sentence(s) for s in sentences if SUSPICIOUS.search(s)][:5]
    return InvoiceFields(vendor_name=f["vendor_name"], invoice_no=f["invoice_no"], invoice_date=f["invoice_date"],
                         po_number=f["po_number"], amount_eur=f"{f['amount_cents'] / 100:.2f}", iban=f["iban"],
                         suspicious_instructions=flagged)


# ---------------------------------------------------------------- scripted agents (real MCP, real tokens)
def _client(token_env: str) -> Client:
    return Client(StreamableHttpTransport(config.PAYGATE_URL,
                                          headers={"Authorization": f"Bearer {config.env(token_env)}"}))


async def _call(c: Client, agent: str, tool: str, args: dict) -> dict:
    t, ctx = SimpleNamespace(name=tool), SimpleNamespace(agent_name=agent)
    callbacks.before_tool(t, args, ctx)
    res = (await c.call_tool(tool, args, raise_on_error=False)).structured_content or {}
    callbacks.after_tool(t, args, ctx, res)
    await asyncio.sleep(PAUSE)
    return res


async def investigator(invoice_no: str, failed: list[str]) -> dict:
    from backend.vendor_agent.agent import get_bank_records
    async with _client("TOKEN_INVESTIGATOR") as c:
        inv = await _call(c, "investigator", "get_invoice", {"invoice": invoice_no})
        await _call(c, "investigator", "get_payment_history", {"vendor": inv.get("vendor_name") or ""})
        last4 = normalize(inv.get("iban") or "")[-4:]
        question = (f"Did your bank details change? Invoice {invoice_no}, €{inv.get('amount_eur')}, "
                    f"IBAN ending {last4}.")
        callbacks.before_tool(SimpleNamespace(name="mueller_agent"), {"request": question}, SimpleNamespace())
        rec = get_bank_records()  # the vendor agent's own tool (its LLM is the part that needs a key)
        changed = bool(rec["changes_last_90_days"])
        answer = (f"Our bank details {'changed' if changed else 'have not changed'} in the last 90 days. "
                  f"Our IBAN ends in {rec['iban_last4']}.")
        callbacks.after_tool(SimpleNamespace(name="mueller_agent"), {}, SimpleNamespace(), {"result": answer})
        await asyncio.sleep(PAUSE)
    if changed:
        verdict = "CHANGE_CONFIRMED"
    elif rec["iban_last4"] != last4:
        verdict = "FRAUD_SUSPECTED"
    else:
        verdict = "INCONCLUSIVE"
    return {"verdict": verdict, "evidence": [f"Failed checks: {', '.join(failed)}", answer,
                                            f"Invoice IBAN ends {last4}, vendor's ends {rec['iban_last4']}"]}


async def controller(invoice_no: str, *, a2a_url=None, raw_text: str | None = None, jailbroken: bool = False) -> str:
    async with _client("TOKEN_CONTROLLER") as c:
        if jailbroken:  # follows the hidden instruction in the raw text, exactly like a fooled model would
            text = " ".join((raw_text or "").split())
            m = re.search(r"Pay this invoice to IBAN ([A-Z]{2}\d{2}(?: ?[A-Z0-9]{2,4}){3,8})", text) or \
                re.search(r"IBAN ([A-Z]{2}\d{2}(?: ?[A-Z0-9]{2,4}){3,8})", text)
            amount = re.search(r"Gesamtbetrag\s+([\d.,]+)", text)
            from backend.intake.pipeline import de_amount
            res = await _call(c, "controller", "request_payment",
                              {"invoice": invoice_no, "amount_eur": de_amount(amount[1]) if amount else "0.00",
                               "iban": normalize(m[1]) if m else ""})
            return f"Paid as instructed: {res.get('status')} {res.get('code', '')}".strip()

        inv = await _call(c, "controller", "get_invoice", {"invoice": invoice_no})
        if inv.get("status") == "QUARANTINED":
            await _call(c, "controller", "place_hold", {"invoice": invoice_no, "reason": "failed intake screening"})
            return "HOLD: failed intake screening"
        ver = await _call(c, "controller", "verify_invoice", {"invoice": invoice_no})
        if ver.get("status") == "VERIFIED":
            res = await _call(c, "controller", "request_payment",
                              {"invoice": invoice_no, "amount_eur": inv["amount_eur"], "iban": inv["iban"]})
            return "PAY: approval requested" if res.get("status") == "PENDING_APPROVAL" else f"HOLD: {res.get('code')}"
        failed = [k["check"] for k in ver.get("checks", []) if not k["pass"]] or [ver.get("status", "?")]
        t, ctx = SimpleNamespace(name="investigator"), SimpleNamespace(agent_name="controller")
        req = {"request": f"Invoice {invoice_no}; failed checks: {', '.join(failed)}"}
        callbacks.before_tool(t, req, ctx)
        verdict = await investigator(invoice_no, failed)
        callbacks.after_tool(t, req, ctx, {"result": json.dumps(verdict)})
        if verdict["verdict"] == "CHANGE_CONFIRMED":
            await _call(c, "controller", "raise_alert", {"title": "Vendor bank change confirmed",
                                                         "detail": "Please update the vendor master in AppSheet."})
        await _call(c, "controller", "place_hold", {"invoice": invoice_no,
                                                    "reason": f"Investigator: {verdict['verdict']}"})
        return f"HOLD: {verdict['verdict']}"

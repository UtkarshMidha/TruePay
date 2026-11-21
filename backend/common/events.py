"""Event contract (PRD §8) + emit(): one Firestore doc in `events` and one coloured terminal line (§9)."""
import os
import re
import sys
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from rich.console import Console

Actor = Literal["baseline", "intake", "sentinel", "model_armor", "controller", "investigator",
                "onboarding", "vendor_agent", "firewall", "human", "bank"]
EventType = Literal["STEP", "CHECK", "TOOL_CALL", "DECISION", "ALERT"]
Layer = Literal["L1", "L2", "L3", "L4", "L5", "L6"]
Verdict = Literal["INFO", "PASS", "BLOCK", "ALLOW", "DENY"]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    invoice_id: Optional[str] = None
    actor: Actor
    type: EventType
    layer: Optional[Layer] = None
    verdict: Verdict
    title: str = Field(max_length=60)
    detail: str = Field(default="", max_length=200)
    tool: Optional[str] = None
    codes: list[str] = []
    amount_cents: Optional[int] = None


# Compact (DE39999999990012345678) or grouped (DE39 9999 9999 0012 3456 78) IBANs.
_IBAN_IN_TEXT = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_COLOURS = {"ALLOW": "green", "PASS": "green", "DENY": "red", "BLOCK": "red", "INFO": "blue"}
_console = Console(file=sys.stdout, highlight=False, soft_wrap=True)

# EMIT_FIRESTORE=0 -> terminal only (tests, offline dev).
_WRITE = os.environ.get("EMIT_FIRESTORE", "1") != "0"


def mask_ibans(text: str) -> str:
    """Safety net: any full IBAN that slips into a title/detail is masked to DE39…5678."""
    return _IBAN_IN_TEXT.sub(lambda m: (lambda c: f"{c[:4]}…{c[-4:]}")(m.group(0).replace(" ", "")), text or "")


def _clip(s: str, n: int) -> str:
    s = mask_ibans(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def emit(run_id: str, actor: str, type: str, verdict: str, title: str, detail: str = "", *,
         invoice_id: str | None = None, layer: str | None = None, tool: str | None = None,
         codes: list[str] | None = None, amount_cents: int | None = None) -> dict:
    ev = Event(run_id=run_id, invoice_id=invoice_id, actor=actor, type=type, layer=layer, verdict=verdict,
               title=_clip(title, 60), detail=_clip(detail, 200), tool=tool, codes=codes or [],
               amount_cents=amount_cents)
    data = ev.model_dump()
    codes_s = " ".join(data["codes"])
    _console.print(f"{datetime.now():%H:%M:%S}  {actor:<12} [{_COLOURS[verdict]}]{verdict:<5}[/]  "
                   f"{data['title']}  [dim]{codes_s}[/]", markup=True)
    if _WRITE:
        try:
            from backend.common.firestore import db, server_ts
            db().collection("events").add({**data, "ts": server_ts()})
        except Exception as e:  # event bus down must not crash the caller; money paths check Firestore themselves
            _console.print(f"[yellow]event write failed: {type_name(e)}[/]")
    return data


def tool_line(tool: str, **args) -> None:
    """Terminal line for a tool call: → request_payment(invoice=INV-1002, amount_eur=18950.00, iban=DE39…5678)"""
    a = ", ".join(f"{k}={mask_ibans(str(v))}" for k, v in args.items())
    _console.print(f"[blue]→ {tool}({a})[/]", markup=True)


def type_name(e: Exception) -> str:
    return e.__class__.__name__

"""Runner: one command at a time from Firestore `commands` (NEW -> RUNNING -> DONE/ERROR). python -m backend.agents.runner"""
import asyncio
import os
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore

from backend import sim
from backend.agents import callbacks, compromised_onboarding, controller
from backend.common import config
from backend.common.events import emit
from backend.common.firestore import db
from backend.fixtures.make_invoices import OUT, build
from backend.intake.pipeline import run_intake

TITLES = {"baseline": "Legacy AP automation (no controls)", "clean": "INV-1001: standard invoice",
          "poisoned": "INV-1002: prompt injection", "swap": "INV-1003: IBAN substitution",
          "insider": "Compromised service identity", "judge": "Custom invoice"}


def vendor_a2a_url() -> str | None:
    """A2A address from the vendor master (Sheets), never from invoice text. None -> INCONCLUSIVE -> HOLD."""
    if config.SIM:
        return "sim://mueller"
    if config.LOCAL_MASTER:  # no Sheet: the seed vendor master
        from backend.scripts.seed import VENDORS
        return dict(zip(VENDORS[0], VENDORS[1]))["a2a_url"]
    try:
        import gspread
        rows = gspread.service_account(filename=config.env("GOOGLE_APPLICATION_CREDENTIALS", "sa.json")) \
            .open_by_key(config.SHEET_ID).worksheet("vendors").get_all_records()
        return next(r["a2a_url"] for r in rows if r["vendor_id"] == config.VENDOR_ID)
    except Exception as e:
        print(f"runner: vendor master unreadable ({e.__class__.__name__}); vendor callback disabled")
        return None


def new_run(scenario: str) -> tuple[str, int]:
    ref = db().document("config/runtime")

    @firestore.transactional
    def bump(tx):
        seq = ((ref.get(transaction=tx).to_dict() or {}).get("run_seq") or 0) + 1
        tx.set(ref, {"run_seq": seq, "current_run_id": f"run-{seq:04d}", "current_scenario": scenario}, merge=True)
        return seq

    seq = bump(db().transaction())
    return f"run-{seq:04d}", seq


def layers_for(scenario: str) -> dict:
    stored = (db().document("config/layers").get().to_dict()) or {}
    return {**config.DEFAULT_LAYERS, **stored}


async def handle(cmd: dict, a2a_url: str | None):
    """note == "demo": replay cached agent responses for this run (fast, no model calls). paygate, rules,
    approvals and the vendor master stay real either way."""
    demo = cmd.get("note") == "demo" and cmd["scenario"] != "judge"
    prev, config.SIM = config.SIM, config.SIM or demo
    try:
        await _handle(cmd, a2a_url)
    finally:
        config.SIM = prev


async def _handle(cmd: dict, a2a_url: str | None):
    scenario = cmd["scenario"]
    run_id, seq = new_run(scenario)
    callbacks.RUN.update(run_id=run_id, invoice_id=None)
    emit(run_id, "intake" if scenario != "baseline" else "baseline", "STEP", "INFO", TITLES[scenario],
         f"Run {run_id}" + (" · demo mode: cached agent responses" if config.SIM else " · live agents"))

    if scenario == "insider":
        await compromised_onboarding.attack(run_id)
        return
    fixture = config.FIXTURE_BY_KEY[scenario]
    if scenario == "baseline":
        from backend.baseline import automation
        await asyncio.to_thread(automation.run, run_id, OUT / f"{fixture}.pdf", fixture)
        return

    layers = layers_for(scenario)
    pdf = OUT / f"{fixture}.pdf"
    if scenario == "judge":
        pdf = build(fixture, note=cmd.get("note") or "", out_dir=Path(tempfile.mkdtemp()))
    elif not pdf.exists():
        pdf = build(fixture)
    doc, text = await asyncio.to_thread(run_intake, run_id, seq, fixture, pdf, layers, cmd.get("note"))
    callbacks.RUN["invoice_id"] = doc["invoice_id"]

    l3_off = not layers["quarantine"]
    run_agents = sim.controller if config.SIM else controller.run
    kwargs = dict(a2a_url=a2a_url, raw_text=text if l3_off else None, jailbroken=layers["jailbreak_controller"])
    try:
        final = await run_agents(doc["invoice_no"], **kwargs)
    except Exception as e:  # Gemini 429/503 at event load: one retry on the backup key (paygate still decides money)
        backup = config.env("GOOGLE_API_KEY_FALLBACK")
        if config.SIM or not backup or os.environ.get("GOOGLE_API_KEY") == backup:
            raise
        os.environ["GOOGLE_API_KEY"] = backup
        emit(run_id, "controller", "STEP", "INFO", "Switched to backup Gemini key", e.__class__.__name__,
             invoice_id=doc["invoice_id"])
        final = await run_agents(doc["invoice_no"], **kwargs)
    inv = db().document(f"invoices/{doc['invoice_id']}").get().to_dict() or {}
    status = inv.get("status", "?")
    verdict = {"HOLD": "BLOCK", "PENDING_APPROVAL": "ALLOW", "PAID": "ALLOW"}.get(status, "INFO")
    emit(run_id, "controller", "DECISION", verdict, f"Decision: {'PAY' if verdict == 'ALLOW' else status}",
         final.splitlines()[0][:200] if final else "No reply", invoice_id=doc["invoice_id"],
         amount_cents=inv.get("amount_cents"))


def set_status(ref, status: str) -> bool:
    """A reset may delete the command mid-run; the runner must keep listening."""
    try:
        ref.update({"status": status})
        return True
    except Exception as e:
        print(f"runner: command {ref.id} gone ({e.__class__.__name__}); continuing")
        return False


def main():
    if config.SIM:
        print("runner: SIMULATION MODE (TP_SIM=1): scripted agents, no Gemini / Model Armor / Sheets")
    elif not config.GOOGLE_API_KEY:
        print("runner: WARNING GOOGLE_API_KEY is empty in .env; agent runs will fail (see docs/SETUP.md step 4)")
    a2a_url = vendor_a2a_url()
    print(f"runner: listening on commands (vendor agent: {a2a_url})")
    col = db().collection("commands")
    while True:
        new = sorted(col.where("status", "==", "NEW").stream(), key=lambda s: str(s.to_dict().get("created_at")))
        for snap in new[:1]:
            cmd = snap.to_dict()
            if cmd.get("note") == "reset":  # sidebar Reset button (rules only allow commands, not deletes)
                from backend.scripts.reset import reset
                print("runner: reset requested from the UI:", reset())
                continue
            if not set_status(snap.reference, "RUNNING"):
                continue
            try:
                if cmd.get("scenario") not in config.SCENARIO_KEYS:
                    raise ValueError(f"unknown scenario {cmd.get('scenario')!r}")
                asyncio.run(handle(cmd, a2a_url))
                set_status(snap.reference, "DONE")
            except Exception as e:
                traceback.print_exc()
                set_status(snap.reference, "ERROR")
                run_id = (db().document("config/runtime").get().to_dict() or {}).get("current_run_id", "run-0000")
                emit(run_id, "controller", "STEP", "INFO", f"Run failed: {e.__class__.__name__}",
                     str(e)[:200] or "see the runner terminal", invoice_id=callbacks.RUN.get("invoice_id"))
        time.sleep(0.5)


if __name__ == "__main__":
    main()

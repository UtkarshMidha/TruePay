"""make reset: back to a clean demo in seconds (PRD §11)."""
from datetime import datetime, timezone

from backend.common import config
from backend.common.firestore import db
from backend.scripts.seed import seed_sheet


def wipe(col, where=None):
    q = db().collection(col)
    if where:
        q = q.where(*where)
    n, batch = 0, db().batch()
    for snap in q.stream():
        batch.delete(snap.reference); n += 1
        if n % 400 == 0:
            batch.commit(); batch = db().batch()
    batch.commit()
    return n


def reset() -> dict:
    counts = {c: wipe(c) for c in ("events", "invoices", "approvals", "commands", "baseline_confirmations",
                                   "baseline_transfers")}
    counts["payments"] = wipe("payments", ("historic", "==", False))
    d = db()
    d.document("stats/demo").set({"lost_cents": 0, "blocked_cents": 0, "paid_cents": 0, "denied_actions": 0})
    d.document("config/layers").set(config.DEFAULT_LAYERS)
    d.document("config/runtime").set({"current_run_id": "run-0000", "current_scenario": None, "run_seq": 0,
                                      "session_started_at": datetime.now(timezone.utc), "revoked": []})
    if not config.LOCAL_MASTER:
        seed_sheet(ledger=True)  # restores PO amounts and empties the ledger
    return counts


if __name__ == "__main__":
    print("reset:", reset())

"""Env loading and the canonical SCENARIOS table (PRD §3). Mirrors app/lib/scenarios.dart."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


GOOGLE_API_KEY = env("GOOGLE_API_KEY")
CONTROLLER_MODEL = env("CONTROLLER_MODEL", "gemini-4-hydrogen")
WORKER_MODEL = env("WORKER_MODEL", "gemini-3.8-flash")
SENTINEL_MODEL = env("SENTINEL_MODEL", "gemma4:e4b")
SENTINEL_BACKEND = env("SENTINEL_BACKEND", "ollama")
GCP_PROJECT = env("GCP_PROJECT")
MODEL_ARMOR_TEMPLATE = env("MODEL_ARMOR_TEMPLATE")
SHEET_ID = env("SHEET_ID")
PAYGATE_URL = env("PAYGATE_URL", "http://localhost:8001/mcp")
POLICY_FILE = ROOT / env("POLICY_FILE", "./policy/paygate.yaml")
APPROVAL_SECRET = env("APPROVAL_SECRET")
APPROVER_UID = env("APPROVER_UID")
SIM = env("TP_SIM") == "1"  # keyless rehearsal mode, see backend/sim.py
# No Sheet configured: vendor master + POs come from the seed tables, the audit ledger goes to audit_ledger.csv
LOCAL_MASTER = SIM or not SHEET_ID

# token -> identity (PRD §6 Identities). Empty tokens never match.
TOKENS = {
    t: ident
    for ident, t in (
        ("controller", env("TOKEN_CONTROLLER")),
        ("investigator", env("TOKEN_INVESTIGATOR")),
        ("onboarding", env("TOKEN_ONBOARDING")),
    )
    if t
}

# Fixture constants (PRD §3)
VENDOR_ID = "V-001"
VENDOR_NAME = "Müller Bürobedarf GmbH"
MASTER_IBAN = "DE89370400440532013000"
ATTACKER_IBAN = "DE39999999990012345678"
ATTACKER_HOLDER = "Mueller Buerobedarf"

# Canonical scenario table (PRD §3). Act 5 reuses key "poisoned" with switches.
DEFAULT_LAYERS = {"hidden_text": True, "model_armor": True, "quarantine": True, "jailbreak_controller": False}
SCENARIOS = [
    {"act": 0, "key": "baseline", "fixture": "INV-1003", "button": "0", "switches": "ignored"},
    {"act": 1, "key": "clean", "fixture": "INV-1001", "button": "1", "switches": "defaults"},
    {"act": 2, "key": "poisoned", "fixture": "INV-1002", "button": "2", "switches": "defaults"},
    {"act": 3, "key": "swap", "fixture": "INV-1003", "button": "3", "switches": "defaults"},
    {"act": 4, "key": "insider", "fixture": None, "button": "4", "switches": "ignored"},
    {"act": 5, "key": "poisoned", "fixture": "INV-1002", "button": "2", "switches": "L1-L3 off, jailbreak on"},
    {"act": "judge", "key": "judge", "fixture": "INV-1099", "button": "Run attack", "switches": "as set"},
]
SCENARIO_KEYS = ("baseline", "clean", "poisoned", "swap", "insider", "judge")
FIXTURE_BY_KEY = {s["key"]: s["fixture"] for s in SCENARIOS}

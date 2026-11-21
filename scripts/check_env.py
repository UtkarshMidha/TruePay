"""make check-env: which .env values are still placeholders, and which local files/tools are missing."""
import os
import shutil
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
env = dotenv_values(ROOT / ".env") if (ROOT / ".env").exists() else {}
NEED = {
    "GOOGLE_API_KEY": "AI Studio key (docs/SETUP.md step 4)",
    "GCP_PROJECT": "Google Cloud project id (step 2)",
    "MODEL_ARMOR_TEMPLATE": "template path with your project id (step 3, setup.sh fills it)",
    "SHEET_ID": "Sheet id from its URL (step 5)",
    "APPROVER_UID": "UID of approver@iw-demo.example (step 6)",
    "TOKEN_CONTROLLER": "generated token", "TOKEN_INVESTIGATOR": "generated token",
    "TOKEN_ONBOARDING": "generated token", "APPROVAL_SECRET": "generated secret",
}
missing = [(k, why) for k, why in NEED.items() if not env.get(k) or "<" in env.get(k, "")]
for k, why in missing:
    print(f"  [ ] {k:<22} {why}")
files = [("sa.json", "service-account key (step 3, setup.sh creates it)"),
         ("app/firebase.web.json", "Firebase web config (step 7, `make app/firebase.web.json`)")]
for f, why in files:
    if not (ROOT / f).exists():
        print(f"  [ ] {f:<22} {why}"); missing.append(f)
for tool in ("gcloud", "flutter", "firebase", "tmux", "ollama"):
    if not shutil.which(tool):
        print(f"  [ ] tool: {tool:<16} not on PATH (docs/SETUP.md step 1)"); missing.append(tool)
print("All set." if not missing else f"\n{len(missing)} item(s) left.")
sys.exit(1 if missing else 0)

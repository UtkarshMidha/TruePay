"""Local dev only: seed the Firestore+Auth emulators (make emu) with config and the two demo users.
FIRESTORE_EMULATOR_HOST=localhost:8085 GCP_PROJECT=demo-truepay python -m backend.scripts.emu_seed"""
import json
import os
import urllib.request

assert os.environ.get("FIRESTORE_EMULATOR_HOST"), "emulator only"
from backend.scripts.seed import seed_firestore  # noqa: E402

seed_firestore()
for email in ("operator@iw-demo.example", "approver@iw-demo.example"):
    req = urllib.request.Request(
        "http://localhost:9099/identitytoolkit.googleapis.com/v1/accounts:signUp?key=demo-key",
        data=json.dumps({"email": email, "password": "demo1234", "returnSecureToken": True}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        uid = json.load(urllib.request.urlopen(req))["localId"]
    except urllib.error.HTTPError:  # already exists: sign in to read its uid
        req.full_url = req.full_url.replace("accounts:signUp", "accounts:signInWithPassword")
        uid = json.load(urllib.request.urlopen(req))["localId"]
    print(f"{email} / demo1234  uid={uid}")
    if email.startswith("approver"):
        print(f"APPROVER_UID={uid}")

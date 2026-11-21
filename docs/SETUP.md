# Setup guide: filling in the keys

All config lives in **`.env`** (git-ignored; already created, with the local secrets generated).
Run **`make check-env`** at any time. It lists exactly which items are still missing.

| `.env` key | What it is | Where you get it | Step |
| :-- | :-- | :-- | :-- |
| `GCP_PROJECT` | Google Cloud project **id** | Cloud console project picker | 2 |
| `MODEL_ARMOR_TEMPLATE` | Model Armor template path | Filled by `scripts/setup.sh` | 3 |
| `GOOGLE_APPLICATION_CREDENTIALS` → `sa.json` | Service-account key file | Created by `scripts/setup.sh` | 3 |
| `GOOGLE_API_KEY` | Gemini API key | AI Studio, in the **same** project | 4 |
| `SHEET_ID` | Google Sheet id | The Sheet's URL | 5 |
| `APPROVER_UID` | Firebase UID of the approver | Firebase console → Authentication | 6 |
| `app/firebase.web.json` | Firebase web-app config (public values) | `make app/firebase.web.json` | 7 |
| `TOKEN_*`, `APPROVAL_SECRET` | Agent identity tokens, HMAC secret | **Already generated**, leave them | none |
| `CONTROLLER_MODEL`, `WORKER_MODEL` | Gemini model ids | Check they exist in AI Studio | 4 |
| `SENTINEL_BACKEND`, `SENTINEL_MODEL` | Local Gemma or API fallback | See step 1 | 1 |

## 1. Tools (done on the demo laptop, except Ollama)

Installed in user space under `~/tools` (the Makefile puts them on `PATH`): Flutter, gcloud, tmux;
`firebase-tools` via npm. For your own shell, add:

```bash
export PATH="$HOME/tools/flutter/bin:$HOME/tools/google-cloud-sdk/bin:$HOME/tools/tmuxenv/bin:$PATH"
```

**Ollama must be upgraded (needs sudo).** The installed 0.20.7 cannot pull Gemma 4:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:e4b
```

If that is not possible, set `SENTINEL_BACKEND=api` and put the Gemma model id from AI Studio in `SENTINEL_MODEL`.

## 2. Google Cloud project with billing

1. <https://console.cloud.google.com/>: create or pick a project and attach the event's billing / credits.
2. Copy the **project id** into `GCP_PROJECT=`.
3. Log in from the terminal: `gcloud auth login` and `gcloud auth application-default login`.

## 3. Cloud resources (one script)

```bash
GCP_PROJECT=<your-project-id> ./scripts/setup.sh
```

It enables the APIs, creates Firestore (europe-west3), the Model Armor template `iw-invoice`, and the
service account `iw-backend` with `datastore.user` and `modelarmor.user`. It saves its key as `sa.json`
and fills `GCP_PROJECT` and `MODEL_ARMOR_TEMPLATE` in `.env`. The generated tokens are kept.

## 4. Gemini API key

1. <https://aistudio.google.com/apikey>, then **Create API key**, then choose the **same project** as step 2.
2. Paste it into `GOOGLE_API_KEY=`.
3. In AI Studio's model list, confirm that `CONTROLLER_MODEL` and `WORKER_MODEL` exist. If not, put the closest
   current ids in `.env` (one line each).

## 5. Google Sheet "TruePay Master"

1. Create an empty Google Sheet with that name.
2. **Share** it with `iw-backend@<project-id>.iam.gserviceaccount.com` as **Editor**.
3. Copy the id from the URL `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit` into `SHEET_ID=`.
4. `make seed` creates the tabs `vendors`, `purchase_orders` and `audit_ledger` with the fixture rows.

## 6. Firebase Auth users

1. <https://console.firebase.google.com/>: **Add Firebase** to the same project.
2. Authentication, then Sign-in method, then enable **Email/Password**.
3. Users, then add `operator@iw-demo.example` and `approver@iw-demo.example` (any passwords; note them).
4. Copy the approver's **User UID** into `APPROVER_UID=`.

## 7. Firebase CLI and web config

```bash
firebase login
firebase use <project-id>
firebase apps:create web truepay      # once
make app/firebase.web.json                  # writes the web config the Flutter app reads
```

## 8. Run

```bash
make check-env      # should print "All set."
make fixtures seed  # invoices, Sheet tabs, Firestore config, 6 historic payments
make test           # firewall tests F0–F7
make web            # build + deploy Mission Control / Approver / Report
make up             # tmux: ollama, paygate :8001, vendor agent :8002, runner
make reset          # between rehearsals
```

Mission Control: `https://<project-id>.web.app/` (operator). Phone: `https://<project-id>.web.app/approve` (approver).
Fallback without Hosting: `cd app && flutter run -d chrome --dart-define-from-file=firebase.web.json`.

## Try it without any keys (local emulators)

```bash
make emu                                                   # terminal 1: Firestore :8085 + Auth :9099, real rules
export FIRESTORE_EMULATOR_HOST=localhost:8085 GCP_PROJECT=demo-truepay
.venv/bin/python -m backend.scripts.emu_seed               # config + operator/approver (password demo1234)
cd app && flutter run -d chrome --dart-define=EMULATOR=true   # Mission Control; /approve for the phone
```

Act 4 and Act 0 also run fully on the emulator (no Gemini needed). Acts 1–3 and 5 need `GOOGLE_API_KEY` and the Sheet.

## Optional extra

**AppSheet finance console** (no code, about 5 minutes):
1. <https://www.appsheet.com/>: **Create**, then **App**, then **Start with existing data**, then pick the "TruePay Master" Sheet.
2. Tables `vendors` (editable: `iban`, `a2a_url`, `status`), `purchase_orders` (read-only), `audit_ledger` (read-only).
3. Use a deck view on `audit_ledger` sorted by `ts` descending, and a form view on `vendors`.
4. This is the **only** place a person changes bank details. Agents have no tool for it.

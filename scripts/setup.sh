#!/usr/bin/env bash
# One-time GCP setup (PRD §11). Needs: gcloud logged in, billing linked, GCP_PROJECT set.
# Usage: GCP_PROJECT=my-project ./scripts/setup.sh
set -euo pipefail
export CLOUDSDK_CORE_DISABLE_PROMPTS=1  # never hang on an interactive prompt
: "${GCP_PROJECT:?set GCP_PROJECT}"
SA_NAME=iw-backend
SA_EMAIL="$SA_NAME@$GCP_PROJECT.iam.gserviceaccount.com"

gcloud config set project "$GCP_PROJECT"

# 3. APIs
gcloud services enable modelarmor.googleapis.com sheets.googleapis.com firestore.googleapis.com \
  run.googleapis.com cloudfunctions.googleapis.com \
  firebase.googleapis.com identitytoolkit.googleapis.com firebasehosting.googleapis.com \
  iam.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com

# 2. Firestore native mode, europe-west3 (no-op if it already exists)
gcloud firestore databases describe --database="(default)" >/dev/null 2>&1 || \
  gcloud firestore databases create --location=europe-west3 --type=firestore-native

# 4. Model Armor template (regional endpoint)
gcloud config set api_endpoint_overrides/modelarmor "https://modelarmor.europe-west3.rep.googleapis.com/"
gcloud model-armor templates create iw-invoice --location=europe-west3 \
  --pi-and-jailbreak-filter-settings-enforcement=enabled \
  --pi-and-jailbreak-filter-settings-confidence-level=LOW_AND_ABOVE \
  --malicious-uri-filter-settings-enforcement=enabled || echo "template exists?"

# 5. Service account with datastore.user + modelarmor.user, key saved as sa.json (git-ignored)
gcloud iam service-accounts create "$SA_NAME" --display-name="TruePay backend" 2>/dev/null || true
for role in roles/datastore.user roles/modelarmor.user; do
  gcloud projects add-iam-policy-binding "$GCP_PROJECT" --member="serviceAccount:$SA_EMAIL" \
    --role="$role" --condition=None -q >/dev/null
done
[ -f sa.json ] || gcloud iam service-accounts keys create sa.json --iam-account="$SA_EMAIL"

# Tokens and approval secret for .env
[ -f .env ] || cp .env.example .env
for k in TOKEN_CONTROLLER TOKEN_INVESTIGATOR TOKEN_ONBOARDING APPROVAL_SECRET; do
  grep -q "^$k=.\+" .env || sed -i "s|^$k=.*|$k=$(python3 -c 'import secrets; print(secrets.token_hex(16))')|" .env
done
sed -i "s|^GCP_PROJECT=.*|GCP_PROJECT=$GCP_PROJECT|; /^MODEL_ARMOR_TEMPLATE=/s|<GCP_PROJECT>|$GCP_PROJECT|" .env

# 6. Local model (needs a recent Ollama; otherwise set SENTINEL_BACKEND=api in .env)
ollama pull gemma4:e4b || echo "WARNING: ollama pull failed; upgrade Ollama or set SENTINEL_BACKEND=api"

echo
echo "Done. Share the Sheet 'TruePay Master' with $SA_EMAIL as Editor and put its id in SHEET_ID."

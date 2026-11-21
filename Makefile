PY ?= .venv/bin/python
# Tools installed in user space by the setup (docs/SETUP.md step 1)
export PATH := $(HOME)/tools/flutter/bin:$(HOME)/tools/google-cloud-sdk/bin:$(HOME)/tools/tmuxenv/bin:$(PATH)

.PHONY: fixtures seed up test reset web check-env install emu sim sim-reset

# Keyless rehearsal: emulators + real paygate + scripted agents + UI on http://localhost:5000 (docs/SETUP.md)
sim:
	./scripts/sim.sh

sim-reset:
	TP_SIM=1 FIRESTORE_EMULATOR_HOST=localhost:8085 GCP_PROJECT=demo-truepay $(PY) -m backend.scripts.reset

# Local dev without any keys: Firestore + Auth emulators (project demo-truepay) with the real security rules.
emu:
	firebase emulators:start --only firestore,auth --project demo-truepay

install:
	python3 -m venv .venv && $(PY) -m pip install -q -r requirements.txt

check-env:
	@$(PY) scripts/check_env.py

fixtures:
	$(PY) -m backend.fixtures.make_invoices

seed:
	$(PY) -m backend.scripts.seed

# Panes stay open on exit so a crash stays readable. Stage: runner (agents) on top, paygate below.
KEEP = ; echo; echo '[exited - press enter]'; read _
up:
	tmux kill-session -t tp 2>/dev/null || true
	tmux new-session -d -s tp -x 220 -y 55 "$(PY) -m backend.agents.runner $(KEEP)" \; \
	  split-window -v "$(PY) -m backend.paygate.server $(KEEP)" \; \
	  split-window -h "$(PY) -m uvicorn backend.vendor_agent.a2a_app:app --port 8002 $(KEEP)" \; \
	  split-window -h "$(PY) scripts/spa.py app/build/web 5000 $(KEEP)" \; \
	  select-pane -t 0
	@echo "Mission Control: http://localhost:5000   Phone: http://localhost:5000/approve   Terminal: tmux attach -t tp"

test:
	$(PY) -m pytest tests/ -q

reset:
	$(PY) -m backend.scripts.reset

web: app/firebase.web.json
	cd app && ([ -d web ] || flutter create --platforms=web --project-name truepay .) && \
	  flutter pub get && flutter build web --dart-define-from-file=firebase.web.json --dart-define-from-file=demo_accounts.json
	firebase deploy --only hosting,firestore

# Firebase web config (public values) for the Flutter app.
app/firebase.web.json:
	firebase apps:sdkconfig web --json | $(PY) -c "import json,sys; print(json.dumps(json.load(sys.stdin)['result']['sdkConfig']))" > $@

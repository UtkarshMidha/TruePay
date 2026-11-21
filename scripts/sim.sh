#!/usr/bin/env bash
# Keyless rehearsal (TP_SIM=1, see backend/sim.py): Firestore/Auth emulators with the real rules, the REAL paygate,
# the runner with scripted agents instead of Gemini, and the web UI.
#   Mission Control  http://localhost:5000          operator@iw-demo.example / demo1234
#   Phone            http://localhost:5000/approve  approver@iw-demo.example / demo1234
# Stop: tmux kill-session -t tp-sim
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/tools/flutter/bin:$HOME/tools/tmuxenv/bin:$PATH"
export TP_SIM=1 FIRESTORE_EMULATOR_HOST=localhost:8085 GCP_PROJECT=demo-truepay PYTHONWARNINGS=ignore
PY=.venv/bin/python
KEEP="; echo; echo '[exited - press enter]'; read _"

tmux kill-session -t tp-sim 2>/dev/null || true
[ -f backend/fixtures/out/INV-1001.pdf ] || $PY -m backend.fixtures.make_invoices
tmux new-session -d -s tp-sim -x 220 -y 55 "firebase emulators:start --only firestore,auth --project demo-truepay $KEEP"
echo "building web UI (emulator mode)..."
(cd app && flutter build web --dart-define=EMULATOR=true -o build/web_sim >/dev/null) &
until curl -sf localhost:8085 >/dev/null && curl -sf localhost:9099 >/dev/null; do sleep 1; done
APPROVER_UID=$($PY -m backend.scripts.emu_seed | tee /dev/stderr | sed -n 's/^APPROVER_UID=//p')
wait
E="TP_SIM=1 FIRESTORE_EMULATOR_HOST=localhost:8085 GCP_PROJECT=demo-truepay APPROVER_UID=$APPROVER_UID PYTHONWARNINGS=ignore"
tmux split-window -t tp-sim -v "env $E $PY -m backend.agents.runner $KEEP"
tmux split-window -t tp-sim -v "env $E $PY -m backend.paygate.server $KEEP"
tmux split-window -t tp-sim -h "$PY scripts/spa.py app/build/web_sim 5000 $KEEP"
tmux select-layout -t tp-sim tiled >/dev/null
echo
echo "Running. Mission Control: http://localhost:5000   Phone: http://localhost:5000/approve   (password demo1234)"
echo "Terminal: tmux attach -t tp-sim     Stop: tmux kill-session -t tp-sim     Reset demo: TP_SIM=1 FIRESTORE_EMULATOR_HOST=localhost:8085 GCP_PROJECT=demo-truepay .venv/bin/python -m backend.scripts.reset"

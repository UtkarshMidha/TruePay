"""before/after tool callbacks: every agent tool call becomes an event (PRD §5 ADK wiring)."""
import json
import re

from backend.common.events import emit, tool_line

RUN = {"run_id": "run-0000", "invoice_id": None}  # set by the runner per command
ACTORS = {"controller": "controller", "investigator": "investigator"}


def _actor(ctx) -> str:
    return ACTORS.get(getattr(ctx, "agent_name", ""), "controller")


def parse_verdict(text) -> dict:
    """Investigator reply -> {verdict, evidence}. Anything unparseable is INCONCLUSIVE (-> HOLD)."""
    if isinstance(text, dict):
        text = text.get("result", json.dumps(text))
    m = re.search(r"\{.*\}", str(text), re.S)
    try:
        v = json.loads(m.group(0)) if m else {}
    except ValueError:
        v = {}
    if v.get("verdict") not in ("FRAUD_SUSPECTED", "CHANGE_CONFIRMED", "INCONCLUSIVE"):
        v = {"verdict": "INCONCLUSIVE", "evidence": ["Investigator reply not parseable"]}
    return {"verdict": v["verdict"], "evidence": [str(e) for e in v.get("evidence", [])][:5]}


def before_tool(tool, args, tool_context):
    tool_line(tool.name, **args)
    actor = _actor(tool_context)
    if tool.name == "mueller_agent":
        emit(RUN["run_id"], "investigator", "TOOL_CALL", "INFO", "Asking Müller's agent over A2A",
             str(args.get("request", args))[:200], invoice_id=RUN["invoice_id"], layer="L4", tool="a2a")
    elif tool.name == "investigator":
        emit(RUN["run_id"], actor, "TOOL_CALL", "INFO", "Calling the Investigator", str(args.get("request", args))[:200],
             invoice_id=RUN["invoice_id"])
    else:
        emit(RUN["run_id"], actor, "TOOL_CALL", "INFO", f"{tool.name}({', '.join(f'{v}' for v in args.values())})"[:60],
             json.dumps(args, ensure_ascii=False)[:200], invoice_id=RUN["invoice_id"], tool=tool.name)
    return None


def after_tool(tool, args, tool_context, tool_response):
    if tool.name == "mueller_agent":
        emit(RUN["run_id"], "vendor_agent", "STEP", "INFO", "Müller's agent answered",
             str(tool_response.get("result", tool_response) if isinstance(tool_response, dict) else tool_response)[:200],
             invoice_id=RUN["invoice_id"], layer="L4")
    elif tool.name == "investigator":
        v = parse_verdict(tool_response)
        ev = "; ".join(v["evidence"]) or v["verdict"]
        if v["verdict"] == "CHANGE_CONFIRMED":
            emit(RUN["run_id"], "investigator", "DECISION", "INFO", "Vendor confirms a bank change", ev,
                 invoice_id=RUN["invoice_id"], layer="L4")
        else:
            title = "No bank change: fraud suspected" if v["verdict"] == "FRAUD_SUSPECTED" else "Vendor callback inconclusive"
            emit(RUN["run_id"], "investigator", "DECISION", "BLOCK", title, ev, invoice_id=RUN["invoice_id"], layer="L4")
    return None

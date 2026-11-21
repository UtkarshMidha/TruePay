"""Controller: decides PAY, HOLD or INVESTIGATE through its own MCP identity (PRD §5)."""
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types

from backend.agents import callbacks, investigator
from backend.agents.prompts import CONTROLLER, SIMULATED_JAILBREAK
from backend.common import config

TOOLS = ["get_invoice", "verify_invoice", "request_payment", "place_hold", "raise_alert"]


async def run(invoice_no: str, *, a2a_url: str | None, raw_text: str | None = None, jailbroken: bool = False) -> str:
    """Runs the Controller once. raw_text only when L3 is off (breach simulation). Returns its final text."""
    mcp = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=config.PAYGATE_URL, headers={"Authorization": f"Bearer {config.env('TOKEN_CONTROLLER')}"}, timeout=30),
        tool_filter=TOOLS)
    inv_agent, inv_mcp = investigator.build(a2a_url)
    instruction = f"{SIMULATED_JAILBREAK}\n\n{raw_text or ''}" if jailbroken else CONTROLLER
    agent = LlmAgent(
        name="controller", model=config.CONTROLLER_MODEL, instruction=instruction,
        tools=[mcp, AgentTool(inv_agent)],
        generate_content_config=types.GenerateContentConfig(temperature=0),
        before_tool_callback=callbacks.before_tool, after_tool_callback=callbacks.after_tool)
    msg = f"Invoice number: {invoice_no}"
    if raw_text and not jailbroken:
        msg += f"\n\nInvoice text (L3 quarantine is off):\n{raw_text}"
    runner = InMemoryRunner(agent=agent, app_name="truepay")
    sid = uuid.uuid4().hex
    await runner.session_service.create_session(app_name="truepay", user_id="ap", session_id=sid)
    final = ""
    try:
        async for ev in runner.run_async(user_id="ap", session_id=sid,
                                         new_message=types.Content(role="user", parts=[types.Part(text=msg)])):
            if ev.content and ev.content.parts and ev.author == "controller":
                final = "".join(p.text or "" for p in ev.content.parts) or final
    finally:
        for t in (mcp, inv_mcp):
            try:
                await t.close()
            except Exception:
                pass
    return final.strip()

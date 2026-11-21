"""Investigator: payment history + asks the vendor's own agent over A2A (L4)."""
from google.adk.agents import LlmAgent
from google.adk.agents.remote_a2a_agent import AGENT_CARD_WELL_KNOWN_PATH, RemoteA2aAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types

from backend.agents import callbacks
from backend.agents.prompts import INVESTIGATOR
from backend.common import config


def build(a2a_url: str | None) -> tuple[LlmAgent, McpToolset]:
    mcp = McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=config.PAYGATE_URL, headers={"Authorization": f"Bearer {config.env('TOKEN_INVESTIGATOR')}"}, timeout=30),
        tool_filter=["get_invoice", "get_payment_history", "place_hold", "raise_alert"])
    tools = [mcp]
    if a2a_url:  # from the vendor master, never from invoice text. Unreachable -> INCONCLUSIVE -> HOLD
        tools.append(AgentTool(RemoteA2aAgent(
            name="mueller_agent", agent_card=f"{a2a_url.rstrip('/')}{AGENT_CARD_WELL_KNOWN_PATH}",
            description="The registered agent of the vendor Müller Bürobedarf GmbH. Ask it about its bank details.")))
    agent = LlmAgent(
        name="investigator", model=config.WORKER_MODEL, instruction=INVESTIGATOR, tools=tools,
        description="Investigates payment anomalies. Pass the invoice number and the failed checks.",
        generate_content_config=types.GenerateContentConfig(temperature=0),
        before_tool_callback=callbacks.before_tool, after_tool_callback=callbacks.after_tool)
    return agent, mcp

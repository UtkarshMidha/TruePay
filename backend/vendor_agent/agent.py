"""Müller Bürobedarf's own agent (external company). Answers bank-change questions (L4)."""
from google.adk.agents import LlmAgent
from google.genai import types

from backend.agents.prompts import VENDOR
from backend.common import config


def get_bank_records() -> dict:
    """Return Müller Bürobedarf's current bank records: last 4 IBAN digits and changes in the last 90 days."""
    return {"iban_last4": "3000", "changes_last_90_days": []}


vendor_agent = LlmAgent(
    name="mueller_accounts_agent", model=config.WORKER_MODEL, instruction=VENDOR, tools=[get_bank_records],
    description="Accounts team agent of Müller Bürobedarf GmbH. Answers questions about its bank details.",
    generate_content_config=types.GenerateContentConfig(temperature=0),
)

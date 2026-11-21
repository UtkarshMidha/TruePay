"""L2: Model Armor screening (europe-west3). Caller treats any exception as BLOCK UPSTREAM_UNAVAILABLE.

Screens the full text AND every line of >= 30 chars: an injection embedded in invoice text is missed even with
only five short invoice lines around it, but found on its own line (measured on INV-1002). Any match -> BLOCK.
"""
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from backend.common import config

MIN_LINE = 30


@lru_cache(maxsize=1)
def _client():
    from google.cloud import modelarmor_v1
    return modelarmor_v1.ModelArmorClient(
        client_options={"api_endpoint": "modelarmor.europe-west3.rep.googleapis.com"})


def chunks(text: str) -> list[str]:
    """One chunk per non-trivial line (pdfplumber puts a hidden text block on one line)."""
    return [ln.strip() for ln in text.splitlines() if len(ln.strip()) >= MIN_LINE]


def _one(text: str) -> tuple[bool, str]:
    from google.cloud import modelarmor_v1 as ma
    r = _client().sanitize_user_prompt(request=ma.SanitizeUserPromptRequest(
        name=config.MODEL_ARMOR_TEMPLATE, user_prompt_data=ma.DataItem(text=text))).sanitization_result
    if r.filter_match_state != ma.FilterMatchState.MATCH_FOUND:
        return False, ""
    try:
        return True, r.filter_results["pi_and_jailbreak"].pi_and_jailbreak_filter_result.confidence_level.name
    except Exception:
        return True, "MATCH"


def screen(text: str) -> dict:
    """-> {match: bool, confidence: str}. Raises if Model Armor is unreachable (pipeline fails closed)."""
    if config.SIM:
        from backend import sim
        return sim.screen(text)
    parts = [text] + [c for c in chunks(text) if c.strip() and c != text]
    with ThreadPoolExecutor(max_workers=12) as ex:
        results = list(ex.map(_one, parts))  # any exception propagates -> BLOCK UPSTREAM_UNAVAILABLE
    hits = [conf for match, conf in results if match]
    return {"match": bool(hits), "confidence": hits[0] if hits else "NONE"}

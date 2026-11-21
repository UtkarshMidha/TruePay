# Deviations from PRD snippets (contract unchanged)

- PRD file lived at repo root as `TruePay — PRD (DevFest Münster 2026) (2).md`; moved to `docs/PRD.md`.
- FastMCP 4.2.4: server runs with `mcp.run(transport="http", host, port=8001, path="/mcp")` (streamable HTTP).
- `get_invoice` returns the full invoice IBAN (Controller prompt §5 must pass it to `request_payment`); history, approvals, events and logs stay masked (§7 point 2 applies to those).
- Investigator gets `get_invoice` in its client-side tool filter (allowed by policy) so it can read the vendor name and IBAN last 4 it must quote; §5 table lists only history/hold/alert.
- Payment execution additionally requires the invoice to still be PENDING_APPROVAL, so a HOLD placed after the request stops the payment (fails closed; F7 code unchanged).
- With L3 off (breach simulation) fields come from a deterministic parser (`intake/pipeline.parse_plain`), no model; the Controller additionally gets the raw text as §5 specifies.
- Model Armor (L2) screens the full text plus every line >= 30 chars; on the full INV-1002 text (and even a 5-line block) it returns NO_MATCH (dilution), on the hidden line MATCH_FOUND. Any match is BLOCK; `model_armor{match, confidence}` unchanged.
- L3 quarantines only Sentinel flags aimed at the agent (AI/system, skip approval/verification, speed/secrecy; `sentinel.AGENT_DIRECTED`). A plain bank-change notice (INV-1003) is still recorded in `suspicious_instructions` but goes to C3 + L4, as PRD Act 3 requires L1–L3 PASS. Prompt and InvoiceFields unchanged.

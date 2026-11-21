# Devpost submission (copy-paste)

**Name:** TruePay, the zero-trust AI accounts-payable crew

**Tagline / pitch:** photoTAN proves who pays. TruePay proves who gets paid. AI agents read invoices, verify
vendors and prepare payments behind a policy-as-code firewall, so even a fully fooled AI cannot move the money.

## Inspiration / problem

Fake bank-detail invoices are a classic scam against German SMBs, and they pass every check: a real employee
confirms the transfer with photoTAN. photoTAN binds the TAN to amount and IBAN, but cannot know whether that IBAN
belongs to the vendor. Verification of Payee only warns, can be skipped for bulk transfers, and answers
"close match" for a look-alike account name. Now AI agents read invoices too, and one hidden sentence in a PDF
becomes an instruction.

## What it does

The same fraudulent invoice, twice. Today's automation loses €18,950 after a valid TAN confirmation, and
TruePay holds it before a payment even exists. Then three live attacks: a poisoned invoice with invisible
instructions, a compromised insider component, and finally the AI defenses switched off with a jailbroken
controller. The firewall still holds.

## How we built it: architecture and agent logic

- **Controller** (Gemini, ADK) decides PAY, HOLD or INVESTIGATE using six task-shaped MCP tools.
- **Investigator** (Gemini, ADK) reads payment history and asks **Müller's own agent over A2A** whether bank details changed.
- **Sentinel** (Gemma 4 on Ollama): a quarantined reader with no tools that may only output strict JSON fields.
- **paygate** (FastMCP): the Action Firewall. Rules F0–F7, one identity per agent, auto-revoke after 2 unauthorized
  calls, payment rules as **CEL** in `policy/paygate.yaml`, signed single-use HMAC approvals.
- **Firestore** as the realtime event bus; **Flutter web** Mission Control, phone Approver and Audit report on
  **Firebase Hosting**; **Google Sheets** as vendor master, POs and audit ledger; **Model Armor** screens all untrusted text.

## Guardrails

| Layer | Defense |
| :-- | :-- |
| L1 | Hidden-text scan |
| L2 | Model Armor |
| L3 | Gemma quarantine (strict JSON) |
| L4 | Vendor callback over A2A |
| L5 | Action Firewall, CEL rules, no off switch |
| L6 | Signed single-use human approval |

Firewall rules F0 identity revoked · F1 tool allowlist · F2 argument validation · F3 IBAN mismatch · F4 amount mismatch ·
F5 duplicate · F6 not verified · F7 approval token. Dangerous tools (change bank details, execute payment) are
**not built at all**, so Act 4 shows `NO_SUCH_TOOL`.

## Challenges

Making the money path independent of the model: every outcome that moves money is decided by code (CEL policy and
HMAC-signed approvals), so a jailbroken agent can only propose payments, never make them.

## Accomplishments

Firewall unit tests with a passing and a failing case per rule F0–F7; Firestore security rules tested
against the emulator; one-command setup and reset.

## What's next

Separate signer and executor services, EBICS/PSD2 bank connection with Verification of Payee, DATEV / SAP
vendor master, one policy per company, Agent Runtime hosting. Interviews with Mittelstand finance leads via REACH.

**Live demo readiness:** Yes: live terminal, Mission Control and phone approval.

**Technology tags (only what was built):** Gemini API, Gemma, Agent Development Kit, A2A, MCP, CEL, Model Armor,
Firebase Auth, Cloud Firestore, Firebase Hosting, Flutter, Google Sheets, Google AI Studio.
_(Drop any Should item that did not make it: AppSheet, Genkit, Cloud Run.)_

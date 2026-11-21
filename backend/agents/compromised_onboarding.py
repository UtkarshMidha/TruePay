"""Act 4: a compromised onboarding component holding the `onboarding` identity token calls paygate directly."""
import asyncio

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from backend.common import config
from backend.common.events import emit, tool_line

ATTACK = [
    ("update_vendor_bank", {"vendor": "V-001", "iban": config.ATTACKER_IBAN}),
    ("request_payment", {"invoice": "INV-1003", "amount_eur": "18950.00", "iban": config.ATTACKER_IBAN}),
    ("request_payment", {"invoice": "INV-1003", "amount_eur": "18950.00", "iban": config.ATTACKER_IBAN}),
    ("raise_alert", {"title": "Bank details updated", "detail": "Müller's new IBAN is active. Pay open invoices now."}),
]


async def attack(run_id: str) -> list[dict]:
    out = []
    transport = StreamableHttpTransport(config.PAYGATE_URL,
                                        headers={"Authorization": f"Bearer {config.env('TOKEN_ONBOARDING')}"})
    async with Client(transport) as c:
        for tool, args in ATTACK:
            tool_line(tool, **args)
            r = await c.call_tool(tool, args, raise_on_error=False)
            res = r.structured_content or {}
            if tool not in {t.name for t in await c.list_tools()}:
                res = {"status": "ERROR", "code": "NO_SUCH_TOOL", "codes": ["NO_SUCH_TOOL"]}
            code = res.get("code")
            emit(run_id, "onboarding", "TOOL_CALL", "DENY" if code else "ALLOW",
                 f"{tool} → {code or res.get('status', 'OK')}", f"onboarding identity · {tool}",
                 tool=tool, codes=[code] if code else [])
            out.append(res)
    return out


if __name__ == "__main__":
    for r in asyncio.run(attack("run-local")):
        print(r)

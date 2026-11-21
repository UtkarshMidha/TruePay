"""paygate over real MCP/HTTP with bearer tokens (fake store): exactly six tools, Act 4 sequence (A4)."""
import asyncio
import socket
import threading
import time

import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from backend.paygate import server
from backend.paygate.firewall import Gate
from backend.paygate.policy import load_policy
from tests.test_firewall import TOKENS, FakeStore


@pytest.fixture(scope="module")
def url():
    server._gate = Gate(load_policy(), FakeStore(), tokens=TOKENS)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    threading.Thread(target=lambda: server.mcp.run(transport="http", host="127.0.0.1", port=port, path="/mcp",
                                                   show_banner=False), daemon=True).start()
    time.sleep(1.5)
    return f"http://127.0.0.1:{port}/mcp"


def client(url, token):
    return Client(StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"}))


async def call(c, name, args):
    r = await c.call_tool(name, args, raise_on_error=False)
    return r.structured_content


def test_six_tools_and_act4(url):
    async def go():
        async with client(url, "to") as c:
            names = sorted(t.name for t in await c.list_tools())
            assert names == ["get_invoice", "get_payment_history", "place_hold", "raise_alert",
                             "request_payment", "verify_invoice"]
            r = await c.call_tool("update_vendor_bank", {"vendor": "V-001", "iban": "DE39999999990012345678"},
                                  raise_on_error=False)
            assert r.is_error  # fails at the MCP layer -> caller reports NO_SUCH_TOOL
            pay = {"invoice": "INV-1001", "amount_eur": "4280.00", "iban": "DE39999999990012345678"}
            assert (await call(c, "request_payment", pay))["code"] == "UNAUTHORIZED_TOOL"
            assert (await call(c, "request_payment", pay))["code"] == "UNAUTHORIZED_TOOL"
            assert (await call(c, "raise_alert", {"title": "x", "detail": "y"}))["code"] == "IDENTITY_REVOKED"
        async with client(url, "tc") as c:
            assert (await call(c, "get_invoice", {"invoice": "INV-1001"}))["status"] == "VERIFIED"
    asyncio.run(go())

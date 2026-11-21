"""uvicorn backend.vendor_agent.a2a_app:app --port 8002
On Cloud Run set PUBLIC_URL (the service URL) so the A2A agent card advertises the public address, not localhost."""
import os
from urllib.parse import urlparse

from google.adk.a2a.utils.agent_to_a2a import to_a2a

from backend.vendor_agent.agent import vendor_agent

_pub = urlparse(os.environ.get("PUBLIC_URL", ""))
app = (to_a2a(vendor_agent, host=_pub.hostname, port=_pub.port or (443 if _pub.scheme == "https" else 80),
              protocol=_pub.scheme) if _pub.hostname else to_a2a(vendor_agent, port=8002))

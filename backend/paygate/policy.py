"""policy/paygate.yaml loader + CEL evaluation of payment rules F3–F6 (PRD §6)."""
from dataclasses import dataclass

import celpy
import yaml

from backend.common import config


@dataclass(frozen=True)
class Policy:
    identities: dict[str, list[str]]
    revoke_after_unauthorized: int
    payment_limit_cents: int
    approval_ttl_seconds: int
    rules: dict  # code -> compiled CEL program, in YAML order (F3, F4, F5, F6)

    def failed(self, activation: dict, only: tuple[str, ...] | None = None) -> list[str]:
        """Codes of every rule that is not true. Any evaluation error counts as a failure (fail closed)."""
        act = celpy.json_to_cel(activation)
        out = []
        for code, prog in self.rules.items():
            if only and code not in only:
                continue
            try:
                ok = prog.evaluate(act)
                ok = isinstance(ok, celpy.celtypes.BoolType) and bool(ok)
            except Exception:
                ok = False
            if not ok:
                out.append(code)
        return out


def load_policy(path=None) -> Policy:
    with open(path or config.POLICY_FILE, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    env = celpy.Environment()
    return Policy(
        identities={k: list(v) for k, v in raw["identities"].items()},
        revoke_after_unauthorized=int(raw["revoke_after_unauthorized"]),
        payment_limit_cents=int(raw["payment_limit_cents"]),
        approval_ttl_seconds=int(raw["approval_ttl_seconds"]),
        rules={code: env.program(env.compile(expr)) for code, expr in raw["rules"].items()},
    )

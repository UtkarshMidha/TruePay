"""IBAN mod-97 check and masking (PRD §6, §8)."""
import re

IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")


def normalize(iban: str) -> str:
    return re.sub(r"\s+", "", iban or "").upper()


def checksum_ok(iban: str) -> bool:
    iban = normalize(iban)
    if not IBAN_RE.match(iban):
        return False
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def mask(iban: str) -> str:
    iban = normalize(iban)
    return f"{iban[:4]}…{iban[-4:]}" if len(iban) > 8 else "…"


def last4(iban: str) -> str:
    return normalize(iban)[-4:]

"""Sentinel output schema InvoiceFields (PRD §5). Frozen contract."""
from datetime import date
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from backend.common.money import to_cents


class InvoiceFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: str
    invoice_no: Annotated[str, StringConstraints(pattern=r"^INV-\d{4}$")]
    invoice_date: date  # YYYY-MM-DD
    po_number: Annotated[str, StringConstraints(pattern=r"^PO-\d{4}$")]
    amount_eur: Annotated[str, StringConstraints(pattern=r"^\d+\.\d{2}$")]  # decimal string, e.g. "18950.00"
    iban: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]+$")]  # uppercase, no spaces
    suspicious_instructions: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("iban", mode="before")
    @classmethod
    def _iban_upper(cls, v):
        return "".join(str(v).split()).upper()

    @property
    def amount_cents(self) -> int:
        return to_cents(self.amount_eur)

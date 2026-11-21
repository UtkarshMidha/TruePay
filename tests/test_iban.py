import pytest

from backend.common import iban, money
from backend.common.config import ATTACKER_IBAN, MASTER_IBAN
from backend.common.events import mask_ibans


def test_fixture_ibans_have_valid_checksums():
    assert iban.checksum_ok(MASTER_IBAN)
    assert iban.checksum_ok(ATTACKER_IBAN)
    assert iban.checksum_ok("DE89 3704 0044 0532 0130 00")


@pytest.mark.parametrize("bad", ["DE89370400440532013001", "DE00370400440532013000", "XX", "", "de89-3704"])
def test_bad_ibans_fail(bad):
    assert not iban.checksum_ok(bad)


def test_mask():
    assert iban.mask(ATTACKER_IBAN) == "DE39…5678"
    assert iban.mask("DE89 3704 0044 0532 0130 00") == "DE89…3000"
    assert mask_ibans(f"pay {ATTACKER_IBAN} now") == "pay DE39…5678 now"


def test_money_cents():
    assert money.to_cents("18950.00") == 1895000
    assert money.to_cents("4280") == 428000
    assert money.eur(1895000) == "18950.00"
    for bad in ["abc", "1.005", 1.5, "NaN"]:
        with pytest.raises(ValueError):
            money.to_cents(bad)


def test_mask_spaced_iban_in_text():
    assert mask_ibans("to IBAN DE39 9999 9999 0012 3456 78. The CFO") == "to IBAN DE39…5678. The CFO"

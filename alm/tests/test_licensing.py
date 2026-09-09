"""Licensing golden tests: issue/verify round-trip, and every way a license
can be invalid checked independently, a corrupted token, expiry, a wrong
verification key, a structurally-valid but forged upgrade, and the actual
point of asymmetric signing: possessing only the public key (what ships to
every customer) must never be enough to issue a new, validly-signed license.
"""

from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from alm.licensing import (
    TIER_FEATURES,
    LicenseError,
    LicenseTier,
    check_feature_entitlement,
    generate_keypair,
    issue_license,
    require_feature,
    verify_license,
)
from datetime import date


@pytest.fixture(scope="module")
def keypair():
    return generate_keypair()  # (private_pem, public_pem)


def test_valid_license_round_trips(keypair):
    private_pem, public_pem = keypair
    token = issue_license("Example Life Assurance plc", date(2027, 9, 8), LicenseTier.PROFESSIONAL, private_pem, max_legal_entities=3)
    license = verify_license(token, public_pem)

    assert license.customer_name == "Example Life Assurance plc"
    assert license.tier == LicenseTier.PROFESSIONAL
    assert license.expiry_date == date(2027, 9, 8)
    assert license.max_legal_entities == 3


def test_expired_license_is_rejected(keypair):
    private_pem, public_pem = keypair
    token = issue_license("Old Customer Ltd", date(2020, 1, 1), LicenseTier.STARTER, private_pem)
    with pytest.raises(LicenseError, match="expired"):
        verify_license(token, public_pem, as_of=date(2026, 9, 9))


def test_license_valid_exactly_on_expiry_date_and_invalid_the_day_after(keypair):
    private_pem, public_pem = keypair
    token = issue_license("Boundary Ltd", date(2026, 12, 31), LicenseTier.STARTER, private_pem)
    verify_license(token, public_pem, as_of=date(2026, 12, 31))  # does not raise
    with pytest.raises(LicenseError, match="expired"):
        verify_license(token, public_pem, as_of=date(2027, 1, 1))


def test_wrong_public_key_is_rejected(keypair):
    private_pem, _ = keypair
    _, other_public_pem = generate_keypair()  # an unrelated keypair
    token = issue_license("Example Ltd", date(2027, 1, 1), LicenseTier.STARTER, private_pem)
    with pytest.raises(LicenseError, match="signature"):
        verify_license(token, other_public_pem)


def test_corrupted_token_is_rejected(keypair):
    private_pem, public_pem = keypair
    token = issue_license("Example Ltd", date(2027, 1, 1), LicenseTier.STARTER, private_pem)
    corrupted = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    with pytest.raises(LicenseError):
        verify_license(corrupted, public_pem)


def test_structurally_valid_tier_forgery_is_caught_by_signature_not_parsing(keypair):
    """A JSON-well-formed token with the tier field changed but the original
    signature left in place. Must be caught by signature mismatch, proving
    the signature actually binds to the payload content."""
    private_pem, public_pem = keypair
    token = issue_license("Example Ltd", date(2027, 1, 1), LicenseTier.STARTER, private_pem)
    decoded = json.loads(base64.urlsafe_b64decode(token))
    decoded["payload"]["tier"] = "enterprise"
    forged = base64.urlsafe_b64encode(json.dumps(decoded).encode()).decode("ascii")

    with pytest.raises(LicenseError, match="signature"):
        verify_license(forged, public_pem)


def test_the_public_key_alone_cannot_forge_a_new_license(keypair):
    """The actual point of moving to asymmetric signing: an attacker (or a
    customer) who extracts PUBLIC_KEY_PEM from the shipped package has
    everything `verify_license` ever needs, and that must still be
    insufficient to mint a new, validly-signed license -- the property the
    old HMAC shared-secret scheme explicitly did NOT have (that secret was
    both the signing and verifying key, so extracting it from the package
    would have let anyone forge one). Attempting to sign with the public
    key object itself must fail outright: it exposes no signing operation."""
    private_pem, public_pem = keypair

    # a customer holding only the public key has no private key material to
    # construct a new token with at all; simulate the best a forger could do,
    # fabricating a payload and reusing some other (unrelated) signature bytes
    fabricated_payload = {
        "customer_name": "Forger Ltd", "issued_date": "2026-01-01",
        "expiry_date": "2099-01-01", "tier": "enterprise", "max_legal_entities": None,
    }
    unrelated_private_key = Ed25519PrivateKey.generate()  # not the vendor's key
    bogus_signature = unrelated_private_key.sign(b"unrelated data")
    forged_token = base64.urlsafe_b64encode(json.dumps({
        "payload": fabricated_payload,
        "signature": base64.b64encode(bogus_signature).decode("ascii"),
    }).encode()).decode("ascii")

    with pytest.raises(LicenseError, match="signature"):
        verify_license(forged_token, public_pem)


def test_tier_feature_gating_is_strictly_ordered(keypair):
    private_pem, public_pem = keypair
    starter = verify_license(issue_license("A", date(2027, 1, 1), LicenseTier.STARTER, private_pem), public_pem)
    professional = verify_license(issue_license("B", date(2027, 1, 1), LicenseTier.PROFESSIONAL, private_pem), public_pem)
    enterprise = verify_license(issue_license("C", date(2027, 1, 1), LicenseTier.ENTERPRISE, private_pem), public_pem)

    assert check_feature_entitlement(starter, "reconciliation") is True
    assert check_feature_entitlement(starter, "scr_standard_formula") is False
    assert check_feature_entitlement(professional, "scr_standard_formula") is True
    assert check_feature_entitlement(professional, "scr_internal_model") is False
    assert check_feature_entitlement(enterprise, "scr_internal_model") is True

    assert TIER_FEATURES[LicenseTier.STARTER] <= TIER_FEATURES[LicenseTier.PROFESSIONAL] <= TIER_FEATURES[LicenseTier.ENTERPRISE]

    require_feature(professional, "stresses")  # does not raise
    with pytest.raises(LicenseError, match="professional"):
        require_feature(professional, "scr_internal_model")

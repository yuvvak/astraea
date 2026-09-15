"""Self-hosted license entitlement. Since the product runs inside the
customer's own infrastructure rather than as a hosted service, there's no
server-side account to gate access against, so entitlement gets checked
locally against a license file the customer installs alongside the
software.

Signed with Ed25519 (asymmetric). `issue_license` signs with a private key
generated once and never shipped to a customer; `verify_license` checks
the signature against the matching public key, which is bundled in the
distributed package. This replaces an earlier HMAC-shared-secret version,
which was forgeable in principle since the shared secret would have had
to live inside every customer's installed copy. With asymmetric signing
the verifying side never holds anything it could also sign with.

`generate_keypair` and `issue_license` are vendor-side only, run once to
create the keypair and then once per sale to issue a license.
`verify_license`, `PUBLIC_KEY_PEM`, and everything else here is what
actually ships inside the customer's package.
"""

from __future__ import annotations

import base64
import json
from datetime import date
from enum import Enum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_pem_public_key,
)
from pydantic import BaseModel, ConfigDict


class LicenseTier(str, Enum):
    STARTER = "starter"        # single legal entity, reconciliation only
    PROFESSIONAL = "professional"  # multiple entities, reconciliation + stresses + SCR
    ENTERPRISE = "enterprise"  # unlimited entities, full feature set, internal-model interface


TIER_FEATURES: dict[LicenseTier, frozenset[str]] = {
    LicenseTier.STARTER: frozenset({"reconciliation", "ma_engine"}),
    LicenseTier.PROFESSIONAL: frozenset({"reconciliation", "ma_engine", "pra_tests", "stresses", "scr_standard_formula"}),
    LicenseTier.ENTERPRISE: frozenset({"reconciliation", "ma_engine", "pra_tests", "stresses", "scr_standard_formula", "scr_internal_model", "reporting"}),
}


class License(BaseModel):
    model_config = ConfigDict(frozen=True)

    customer_name: str
    issued_date: date
    expiry_date: date
    tier: LicenseTier
    max_legal_entities: int | None = None  # None = unlimited


class LicenseError(Exception):
    pass


def _canonical_payload(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def generate_keypair() -> tuple[str, str]:
    """Vendor-side, run once (or on key rotation). Returns (private_key_pem,
    public_key_pem). The private key must never be distributed; store it
    somewhere only the license-issuing process can reach. The public key is
    the one baked into the shipped package as `PUBLIC_KEY_PEM` below."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM, format=PrivateFormat.PKCS8, encryption_algorithm=NoEncryption(),
    ).decode("ascii")
    public_pem = private_key.public_key().public_bytes(
        encoding=Encoding.PEM, format=PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return private_pem, public_pem


def issue_license(
    customer_name: str,
    expiry_date: date,
    tier: LicenseTier,
    private_key_pem: str,
    issued_date: date | None = None,
    max_legal_entities: int | None = None,
) -> str:
    """Vendor-side only. `private_key_pem` is the secret half of a keypair
    from `generate_keypair`; it never ships to a customer."""
    private_key = load_pem_private_key(private_key_pem.encode("ascii"), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise LicenseError("private_key_pem must be an Ed25519 private key")

    payload = {
        "customer_name": customer_name,
        "issued_date": (issued_date or date.today()).isoformat(),
        "expiry_date": expiry_date.isoformat(),
        "tier": tier.value,
        "max_legal_entities": max_legal_entities,
    }
    signature = private_key.sign(_canonical_payload(payload).encode("utf-8"))
    token = {"payload": payload, "signature": base64.b64encode(signature).decode("ascii")}
    return base64.urlsafe_b64encode(json.dumps(token).encode("utf-8")).decode("ascii")


def verify_license(license_string: str, public_key_pem: str, as_of: date | None = None) -> License:
    """Customer-side. `public_key_pem` is the public half shipped with the
    package; it can verify a signature but cannot produce one, so a customer
    (or an attacker with the installed package) cannot forge a new license
    from it, unlike the old shared-secret scheme."""
    as_of = as_of or date.today()

    try:
        token = json.loads(base64.urlsafe_b64decode(license_string.encode("ascii")).decode("utf-8"))
        payload = token["payload"]
        signature = base64.b64decode(token["signature"])
    except Exception as exc:
        raise LicenseError(f"malformed license string: {exc}") from exc

    try:
        public_key: Ed25519PublicKey = load_pem_public_key(public_key_pem.encode("ascii"))
        public_key.verify(signature, _canonical_payload(payload).encode("utf-8"))
    except InvalidSignature as exc:
        raise LicenseError("license signature is invalid: this license was not issued with the expected key, or has been tampered with") from exc
    except Exception as exc:
        raise LicenseError(f"could not verify license signature: {exc}") from exc

    license = License(
        customer_name=payload["customer_name"],
        issued_date=date.fromisoformat(payload["issued_date"]),
        expiry_date=date.fromisoformat(payload["expiry_date"]),
        tier=LicenseTier(payload["tier"]),
        max_legal_entities=payload["max_legal_entities"],
    )

    if license.expiry_date < as_of:
        raise LicenseError(f"license for {license.customer_name!r} expired on {license.expiry_date.isoformat()}")

    return license


def check_feature_entitlement(license: License, feature: str) -> bool:
    return feature in TIER_FEATURES[license.tier]


def require_feature(license: License, feature: str) -> None:
    if not check_feature_entitlement(license, feature):
        raise LicenseError(
            f"the {license.tier.value!r} tier does not include {feature!r}; "
            f"available on: {[t.value for t in LicenseTier if feature in TIER_FEATURES[t]]}"
        )

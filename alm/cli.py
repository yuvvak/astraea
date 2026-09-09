"""Vendor-side license CLI (`alm-license` once the package is installed).
`generate-keypair` and `issue` are vendor-side operations, run wherever
licenses are issued from, never on a customer machine; `verify` is what a
customer (or this package's own startup code) runs, needing only the
public key.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from alm.licensing import LicenseError, LicenseTier, generate_keypair, issue_license, verify_license


def cmd_generate_keypair(args: argparse.Namespace) -> None:
    private_pem, public_pem = generate_keypair()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "private_key.pem").write_text(private_pem, encoding="utf-8")
    (out_dir / "public_key.pem").write_text(public_pem, encoding="utf-8")
    print(f"Keypair written to {out_dir}.")
    print("Keep private_key.pem secret and off any machine that ships to a customer.")
    print("Bundle public_key.pem with the distributed package.")


def cmd_issue(args: argparse.Namespace) -> None:
    private_pem = Path(args.private_key).read_text(encoding="utf-8")
    expiry = date.fromisoformat(args.expiry)
    tier = LicenseTier(args.tier)
    token = issue_license(args.customer, expiry, tier, private_pem, max_legal_entities=args.max_entities)
    if args.out:
        Path(args.out).write_text(token, encoding="utf-8")
        print(f"License written to {args.out}")
    else:
        print(token)


def cmd_verify(args: argparse.Namespace) -> None:
    public_pem = Path(args.public_key).read_text(encoding="utf-8")
    license_path = Path(args.license)
    token = license_path.read_text(encoding="utf-8").strip() if license_path.exists() else args.license

    try:
        license = verify_license(token, public_pem)
    except LicenseError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"VALID license for {license.customer_name}")
    print(f"  tier: {license.tier.value}")
    print(f"  issued: {license.issued_date.isoformat()}")
    print(f"  expires: {license.expiry_date.isoformat()}")
    print(f"  max legal entities: {license.max_legal_entities if license.max_legal_entities is not None else 'unlimited'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alm-license", description="Issue and verify self-hosted license tokens for the ALM engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gen = sub.add_parser("generate-keypair", help="Generate a new Ed25519 vendor keypair (run once, vendor-side)")
    p_gen.add_argument("--out-dir", default=".", help="Directory to write private_key.pem and public_key.pem into")
    p_gen.set_defaults(func=cmd_generate_keypair)

    p_issue = sub.add_parser("issue", help="Issue a signed license token (vendor-side; needs the private key)")
    p_issue.add_argument("--private-key", required=True, help="Path to private_key.pem")
    p_issue.add_argument("--customer", required=True)
    p_issue.add_argument("--tier", required=True, choices=[t.value for t in LicenseTier])
    p_issue.add_argument("--expiry", required=True, help="YYYY-MM-DD")
    p_issue.add_argument("--max-entities", type=int, default=None)
    p_issue.add_argument("--out", default=None, help="Write the license token to this file instead of stdout")
    p_issue.set_defaults(func=cmd_issue)

    p_verify = sub.add_parser("verify", help="Verify a license token (customer-side; needs only the public key)")
    p_verify.add_argument("--public-key", required=True, help="Path to public_key.pem")
    p_verify.add_argument("license", help="A license token string, or a path to a file containing one")
    p_verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()

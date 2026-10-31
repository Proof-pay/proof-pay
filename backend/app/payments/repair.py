"""Audit/repair existing allocations. Default dry-run; never attribute by address.

python -m app.payments.repair --invoice PP-1287C335 --dry-run
python -m app.payments.repair --invoice PP-1287C335 --apply
"""

import argparse
import json
import uuid
from typing import Any

from sqlmodel import Session, select

from app.core.db import engine
from app.models import Invoice, Receipt
from app.payments.chain import BCHNodeProvider
from app.payments.reconcile import reconcile_invoice
from app.payments.service import invoice_view, outputs, receipt_view


def repair_invoice(
    reference: str, provider: BCHNodeProvider, *, apply: bool = False
) -> dict[str, Any]:
    with Session(engine) as session:
        try:
            invoice_id = uuid.UUID(reference)
        except ValueError:
            invoices = session.exec(
                select(Invoice).where(Invoice.order_reference == reference)
            ).all()
        else:
            invoices = session.exec(
                select(Invoice).where(Invoice.id == invoice_id)
            ).all()
        if len(invoices) != 1:
            raise ValueError(
                "Invoice reference not found or ambiguous; use the invoice UUID"
            )
        invoice = session.exec(
            select(Invoice).where(Invoice.id == invoices[0].id).with_for_update()
        ).one()
        before = invoice_view(session, invoice).model_dump(mode="json")
        stored_before = {
            "status": invoice.status,
            "payment_status": invoice.payment_status,
        }
        checked, failures = reconcile_invoice(session, invoice, provider)
        after = invoice_view(session, invoice).model_dump(mode="json")
        receipt = session.exec(
            select(Receipt).where(Receipt.invoice_id == invoice.id)
        ).first()
        snapshot = (
            receipt_view(session, receipt).model_dump(mode="json") if receipt else None
        )
        refs = set(snapshot["output_refs"]) if snapshot else set()
        extra = [
            f"{p.txid}:{p.vout}"
            for p in outputs(session, invoice)
            if f"{p.txid}:{p.vout}" not in refs
        ]
        report = {
            "mode": "apply" if apply else "dry-run",
            "invoice_id": str(invoice.id),
            "stored_before": stored_before,
            "before": before,
            "after": after,
            "checked": checked,
            "provider_failures": failures,
            "receipt": snapshot,
            "allocations_outside_receipt": extra,
            "attribution_note": "Existing allocations are retained. Outputs outside the receipt require merchant review; chain verification cannot establish their intended invoice.",
        }
        # Do not print checkout/receipt bearer tokens as part of an audit report.
        for view in (before, after):
            for key in ("public_token", "checkout_url", "receipt_token", "payment_uri"):
                view.pop(key, None)
        if snapshot:
            snapshot.pop("public_token", None)
            snapshot.pop("verification_url", None)
        if apply:
            session.commit()
        else:
            session.rollback()
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--invoice", required=True, help="Invoice UUID or unambiguous order reference"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Persist provider-verified reconciliation of existing allocations",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Report proposed results and roll back (default)",
    )
    args = parser.parse_args()
    try:
        report = repair_invoice(args.invoice, BCHNodeProvider(), apply=args.apply)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))  # noqa: T201
    if report["provider_failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

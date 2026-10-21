from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api.deps import get_db
from app.api.routes import payments as payment_routes
from app.core.security import create_access_token
from app.main import app
from app.models import User
from app.payments.chain import (
    BCHNodeProvider,
    ProviderError,
    address_script_hex,
    bch_to_sats,
    normalize_address,
)
from app.payments.service import verify_transaction

ADDRESS = "bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a"
TX1 = "a" * 64
TX2 = "b" * 64
TX3 = "c" * 64


@pytest.fixture(name="db", autouse=True)
def no_shared_database():
    """These cases use their own isolated SQLite database."""
    yield


class FakeProvider:
    def __init__(self):
        self.transactions = {}
        self.failure = False

    def transaction(self, txid, network):
        if self.failure:
            raise ProviderError("unavailable")
        return {
            "txid": txid,
            "vout": self.transactions[txid]["vout"],
            "confirmations": self.transactions[txid]["confirmations"],
        }

    def set(self, txid, amounts, confirmations=0):
        self.transactions[txid] = {
            "vout": [
                {
                    "n": n,
                    "value": Decimal(value),
                    "scriptPubKey": {"addresses": [ADDRESS]},
                }
                for n, value in enumerate(amounts)
            ],
            "confirmations": confirmations,
        }


@pytest.fixture
def context(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        users = [
            User(email=f"merchant{n}@example.com", hashed_password="test")
            for n in range(2)
        ]
        session.add_all(users)
        session.commit()
        for user in users:
            session.refresh(user)

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = session_override
    fake = FakeProvider()
    monkeypatch.setattr(payment_routes, "BCHNodeProvider", lambda: fake)
    headers = [
        {"Authorization": f"Bearer {create_access_token(user.id, timedelta(hours=1))}"}
        for user in users
    ]
    with TestClient(app) as client:
        yield client, headers, fake
    app.dependency_overrides.clear()
    engine.dispose()


def create_invoice(
    client, headers, reference="INV-1", amount="1", expiry=None, key=None
):
    body = {
        "order_reference": reference,
        "title": "Design deposit",
        "description": "Public description",
        "amount_bch": amount,
        "receiving_address": ADDRESS,
    }
    if expiry:
        body["expires_at"] = expiry.isoformat()
    extra = {"Idempotency-Key": key} if key else {}
    return client.post("/api/v1/payment-requests", headers=headers | extra, json=body)


def test_address_precision_and_auth(context):
    client, headers, _ = context
    assert client.get("/api/v1/merchant/settings").status_code == 401
    assert normalize_address(ADDRESS, "mainnet") == ADDRESS
    with pytest.raises(ValueError):
        normalize_address(ADDRESS, "testnet")
    with pytest.raises(ValueError):
        normalize_address(ADDRESS[:-1] + "q", "mainnet")
    with pytest.raises(ValueError):
        bch_to_sats("0.000000001")
    bad = create_invoice(client, headers[0], amount="0.000000001")
    assert bad.status_code == 422
    assert (
        client.patch(
            "/api/v1/merchant/settings", headers=headers[0], json={"network": "testnet"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/merchant/settings",
            headers=headers[0],
            json={"receiving_address": ADDRESS},
        ).status_code
        == 200
    )


def test_node_network_and_locking_script(monkeypatch):
    provider = BCHNodeProvider(url="http://unused")
    tx = {
        "txid": TX1,
        "confirmations": 2,
        "vout": [
            {
                "n": 0,
                "value": Decimal("0.5"),
                "scriptPubKey": {
                    "hex": address_script_hex(ADDRESS, "mainnet"),
                    "addresses": [ADDRESS],
                },
            }
        ],
    }
    monkeypatch.setattr(
        provider,
        "_call",
        lambda method, params=None: (
            {"chain": "test", "initialblockdownload": False}
            if method == "getblockchaininfo"
            else tx
        ),
    )
    with pytest.raises(ProviderError):
        provider.transaction(TX1, "mainnet")
    monkeypatch.setattr(
        provider,
        "_call",
        lambda method, params=None: (
            {"chain": "main", "initialblockdownload": True}
            if method == "getblockchaininfo"
            else tx
        ),
    )
    with pytest.raises(ProviderError):
        provider.transaction(TX1, "mainnet")
    monkeypatch.setattr(
        provider,
        "_call",
        lambda method, params=None: (
            {"chain": "main", "initialblockdownload": False}
            if method == "getblockchaininfo"
            else tx
        ),
    )
    assert verify_transaction(provider, TX1, "mainnet", ADDRESS) == [(0, 50_000_000, 2)]
    tx["vout"][0]["scriptPubKey"]["hex"] = "00"
    assert verify_transaction(provider, TX1, "mainnet", ADDRESS) == []


def test_delete_only_unpublished_owned_drafts(context):
    client, headers, _ = context
    draft = create_invoice(client, headers[0], reference="DELETE-1").json()
    path = f"/api/v1/payment-requests/{draft['id']}"
    assert client.delete(path, headers=headers[1]).status_code == 404
    assert client.delete(path, headers=headers[0]).status_code == 204
    assert client.get(path, headers=headers[0]).status_code == 404

    issued = create_invoice(client, headers[0], reference="DELETE-2").json()
    issued_path = f"/api/v1/payment-requests/{issued['id']}"
    assert client.post(f"{issued_path}/issue", headers=headers[0]).status_code == 200
    assert client.delete(issued_path, headers=headers[0]).status_code == 409
    assert client.get(issued_path, headers=headers[0]).status_code == 200


def test_lifecycle_privacy_idempotency_and_ownership(context):
    client, headers, fake = context
    created = create_invoice(client, headers[0], key="once")
    assert created.status_code == 201, created.text
    invoice = created.json()
    assert invoice["status"] == "draft"
    assert (
        client.patch(
            f"/api/v1/payment-requests/{invoice['id']}",
            headers=headers[0],
            json={"status": "confirmed"},
        ).status_code
        == 422
    )
    assert create_invoice(client, headers[0], key="once").json()["id"] == invoice["id"]
    assert create_invoice(client, headers[0], amount="2", key="once").status_code == 409
    assert (
        client.get(
            f"/api/v1/payment-requests/{invoice['id']}", headers=headers[1]
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/public/payment-requests/{invoice['public_token']}"
        ).status_code
        == 404
    )
    issued = client.post(
        f"/api/v1/payment-requests/{invoice['id']}/issue", headers=headers[0]
    )
    assert issued.status_code == 200, issued.text
    assert (
        client.get(
            "/api/v1/payment-requests?status=pending", headers=headers[0]
        ).json()["count"]
        == 1
    )
    assert (
        client.patch(
            f"/api/v1/payment-requests/{invoice['id']}",
            headers=headers[0],
            json={"amount_bch": "2"},
        ).status_code
        == 409
    )
    public = client.get(
        f"/api/v1/public/payment-requests/{invoice['public_token']}"
    ).json()
    assert public["qr_payload"] == f"{ADDRESS}?amount=1"
    assert (
        "contact_email" not in public
        and "merchant_id" not in public
        and "public_token" not in public
    )
    assert (
        client.post(
            f"/api/v1/payment-requests/{invoice['id']}/cancel", headers=headers[0]
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/payment-requests/{invoice['id']}/issue", headers=headers[0]
        ).status_code
        == 409
    )
    fake.set(TX2, ["1"], 6)
    late = client.post(
        f"/api/v1/payment-requests/{invoice['id']}/claims/{TX2}", headers=headers[0]
    ).json()
    assert late["status"] == "cancelled"
    assert late["received_amount_sats"] == 0
    assert late["payments"][0]["is_late"] is True


def test_partial_excess_duplicate_confirmation_loss_and_dashboard(context):
    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    assert client.post(path + "/issue", headers=headers[0]).status_code == 200
    fake.set(TX1, ["0.25", "0.25"], 0)
    assert client.post(path + f"/claims/{TX1}", headers=headers[0]).status_code == 409
    first = client.post(
        path + f"/claims/{TX1}", headers=headers[0], json={"vouts": [0, 1]}
    )
    assert first.status_code == 200, first.text
    assert first.json()["payment_status"] == "partial"
    assert first.json()["received_amount_sats"] == 50_000_000
    assert client.post(path + "/cancel", headers=headers[0]).status_code == 409
    payment_id = first.json()["payments"][0]["id"]
    assert (
        client.get(f"/api/v1/payments/{payment_id}", headers=headers[1]).status_code
        == 404
    )
    again = client.post(
        path + f"/claims/{TX1}", headers=headers[0], json={"vouts": [0, 1]}
    )
    assert again.json()["received_amount_sats"] == 50_000_000
    fake.set(TX2, ["0.75"], 0)
    detected = client.post(path + f"/claims/{TX2}", headers=headers[0]).json()
    assert detected["payment_status"] == "detected"
    assert detected["received_amount_sats"] == 125_000_000
    assert client.get("/api/v1/receipts", headers=headers[0]).json()["count"] == 0
    fake.set(TX1, ["0.25", "0.25"], 1)
    fake.set(TX2, ["0.75"], 1)
    confirmed = client.post(path + f"/claims/{TX2}", headers=headers[0]).json()
    assert (
        confirmed["payment_status"] == "detected"
    )  # Other outputs are still unconfirmed.
    confirmed = client.post(
        path + f"/claims/{TX1}", headers=headers[0], json={"vouts": [0, 1]}
    ).json()
    assert confirmed["payment_status"] == "confirmed"
    receipt_token = confirmed["receipt_token"]
    receipt = client.get(f"/api/v1/public/receipts/{receipt_token}").json()
    assert receipt["amount_sats"] == 125_000_000
    assert receipt["current_status"] == "confirmed"
    assert "id" not in receipt and "public_token" not in receipt
    assert (
        client.get("/api/v1/receipts?search=Design", headers=headers[0]).json()["count"]
        == 1
    )
    assert (
        client.get("/api/v1/payments?search=Design", headers=headers[0]).json()["count"]
        == 3
    )
    assert client.get("/api/v1/receipts", headers=headers[1]).json()["count"] == 0
    summary = client.get("/api/v1/dashboard/summary", headers=headers[0]).json()
    assert summary["confirmed_received_sats"] == 125_000_000
    assert summary["outstanding_requested_sats"] == 0
    history = client.get(
        "/api/v1/dashboard/payment-history",
        headers=headers[0],
        params={
            "from_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "to_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert history.status_code == 200 and history.json()["count"] == 3
    fake.set(TX3, ["0.1"], 1)
    extra = client.post(path + f"/claims/{TX3}", headers=headers[0]).json()
    assert extra["confirmed_amount_sats"] == 135_000_000
    assert (
        client.get(f"/api/v1/public/receipts/{receipt_token}").json()["amount_sats"]
        == 125_000_000
    )
    fake.set(TX2, ["0.75"], 0)
    lost = client.post(path + f"/claims/{TX2}", headers=headers[0]).json()
    assert lost["payment_status"] == "detected"
    assert (
        client.get(f"/api/v1/public/receipts/{receipt_token}").json()["current_status"]
        == "detected"
    )
    other = create_invoice(client, headers[1], reference="INV-OTHER").json()
    client.post(f"/api/v1/payment-requests/{other['id']}/issue", headers=headers[1])
    assert (
        client.post(
            f"/api/v1/payment-requests/{other['id']}/claims/{TX1}",
            headers=headers[1],
            json={"vouts": [0]},
        ).status_code
        == 409
    )


def test_late_payment_and_provider_failure(context):
    client, headers, fake = context
    invoice = create_invoice(
        client, headers[0], expiry=datetime.now(UTC) + timedelta(hours=1)
    ).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.failure = True
    assert client.post(path + f"/claims/{TX1}", headers=headers[0]).status_code == 503
    assert client.get(path, headers=headers[0]).json()["payment_status"] == "pending"
    fake.failure = False
    # Simulate passage of time without sleeping or changing real database state.
    from app.payments import service

    original_now = service.now
    service.now = lambda: datetime.now(UTC) + timedelta(hours=2)
    try:
        fake.set(TX1, ["1"], 6)
        late = client.post(path + f"/claims/{TX1}", headers=headers[0])
        assert late.status_code == 200, late.text
        assert late.json()["status"] == "expired"
        assert late.json()["received_amount_sats"] == 0
        assert late.json()["payments"][0]["is_late"] is True
    finally:
        service.now = original_now

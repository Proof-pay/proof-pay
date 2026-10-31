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
from app.models import Merchant, User
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

    def watch_address(self, address, network):
        if self.failure:
            raise ProviderError("unavailable")

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
    from app.core.config import settings

    monkeypatch.setattr(settings, "BCH_NETWORK", "mainnet")
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

    assert create_invoice(client, headers[0], reference="DELETE-2").status_code == 201
    issued = client.post(
        "/api/v1/payment-requests",
        headers=headers[0],
        json={
            "order_reference": "DELETE-2",
            "title": "Fresh",
            "amount_bch": "1",
            "receiving_address": "bitcoincash:qr95sy3j9xwd2ap32xkykttr4cvcu7as4y0qverfuy",
        },
    ).json()
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
    # A second invoice cannot reserve the same destination, even for another merchant.
    assert create_invoice(client, headers[1], reference="INV-OTHER").status_code == 409


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


def test_discovery_restart_reorg_outage_and_public_privacy(context, monkeypatch):
    from sqlmodel import select

    from app.models import Invoice, PaymentOutput
    from app.payments import reconcile, worker
    from app.payments.chain import TransactionNotFound

    client, headers, fake = context
    # The same engine used by the API override, never the configured live database.
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(reconcile, "engine", test_engine)
    monkeypatch.setattr(worker, "BCHNodeProvider", lambda: fake)
    monkeypatch.setattr(reconcile, "BCHNodeProvider", lambda: fake)
    fake.incoming = lambda address, network: (
        list(fake.transactions)
        if not fake.failure
        else (_ for _ in ()).throw(ProviderError("offline"))
    )

    draft = create_invoice(client, headers[0], amount="1").json()
    assert (
        create_invoice(client, headers[0], reference="HISTORICAL-DRAFT").status_code
        == 201
    )
    path = f"/api/v1/payment-requests/{draft['id']}"
    assert client.post(path + "/issue", headers=headers[0]).status_code == 200
    public_path = f"/api/v1/public/payment-requests/{draft['public_token']}"
    fake.set(TX1, ["0.4"], 0)
    assert worker.discover() == (1, 0)
    checkout = client.get(public_path).json()
    assert checkout["received_amount_sats"] == 0
    assert client.get(path + "/detected", headers=headers[0]).json()[0]["txid"] == TX1
    assert client.post(path + f"/claims/{TX1}", headers=headers[0]).status_code == 200
    checkout = client.get(public_path).json()
    assert checkout["payment_status"] == "partial"
    assert checkout["amount_due_bch"] == "0.6"
    assert checkout["payment_uri"].endswith("amount=0.6")
    fake.set(TX2, ["0.8"], 1)
    fake.set(TX1, ["0.4"], 1)
    # Separate sessions/cycles recover the durable request and do not credit twice.
    assert worker.discover() == (1, 0)
    assert worker.discover() == (1, 0)
    assert reconcile.run_once() == (1, 0)
    assert client.post(path + f"/claims/{TX2}", headers=headers[0]).status_code == 200
    checkout = client.get(public_path).json()
    assert checkout["payment_status"] == "confirmed"
    assert checkout["overpaid_amount_sats"] == 20_000_000
    assert checkout["payment_uri"] is None
    token = checkout["receipt_url"].split("/")[-1]
    receipt = client.get(f"/api/v1/public/receipts/{token}").json()
    assert receipt["requested_amount_sats"] == 100_000_000
    assert all("invoice_id" not in p and "id" not in p for p in receipt["payments"])
    fake.failure = True
    assert worker.discover() == (0, 1)
    assert client.get(public_path).json()["payment_status"] == "confirmed"
    fake.failure = False
    original_transaction = fake.transaction

    def missing(txid, network):
        if txid == TX2:
            raise TransactionNotFound("removed")
        return original_transaction(txid, network)

    fake.transaction = missing
    assert reconcile.run_once()[0] == 2
    assert (
        client.get(f"/api/v1/public/receipts/{token}").json()["current_status"]
        == "partial"
    )
    with Session(test_engine) as session:
        assert len(session.exec(select(PaymentOutput)).all()) == 2
        invoice = session.exec(
            select(Invoice).where(Invoice.id == __import__("uuid").UUID(draft["id"]))
        ).one()
        invoice.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(invoice)
        session.commit()
    fake.transaction = original_transaction
    fake.set(TX3, ["0.1"], 1)
    assert worker.discover() == (1, 0)
    assert client.get(public_path).json()["late_amount_sats"] == 0
    assert client.post(path + f"/claims/{TX3}", headers=headers[0]).status_code == 200
    assert client.get(public_path).json()["late_amount_sats"] == 10_000_000
    exported = client.get("/api/v1/payments/export.csv", headers=headers[0])
    assert exported.status_code == 200
    assert TX3 in exported.text and "amount_sats" in exported.text
    assert TX3 not in client.get("/api/v1/payments/export.csv", headers=headers[1]).text


def test_issue_provider_failure_never_publishes(context):
    client, headers, fake = context
    draft = create_invoice(client, headers[0]).json()
    fake.failure = True
    assert (
        client.post(
            f"/api/v1/payment-requests/{draft['id']}/issue", headers=headers[0]
        ).status_code
        == 503
    )
    assert (
        client.get(
            f"/api/v1/public/payment-requests/{draft['public_token']}"
        ).status_code
        == 404
    )


def test_chipnet_network_is_not_testnet(monkeypatch):
    from app.payments.chain import PREFIXES

    provider = BCHNodeProvider(url="http://unused")
    monkeypatch.setattr(provider, "_call", lambda *args: {"chain": "test"})
    with pytest.raises(ProviderError, match="network mismatch"):
        provider.check_network("chipnet")
    monkeypatch.setattr(provider, "_call", lambda *args: {"chain": "chip"})
    provider.check_network("chipnet")
    assert PREFIXES["chipnet"] == "bchtest"


def test_node_watch_only_adapter_and_rpc_not_found(monkeypatch):
    import httpx

    from app.payments.chain import TransactionNotFound

    provider = BCHNodeProvider(url="http://unused")
    calls = []

    def rpc(method, params=None):
        calls.append((method, params))
        return {
            "getblockchaininfo": {"chain": "main", "initialblockdownload": False},
            "getwalletinfo": {"private_keys_enabled": False, "scanning": False},
            "importaddress": None,
            "getaddressinfo": {"iswatchonly": True},
            "listreceivedbyaddress": [{"txids": [TX1, TX1, TX2]}],
        }[method]

    monkeypatch.setattr(provider, "_call", rpc)
    provider.watch_address(ADDRESS, "mainnet")
    assert ("importaddress", [ADDRESS, "proofpay", False]) in calls
    assert provider.incoming(ADDRESS, "mainnet") == [TX1, TX2]
    assert calls[-1] == ("listreceivedbyaddress", [0, False, True, ADDRESS])
    monkeypatch.setattr(provider, "_call", lambda *args: {"private_keys_enabled": True})
    with pytest.raises(ProviderError, match="watch-only"):
        provider.check_watch_wallet()

    # BCHN reports missing transactions as JSON-RPC errors with HTTP 500.
    class RpcClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, *args, **kwargs):
            return httpx.Response(
                500,
                json={"error": {"code": -5, "message": "not found"}, "result": None},
            )

    monkeypatch.setattr(httpx, "Client", RpcClient)
    with pytest.raises(TransactionNotFound):
        BCHNodeProvider(url="http://unused")._call("getrawtransaction", [TX1, 1])


def test_token_aware_alias_cannot_reuse_destination(context):
    client, headers, _ = context
    # Vector checked against installed libauth 3.1.0-next.8 encodeCashAddress.
    token_alias = "bitcoincash:zpm2qsznhks23z7629mms6s4cwef74vcwvrqekrq9w"
    assert normalize_address(token_alias, "mainnet") == ADDRESS
    assert address_script_hex(token_alias, "mainnet") == address_script_hex(
        ADDRESS, "mainnet"
    )
    assert create_invoice(client, headers[0]).status_code == 201
    response = client.post(
        "/api/v1/payment-requests",
        headers=headers[1],
        json={
            "title": "Alias",
            "order_reference": "ALIAS",
            "amount_bch": "1",
            "receiving_address": token_alias,
        },
    )
    assert response.status_code == 409


def test_cashonize_token_aware_p2sh32_script():
    address = "bchtest:rvqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszqgpqyqszxv0zfkpe"
    assert address_script_hex(address, "chipnet") == "aa20" + "01" * 32 + "87"


def test_same_merchant_can_reuse_destination(context):
    client, headers, _ = context
    assert create_invoice(client, headers[0]).status_code == 201
    response = create_invoice(client, headers[0], reference="INV-2")
    assert response.status_code == 201


@pytest.mark.parametrize(
    "sqlstate,constraint,status",
    [
        ("23505", "uq_reserved_destination", 500),
        ("23505", "invoice_pkey", 500),
        ("23503", "uq_reserved_destination", 500),
    ],
)
def test_integrity_error_classification(
    context, monkeypatch, sqlstate, constraint, status
):
    from types import SimpleNamespace

    from sqlalchemy.exc import IntegrityError

    client, headers, _ = context
    assert (
        client.get("/api/v1/merchant/settings", headers=headers[0]).status_code == 200
    )
    error = Exception("private database details")
    error.sqlstate = sqlstate
    error.diag = SimpleNamespace(constraint_name=constraint)

    def fail_commit(_self):
        raise IntegrityError("INSERT", {}, error)

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = create_invoice(client, headers[0])
    assert response.status_code == status
    assert "already reserved" not in response.text
    assert "private database details" not in response.text


@pytest.mark.parametrize("amount", ["1", "2"])
def test_reuse_issue_edit_and_output_allocation(context, amount):
    client, headers, fake = context
    first = create_invoice(client, headers[0], reference="PROJECT-A").json()
    second = create_invoice(
        client, headers[0], reference="PROJECT-B", amount=amount
    ).json()
    paths = [f"/api/v1/payment-requests/{row['id']}" for row in [first, second]]
    # Case/prefix normalization and a draft edit both preserve merchant scope.
    edited = client.patch(
        paths[1],
        headers=headers[0],
        json={"receiving_address": ADDRESS.split(":")[1].upper()},
    )
    assert edited.status_code == 200 and edited.json()["receiving_address"] == ADDRESS
    watched = []
    fake.watch_address = lambda *args: watched.append(args)
    for path in paths:
        assert client.post(path + "/issue", headers=headers[0]).status_code == 200
    assert len(watched) == 1
    fake.set(TX1, ["1", amount], 1)
    review = client.get(paths[0] + f"/transactions/{TX1}", headers=headers[0])
    assert review.status_code == 200 and len(review.json()) == 2
    assert all(not row["allocated"] for row in review.json())
    for path in paths:
        assert client.get(path, headers=headers[0]).json()["received_amount_sats"] == 0
    assert client.get("/api/v1/receipts", headers=headers[0]).json()["count"] == 0
    assert (
        client.get(paths[0] + f"/transactions/{TX1}", headers=headers[1]).status_code
        == 404
    )
    assert client.get(paths[0] + f"/transactions/{TX1}").status_code == 401
    for path, vout in zip(paths, [0, 1], strict=True):
        claimed = client.post(
            path + f"/claims/{TX1}", headers=headers[0], json={"vouts": [vout]}
        )
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["status"] == "confirmed"
        repeated = client.post(
            path + f"/claims/{TX1}", headers=headers[0], json={"vouts": [vout]}
        )
        assert len(repeated.json()["payments"]) == 1
    conflict = client.post(
        paths[1] + f"/claims/{TX1}", headers=headers[0], json={"vouts": [0]}
    )
    assert conflict.status_code == 409 and "already allocated" in conflict.text
    assert client.get(paths[0] + "/detected", headers=headers[0]).json() == []
    assert create_invoice(client, headers[1]).status_code == 409


def test_invalid_verified_output_and_public_authority(context):
    from app.payments.chain import TransactionNotFound

    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 1)
    assert (
        client.post(
            path + f"/claims/{TX1}", headers=headers[0], json={"vouts": [99]}
        ).status_code
        == 422
    )
    assert client.post(path + f"/claims/{TX1}", json={"vouts": [0]}).status_code == 401
    assert (
        client.post(
            f"/api/v1/public/payment-requests/{invoice['public_token']}/claims/{TX1}"
        ).status_code
        == 404
    )
    fake.transactions[TX1]["vout"][0]["scriptPubKey"] = {"hex": "00"}
    assert client.post(path + f"/claims/{TX1}", headers=headers[0]).status_code == 422
    fake.transaction = lambda *args: (_ for _ in ()).throw(
        TransactionNotFound("missing")
    )
    assert (
        client.get(path + f"/transactions/{TX2}", headers=headers[0]).status_code == 422
    )
    assert client.post(path + f"/claims/{TX2}", headers=headers[0]).status_code == 422
    assert client.get(path, headers=headers[0]).json()["payments"] == []


def test_historical_cancelled_and_expired_destinations_never_auto_credit(
    context, monkeypatch
):
    from app.models import Invoice
    from app.payments import worker

    client, headers, fake = context
    historical = create_invoice(client, headers[0], reference="HISTORY").json()
    current = create_invoice(client, headers[0], reference="CURRENT").json()
    paths = [f"/api/v1/payment-requests/{row['id']}" for row in [historical, current]]
    for path in paths:
        client.post(path + "/issue", headers=headers[0])
    client.post(paths[0] + "/cancel", headers=headers[0])
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
        old = session.get(Invoice, __import__("uuid").UUID(historical["id"]))
        old.expires_at = datetime.now(UTC) - timedelta(days=1)
        session.add(old)
        session.commit()
    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(worker, "BCHNodeProvider", lambda: fake)
    calls = []
    fake.incoming = lambda *args: calls.append(args) or [TX1]
    fake.set(TX1, ["1"], 1)
    assert worker.discover() == (1, 0)
    assert len(calls) == 1
    for path in paths:
        row = client.get(path, headers=headers[0]).json()
        assert row["received_amount_sats"] == 0 and row["receipt_token"] is None
        assert not row["verification_stale"]
    claimed = client.post(paths[0] + f"/claims/{TX1}", headers=headers[0]).json()
    assert claimed["status"] == "cancelled" and claimed["received_amount_sats"] == 0
    assert claimed["payments"][0]["is_late"]


def test_deleted_draft_retains_merchant_association(context):
    client, headers, _ = context
    draft = create_invoice(client, headers[0]).json()
    client.delete(f"/api/v1/payment-requests/{draft['id']}", headers=headers[0])
    assert create_invoice(client, headers[0], reference="REUSE").status_code == 201
    assert create_invoice(client, headers[1]).status_code == 409


@pytest.mark.parametrize("ambiguous", [False, True])
def test_migration_preserves_records_and_blocks_unknown_history(context, ambiguous):
    import importlib
    import uuid

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlmodel import select

    from app.models import (
        AddressReservation,
        DetectedOutput,
        Invoice,
        PaymentOutput,
        Receipt,
    )

    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 1)
    client.post(path + f"/claims/{TX1}", headers=headers[0])
    client.get("/api/v1/merchant/settings", headers=headers[1])
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
        if ambiguous:
            original = session.get(Invoice, uuid.UUID(invoice["id"]))
            other = session.exec(
                select(Merchant).where(Merchant.id != original.merchant_id)
            ).one()
            session.add(
                Invoice(
                    merchant_id=other.id,
                    network="mainnet",
                    receiving_address=ADDRESS,
                    order_reference="LEGACY-SHARED",
                    expected_amount_sats=100000000,
                    expires_at=datetime.now(UTC) - timedelta(days=1),
                    status="cancelled",
                )
            )
            session.commit()
        before = {
            model.__tablename__: [
                row.model_dump() for row in session.exec(select(model)).all()
            ]
            for model in [Invoice, PaymentOutput, Receipt]
        }
        session.add(
            AddressReservation(
                network="mainnet", address="unknown-history", invoice_id=uuid.uuid4()
            )
        )
        session.commit()
    migration = importlib.import_module(
        "app.alembic.versions.7e91bc24a610_reusable_destinations"
    )
    with test_engine.begin() as connection:
        DetectedOutput.__table__.drop(connection)
        connection.execute(text("DROP INDEX ix_address_reservation_merchant_id"))
        connection.execute(
            text("ALTER TABLE address_reservation DROP COLUMN merchant_id")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    with Session(test_engine) as session:
        for model in [Invoice, PaymentOutput, Receipt]:
            assert [
                row.model_dump() for row in session.exec(select(model)).all()
            ] == before[model.__tablename__]
        rows = session.exec(select(AddressReservation)).all()
        assert len(rows) == 2
        assert (
            next(row for row in rows if row.address == ADDRESS).merchant_id is None
        ) == ambiguous
        assert (
            next(row for row in rows if row.address == "unknown-history").merchant_id
            is None
        )
    assert create_invoice(
        client, headers[0], reference="AFTER-MIGRATION"
    ).status_code == (409 if ambiguous else 201)
    assert create_invoice(client, headers[1]).status_code == 409
    assert client.post(path + f"/claims/{TX1}", headers=headers[0]).status_code == 200
    with pytest.raises(RuntimeError, match="Unsafe downgrade"):
        migration.downgrade()


def test_database_uniqueness_protects_racing_allocation(context):
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import select

    from app.models import Invoice, PaymentOutput

    client, headers, _ = context
    first = create_invoice(client, headers[0]).json()
    second = create_invoice(client, headers[0], reference="RACING").json()
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
    # Two sessions decide that the output is free before either inserts it.
    with Session(test_engine) as a, Session(test_engine) as b:
        assert a.exec(select(PaymentOutput)).first() is None
        assert b.exec(select(PaymentOutput)).first() is None
        invoices = {str(row.id): row for row in a.exec(select(Invoice)).all()}
        for session, invoice in [
            (a, invoices[first["id"]]),
            (b, invoices[second["id"]]),
        ]:
            session.add(
                PaymentOutput(
                    invoice_id=invoice.id,
                    network="mainnet",
                    txid=TX1,
                    vout=0,
                    amount_sats=100_000_000,
                    confirmations=1,
                    status="confirmed",
                )
            )
        a.commit()
        with pytest.raises(IntegrityError):
            b.commit()
        b.rollback()
    with Session(test_engine) as session:
        rows = session.exec(select(PaymentOutput)).all()
        assert len(rows) == 1 and str(rows[0].invoice_id) == first["id"]


def test_edit_different_draft_address_to_reused_destination(context):
    client, headers, _ = context
    assert create_invoice(client, headers[0]).status_code == 201
    other_address = "bitcoincash:qr95sy3j9xwd2ap32xkykttr4cvcu7as4y0qverfuy"
    draft = client.post(
        "/api/v1/payment-requests",
        headers=headers[0],
        json={
            "order_reference": "EDIT",
            "title": "Edit",
            "amount_bch": "2",
            "receiving_address": other_address,
        },
    ).json()
    path = f"/api/v1/payment-requests/{draft['id']}"
    changed = client.patch(
        path, headers=headers[0], json={"receiving_address": ADDRESS}
    )
    assert changed.status_code == 200 and changed.json()["receiving_address"] == ADDRESS
    assert client.post(path + "/issue", headers=headers[0]).status_code == 200
    # The edited-away destination remains associated with the original merchant.
    response = client.post(
        "/api/v1/payment-requests",
        headers=headers[1],
        json={
            "order_reference": "OTHER",
            "title": "Other",
            "amount_bch": "1",
            "receiving_address": other_address,
        },
    )
    assert response.status_code == 409


def test_receipt_evidence_is_exact_snapshot_not_later_invoice_payments(context):
    client, headers, fake = context
    invoice = create_invoice(client, headers[0], amount="0.001").json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["0.001"], 10)
    settled = client.post(path + f"/claims/{TX1}", headers=headers[0]).json()
    token = settled["receipt_token"]
    original = client.get(f"/api/v1/public/receipts/{token}").json()
    for txid, amount in [(TX2, "0.00001"), (TX3, "0.008")]:
        fake.set(txid, [amount], 1)
        assert (
            client.post(path + f"/claims/{txid}", headers=headers[0]).status_code == 200
        )
    receipt = client.get(f"/api/v1/public/receipts/{token}").json()
    assert receipt["amount_sats"] == 100000
    assert receipt["output_refs"] == [f"{TX1}:0"]
    assert [(p["txid"], p["vout"]) for p in receipt["payments"]] == [(TX1, 0)]
    assert receipt["verified_at"] == original["verified_at"]
    assert receipt["current_status"] == "confirmed"
    assert receipt["invoice_payment_status"] == "confirmed"
    assert client.get(path, headers=headers[0]).json()["received_amount_sats"] == 901000


def test_stored_status_drift_serializes_consistently_and_repair_is_dry_by_default(
    context, monkeypatch
):
    import uuid

    from app.models import Invoice, PaymentOutput
    from app.payments import repair, service

    client, headers, fake = context
    invoice = create_invoice(client, headers[0], reference="REPAIR-ME").json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 2)
    claimed = client.post(path + f"/claims/{TX1}", headers=headers[0]).json()
    checked_before = claimed["payments"][0]["last_checked_at"]
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
        stored = session.get(Invoice, uuid.UUID(invoice["id"]))
        stored.status = stored.payment_status = "pending"
        session.add(stored)
        session.commit()
    for url, auth in [
        (path, headers[0]),
        (f"/api/v1/public/payment-requests/{invoice['public_token']}", {}),
    ]:
        view = client.get(url, headers=auth).json()
        assert view["payment_status"] == view["status"] == "confirmed"
        assert view["confirmed_amount_sats"] == 100000000
    summary = client.get("/api/v1/dashboard/summary", headers=headers[0]).json()
    assert (
        summary["request_counts"]["confirmed"] == 1
        and summary["request_counts"]["pending"] == 0
    )
    receipt = client.get(f"/api/v1/public/receipts/{claimed['receipt_token']}").json()
    assert receipt["current_status"] == "confirmed"
    assert (
        client.get(
            "/api/v1/payment-requests?status=pending", headers=headers[0]
        ).json()["count"]
        == 0
    )
    assert (
        client.get(
            "/api/v1/payment-requests?status=confirmed", headers=headers[0]
        ).json()["count"]
        == 1
    )
    with Session(test_engine) as session:
        payment = session.get(PaymentOutput, uuid.UUID(claimed["payments"][0]["id"]))
        assert service.aware(payment.last_checked_at) == service.aware(
            datetime.fromisoformat(checked_before)
        )
    monkeypatch.setattr(repair, "engine", test_engine)
    monkeypatch.setattr(
        service, "now", lambda: datetime.now(UTC) + timedelta(minutes=1)
    )
    report = repair.repair_invoice("REPAIR-ME", fake)
    assert (
        report["mode"] == "dry-run" and report["stored_before"]["status"] == "pending"
    )
    assert report["after"]["status"] == "confirmed" and report["provider_failures"] == 0
    assert (
        "public_token" not in report["after"]
        and "verification_url" not in report["receipt"]
    )
    with Session(test_engine) as session:
        assert session.get(Invoice, uuid.UUID(invoice["id"])).status == "pending"
        assert service.aware(
            session.get(
                PaymentOutput, uuid.UUID(claimed["payments"][0]["id"])
            ).last_checked_at
        ) == service.aware(datetime.fromisoformat(checked_before))
    assert (
        repair.repair_invoice("REPAIR-ME", fake, apply=True)["after"]["status"]
        == "confirmed"
    )
    assert (
        repair.repair_invoice("REPAIR-ME", fake, apply=True)["after"][
            "received_amount_sats"
        ]
        == 100000000
    )
    with Session(test_engine) as session:
        assert session.get(Invoice, uuid.UUID(invoice["id"])).status == "confirmed"
    assert client.get("/api/v1/receipts", headers=headers[0]).json()["count"] == 1


def test_reconciliation_freshness_outage_and_settled_discovery_independence(
    context, monkeypatch
):
    from app.payments import reconcile, service

    client, headers, fake = context
    started = datetime.now(UTC)
    monkeypatch.setattr(service, "now", lambda: started)
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 1)
    settled = client.post(path + f"/claims/{TX1}", headers=headers[0]).json()
    receipt_path = f"/api/v1/public/receipts/{settled['receipt_token']}"
    with next(app.dependency_overrides[get_db]()) as session:
        monkeypatch.setattr(reconcile, "engine", session.get_bind())
    monkeypatch.setattr(reconcile, "BCHNodeProvider", lambda: fake)
    monkeypatch.setattr(service, "now", lambda: started + timedelta(minutes=4))
    fake.failure = True
    assert reconcile.run_once() == (1, 1)
    stale = client.get(receipt_path).json()
    assert stale["current_status"] == "confirmed" and stale["verification_stale"]
    assert datetime.fromisoformat(stale["verified_at"]) == started
    assert client.get(path, headers=headers[0]).json()["status"] == "confirmed"
    # Repeated HTTP requests cannot manufacture freshness.
    assert client.get(receipt_path).json()["verified_at"] == stale["verified_at"]
    fake.failure = False
    assert reconcile.run_once() == (1, 0)
    fresh = client.get(receipt_path).json()
    assert not fresh["verification_stale"] and fresh["current_status"] == "confirmed"
    assert datetime.fromisoformat(fresh["verified_at"]) == started + timedelta(
        minutes=4
    )
    # No address discovery was performed, but settled evidence is current.
    assert not client.get(path, headers=headers[0]).json()["verification_stale"]
    assert not client.get(
        f"/api/v1/public/payment-requests/{invoice['public_token']}"
    ).json()["verification_stale"]


def test_atomic_multiple_output_confirmation_threshold_and_reorg(context, monkeypatch):
    from app.payments import reconcile

    client, headers, fake = context
    client.patch(
        "/api/v1/merchant/settings",
        headers=headers[0],
        json={"required_confirmations": 2},
    )
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["0.4", "0.6"], 1)
    first = client.post(
        path + f"/claims/{TX1}", headers=headers[0], json={"vouts": [0, 1]}
    ).json()
    assert first["payment_status"] == "detected" and first["receipt_token"] is None
    with next(app.dependency_overrides[get_db]()) as session:
        monkeypatch.setattr(reconcile, "engine", session.get_bind())
    monkeypatch.setattr(reconcile, "BCHNodeProvider", lambda: fake)
    fake.set(TX1, ["0.4", "0.6"], 2)
    assert reconcile.run_once() == (2, 0)
    assert reconcile.run_once() == (2, 0)
    confirmed = client.get(path, headers=headers[0]).json()
    assert confirmed["status"] == confirmed["payment_status"] == "confirmed"
    assert (
        len(confirmed["payments"]) == 2
        and confirmed["received_amount_sats"] == 100000000
    )
    receipt_path = f"/api/v1/public/receipts/{confirmed['receipt_token']}"
    assert len(client.get(receipt_path).json()["payments"]) == 2
    assert client.get("/api/v1/receipts", headers=headers[0]).json()["count"] == 1
    fake.set(TX1, ["0.4", "0.6"], 1)
    assert reconcile.run_once() == (2, 0)
    assert client.get(path, headers=headers[0]).json()["status"] == "pending"
    assert client.get(receipt_path).json()["current_status"] == "detected"
    fake.set(TX1, ["0.4", "0.6"], -1)
    assert reconcile.run_once() == (2, 0)
    invalid = client.get(path, headers=headers[0]).json()
    assert invalid["received_amount_sats"] == 0
    assert all(p["status"] == "orphaned" for p in invalid["payments"])


def test_recheck_refreshes_prelock_output_before_provider_failure(context):
    import uuid

    from app.models import PaymentOutput
    from app.payments.service import aware, recheck_output

    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 0)
    result = client.post(path + f"/claims/{TX1}", headers=headers[0]).json()
    payment_id = uuid.UUID(result["payments"][0]["id"])
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
    with Session(test_engine) as waiting:
        stale_output = waiting.get(PaymentOutput, payment_id)
        fake.set(TX1, ["1"], 2)
        client.post(path + f"/claims/{TX1}", headers=headers[0])
        with Session(test_engine) as successful:
            timestamp = aware(successful.get(PaymentOutput, payment_id).last_checked_at)
        fake.failure = True
        assert recheck_output(waiting, stale_output, fake) is False
        waiting.commit()
        assert stale_output.confirmations == 2 and stale_output.status == "confirmed"
        assert aware(stale_output.last_checked_at) == timestamp


@pytest.mark.parametrize("discovery_finished", [False, True])
def test_worker_checks_allocated_evidence_while_discovery_is_slow_or_failing(
    monkeypatch, discovery_finished
):
    from concurrent.futures import Future
    from types import SimpleNamespace

    from app.payments import worker

    class LockConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, *args):
            return SimpleNamespace(scalar=lambda: True)

        def commit(self):
            pass

    class DiscoveryExecutor:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, *args):
            future = Future()
            if discovery_finished:
                future.set_result((0, 3))
            return future

    class EndTest(Exception):
        pass

    checks, sleeps = [], []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise EndTest

    monkeypatch.setattr(worker, "engine", SimpleNamespace(connect=LockConnection))
    monkeypatch.setattr(worker, "ThreadPoolExecutor", DiscoveryExecutor)
    monkeypatch.setattr(worker, "run_once", lambda: checks.append(True) or (3, 0))
    monkeypatch.setattr(worker.time, "monotonic", lambda: 0)
    monkeypatch.setattr(worker.time, "sleep", sleep)
    monkeypatch.setattr(worker.settings, "BCH_RECONCILIATION_INTERVAL_SECONDS", 60)
    with pytest.raises(EndTest):
        worker.main()
    assert len(checks) == 2 and sleeps == [60, 60]


def test_reconcile_does_not_issue_receipt_from_partly_rechecked_stale_evidence(
    context, monkeypatch
):
    from sqlmodel import select

    from app.models import PaymentOutput
    from app.payments import reconcile
    from app.payments.chain import TransactionNotFound

    client, headers, fake = context
    invoice = create_invoice(client, headers[0], amount="2").json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    for txid in (TX2, TX1):
        fake.set(txid, ["1"], 0)
        client.post(path + f"/claims/{txid}", headers=headers[0])
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
        # Historical drift: both rows say confirmed, but invoice has no receipt.
        for output in session.exec(select(PaymentOutput)).all():
            output.status, output.confirmations = "confirmed", 1
            session.add(output)
        session.commit()
    fake.set(TX2, ["1"], 1)
    original = fake.transaction

    def transaction(txid, network):
        if txid == TX1:
            raise TransactionNotFound("removed")
        return original(txid, network)

    fake.transaction = transaction
    monkeypatch.setattr(reconcile, "engine", test_engine)
    monkeypatch.setattr(reconcile, "BCHNodeProvider", lambda: fake)
    assert reconcile.run_once() == (2, 0)
    result = client.get(path, headers=headers[0]).json()
    assert result["payment_status"] == "partial" and result["receipt_token"] is None
    assert result["received_amount_sats"] == 100000000
    assert client.get("/api/v1/receipts", headers=headers[0]).json()["count"] == 0


def test_receipt_missing_snapshot_output_is_unavailable_and_never_fresh(context):
    import json
    import uuid

    from sqlmodel import select

    from app.models import Receipt

    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 1)
    result = client.post(path + f"/claims/{TX1}", headers=headers[0]).json()
    with next(app.dependency_overrides[get_db]()) as session:
        receipt = session.exec(
            select(Receipt).where(Receipt.invoice_id == uuid.UUID(invoice["id"]))
        ).one()
        receipt.output_refs = json.dumps([f"{TX1}:0", f"{TX2}:0"])
        session.add(receipt)
        session.commit()
    receipt = client.get(f"/api/v1/public/receipts/{result['receipt_token']}").json()
    assert receipt["missing_output_refs"] == [f"{TX2}:0"]
    assert receipt["current_status"] == "unavailable" and receipt["verification_stale"]
    assert receipt["verified_at"] is None


def test_later_payment_does_not_hide_reorg_of_original_receipt(context, monkeypatch):
    from app.payments import reconcile
    from app.payments.chain import TransactionNotFound

    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    for txid in (TX1, TX2):
        fake.set(txid, ["1"], 1)
        result = client.post(path + f"/claims/{txid}", headers=headers[0]).json()
    original = fake.transaction

    def transaction(txid, network):
        if txid == TX1:
            raise TransactionNotFound("removed")
        return original(txid, network)

    fake.transaction = transaction
    with next(app.dependency_overrides[get_db]()) as session:
        monkeypatch.setattr(reconcile, "engine", session.get_bind())
    monkeypatch.setattr(reconcile, "BCHNodeProvider", lambda: fake)
    assert reconcile.run_once() == (2, 0)
    receipt = client.get(f"/api/v1/public/receipts/{result['receipt_token']}").json()
    assert (
        receipt["current_status"] == "pending"
        and receipt["invoice_payment_status"] == "confirmed"
    )
    assert [p["txid"] for p in receipt["payments"]] == [TX1]
    assert client.get(path, headers=headers[0]).json()["status"] == "confirmed"


def test_review_reports_current_and_authorized_other_allocation_owner(context):
    client, headers, fake = context
    first = create_invoice(client, headers[0], reference="ACTUAL-OWNER").json()
    second = create_invoice(client, headers[0], reference="OTHER-REQUEST").json()
    paths = [f"/api/v1/payment-requests/{row['id']}" for row in [first, second]]
    for path in paths:
        client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 3)
    client.post(paths[0] + f"/claims/{TX1}", headers=headers[0])
    for index, path in enumerate(paths):
        review = client.get(path + f"/transactions/{TX1}", headers=headers[0]).json()[0]
        assert review["allocated"] and review["assigned_to_this_invoice"] == (
            index == 0
        )
        assert review["allocated_invoice_id"] == first["id"]
        assert review["allocated_order_reference"] == "ACTUAL-OWNER"
    assert (
        client.post(paths[1] + f"/claims/{TX1}", headers=headers[0]).status_code == 409
    )
    assert client.get(paths[1], headers=headers[0]).json()["received_amount_sats"] == 0
    assert (
        client.get(paths[1] + f"/transactions/{TX1}", headers=headers[1]).status_code
        == 404
    )


def test_monitoring_distinguishes_no_scan_failed_stale_and_successful_empty(
    context, monkeypatch
):
    import uuid

    from app.models import Invoice
    from app.payments import worker

    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    monitoring = client.get(path + "/monitoring", headers=headers[0]).json()
    assert monitoring["scan_status"] == "never" and monitoring["outputs"] == []
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(worker, "BCHNodeProvider", lambda: fake)

    def unavailable(*_args):
        raise ProviderError("offline")

    fake.incoming = unavailable
    assert worker.discover() == (0, 1)
    failed = client.get(path + "/monitoring", headers=headers[0]).json()
    assert (
        failed["scan_status"] == "failed" and failed["last_successful_scan_at"] is None
    )
    assert failed["outputs"] == []
    fake.incoming = lambda *args: []
    assert worker.discover() == (1, 0)
    assert (
        client.get(path + "/monitoring", headers=headers[0]).json()["scan_status"]
        == "current"
    )
    with Session(test_engine) as session:
        row = session.get(Invoice, uuid.UUID(invoice["id"]))
        row.last_scanned_at = row.scan_attempted_at = datetime.now(UTC) - timedelta(
            hours=1
        )
        session.add(row)
        session.commit()
    assert (
        client.get(path + "/monitoring", headers=headers[0]).json()["scan_status"]
        == "stale"
    )


def test_automatic_credit_only_for_forward_tracked_exclusive_destination(
    context, monkeypatch
):
    from sqlmodel import select

    from app.models import AddressReservation
    from app.payments import worker

    client, headers, fake = context
    first = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{first['id']}"
    client.post(path + "/issue", headers=headers[0])
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
        assert session.exec(select(AddressReservation)).one().auto_allocate
    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(worker, "BCHNodeProvider", lambda: fake)
    fake.incoming = lambda *args: list(fake.transactions)
    fake.set(TX1, ["0.4", "0.6"], 3)
    assert worker.discover() == (1, 0)
    assert worker.discover() == (1, 0)
    result = client.get(path, headers=headers[0]).json()
    assert (
        result["status"] == "confirmed" and result["received_amount_sats"] == 100000000
    )
    assert len(result["payments"]) == 2 and result["receipt_token"]
    second = create_invoice(client, headers[0], reference="REUSED-ADDRESS").json()
    second_path = f"/api/v1/payment-requests/{second['id']}"
    client.post(second_path + "/issue", headers=headers[0])
    fake.set(TX2, ["1"], 3)
    assert worker.discover() == (1, 0)
    assert (
        client.get(path, headers=headers[0]).json()["received_amount_sats"] == 100000000
    )
    assert (
        client.get(second_path, headers=headers[0]).json()["received_amount_sats"] == 0
    )
    detected = client.get(second_path + "/monitoring", headers=headers[0]).json()
    assert detected["scan_status"] == "current" and [
        row["txid"] for row in detected["outputs"]
    ] == [TX2]
    with Session(test_engine) as session:
        assert not session.exec(select(AddressReservation)).one().auto_allocate


def test_deleted_historical_draft_prevents_automatic_credit(context, monkeypatch):
    from app.payments import worker

    client, headers, fake = context
    old = create_invoice(client, headers[0]).json()
    client.delete(f"/api/v1/payment-requests/{old['id']}", headers=headers[0])
    current = create_invoice(
        client, headers[0], reference="AFTER-DELETED-HISTORY"
    ).json()
    path = f"/api/v1/payment-requests/{current['id']}"
    client.post(path + "/issue", headers=headers[0])
    with next(app.dependency_overrides[get_db]()) as session:
        monkeypatch.setattr(worker, "engine", session.get_bind())
    monkeypatch.setattr(worker, "BCHNodeProvider", lambda: fake)
    fake.incoming = lambda *args: [TX1]
    fake.set(TX1, ["1"], 3)
    assert worker.discover() == (1, 0)
    assert client.get(path, headers=headers[0]).json()["received_amount_sats"] == 0


def test_review_refreshes_existing_current_invoice_allocation_and_status(context):
    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    fake.set(TX1, ["1"], 0)
    assert (
        client.post(path + f"/claims/{TX1}", headers=headers[0]).json()["status"]
        == "pending"
    )
    fake.set(TX1, ["1"], 3)
    review = client.get(path + f"/transactions/{TX1}", headers=headers[0])
    assert review.status_code == 200 and review.json()[0]["assigned_to_this_invoice"]
    updated = client.get(path, headers=headers[0]).json()
    assert updated["status"] == updated["payment_status"] == "confirmed"
    assert updated["receipt_token"] and len(updated["payments"]) == 1


def test_exclusivity_migration_defaults_historical_single_request_to_manual(
    context, monkeypatch
):
    import importlib

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    from sqlmodel import select

    from app.models import AddressReservation
    from app.payments import worker

    client, headers, fake = context
    invoice = create_invoice(client, headers[0]).json()
    path = f"/api/v1/payment-requests/{invoice['id']}"
    client.post(path + "/issue", headers=headers[0])
    with next(app.dependency_overrides[get_db]()) as session:
        test_engine = session.get_bind()
    migration = importlib.import_module(
        "app.alembic.versions.a4d28e9f170c_track_exclusive_destinations"
    )
    with test_engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE address_reservation DROP COLUMN auto_allocate")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    with Session(test_engine) as session:
        assert not session.exec(select(AddressReservation)).one().auto_allocate
    monkeypatch.setattr(worker, "engine", test_engine)
    monkeypatch.setattr(worker, "BCHNodeProvider", lambda: fake)
    fake.incoming = lambda *args: [TX1]
    fake.set(TX1, ["1"], 3)
    assert worker.discover() == (1, 0)
    assert client.get(path, headers=headers[0]).json()["received_amount_sats"] == 0

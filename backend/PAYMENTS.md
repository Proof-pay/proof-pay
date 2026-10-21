# ProofPay payment API

All paths below have the `/api/v1` prefix. Existing login, registration, password reset, user administration, and item routes remain in place. The existing frontend payment pages still use their browser demo store; this backend is ready for a later frontend integration.

## Resource inventory

| Existing page or workflow | API |
| --- | --- |
| Merchant payment settings | `GET/PATCH /merchant/settings` |
| Create, browse, inspect, edit, issue, cancel links | `POST/GET /payment-requests`, `GET/PATCH/DELETE /payment-requests/{id}`, `POST /payment-requests/{id}/issue`, `POST /payment-requests/{id}/cancel` |
| Checkout, QR, polling status | `GET /public/payment-requests/{token}`, `GET /public/payment-requests/{token}/status` |
| Claim an observed transaction | `POST /payment-requests/{id}/claims/{txid}` with optional `{"vouts":[0,1]}` |
| Transaction history and detail | `GET /payments`, `GET /payments/{id}`, `GET /payment-requests/{id}` |
| Receipt list, detail, public proof | `GET /receipts`, `GET /receipts/{id}`, `GET /public/receipts/{token}` |
| Dashboard overview and date-range history | `GET /dashboard/summary`, `GET /dashboard/payment-history?from_at=...&to_at=...` |

There is no customer management or line-item form in the repository UI, so this MVP does not add those resources. Fiat reference fields are merchant-entered context only; there is no conversion provider or live exchange rate claim. Receiving-address control is not independently verified; a receipt does not establish who controls that address.

## Authentication and ownership

Merchant routes use the existing Bearer JWT dependency. A user has one merchant profile, created on first settings/payment request access. All merchant queries check the merchant ID, including payment and receipt detail. Public routes require 256-bit random URL tokens and return separate response schemas. Public checkout does not include merchant contact details, user email, internal IDs, or fiat reference values. Draft checkout is unavailable.

Amounts are decimal strings at the API boundary, converted to integer satoshis. Network is fixed for the deployment with `BCH_NETWORK`; merchant settings cannot switch it. Receiving addresses must pass the CashAddr checksum and configured-network prefix. Checkout `qr_payload` is the BCH payment URI, such as `bitcoincash:q...?...`, with the exact decimal BCH amount. This follows [CashAddr network prefixes](https://reference.cash/protocol/blockchain/encoding/cashaddr). The API returns URI data; it does not render an image.

## Lifecycle and attribution

`status` is the request lifecycle: `draft → pending → confirmed`, with `pending → expired` at the expiry time and `draft/pending → cancelled` while unpaid. A confirmation loss can move `confirmed → pending` or `expired`. The stored `payment_status` is `pending`, `partial`, `detected`, or `confirmed`. `partial` means at least one verified output but less than the requested total. `detected` means enough outputs were seen but the confirmed total is below the threshold. `confirmed` means confirmed eligible outputs meet or exceed the request. Editing is restricted to drafts; issuing freezes amount, address, reference, description, expiry, and confirmation policy. Cancelling after any claim is rejected.

`DELETE /payment-requests/{id}` permanently removes only an unpublished draft with no payment outputs or receipt. Issued requests remain in the database and can only be cancelled while unpaid.

This deployment uses a shared receiving address and **explicit transaction claims**. The merchant chooses the invoice and submits a candidate transaction ID. The server fetches the transaction from Bitcoin Cash Node, checks the node network, matching destination, output index, actual satoshis, and confirmations, then allocates each selected output under a `(network, txid, vout)` unique constraint. A transaction with multiple outputs to the address requires explicit `vouts`; amount matching never attributes an output automatically. Claims may be repeated safely. A payment after expiry or cancellation is retained as late evidence and does not settle the request. For safety, a first claim after expiry is treated as late even if the transaction may have appeared earlier; this shared-address setup cannot reliably prove when an unclaimed mempool payment first arrived. Overpayments are recorded in full; the request is satisfied at the threshold. A receipt snapshots the qualifying amount and output references when first confirmed. Later confirmation loss changes `current_status` on the receipt response, never the issued snapshot. A receipt proves observed BCH payment against a request, not goods delivery or payer identity.

Provider errors leave existing evidence in place and make `verification_stale` true after the configured freshness window. A confirmed transaction that disappears from a healthy node is marked orphaned and stops counting. Public polling reads the database only; it cannot invoke chain lookups. Authenticated claims make one bounded node lookup. Reconciliation repeats lookups for known outputs and expires due invoices. No transaction is broadcast and no private key or seed is stored.

## Provider and local setup

The adapter uses Bitcoin Cash Node JSON-RPC `getblockchaininfo` and `getrawtransaction` verbosity 1. The [node documentation](https://docs.bitcoincashnode.org/doc/json-rpc/getrawtransaction/) says `txindex=1` is needed for arbitrary historical transactions. [Chain info](https://docs.bitcoincashnode.org/doc/json-rpc/getblockchaininfo/) supplies the network and sync state. Mainnet, testnet, and regtest CashAddr prefixes are supported, one per deployment. Configure a trusted, synced node reachable only from the backend. Set `BCH_RPC_URL`, and `BCH_RPC_USER`/`BCH_RPC_PASSWORD` if the node uses HTTP Basic authentication. An absent provider returns 503 on claims; no fake success is enabled. Timeouts are eight seconds and there are no in-request retries. See root `.env.example` for the other settings: `BCH_NETWORK`, `BCH_REQUIRED_CONFIRMATIONS`, `BCH_RECONCILIATION_INTERVAL_SECONDS`, and `PUBLIC_CHECKOUT_BASE_URL`.

From the repository root, start the existing development database with `docker compose up -d db`. From `backend/`, run `../.venv/bin/alembic upgrade head` and `../.venv/bin/fastapi dev` after installing the existing Python dependencies. `scripts/prestart.sh` also applies migrations on backend startup. To check the migration on a separate safe database, point `DATABASE_URL` at that database and run `../.venv/bin/alembic upgrade head` followed by `../.venv/bin/alembic check`.

Schedule `cd backend && ../.venv/bin/python -m app.payments.reconcile` every `BCH_RECONCILIATION_INTERVAL_SECONDS` seconds using cron or the deployment scheduler. It processes at most 500 existing outputs and 500 due invoices per run. The command is repeatable. It does not scan a shared address for new transfers: a merchant must submit a transaction claim, and an unclaimed transfer cannot be attributed. There is no provider account, worker queue, or local demo success path.

## Example flow

```sh
# Replace TOKEN, UUID, public token, and transaction ID with actual values.
curl -H 'Authorization: Bearer TOKEN' -H 'Idempotency-Key: invoice-42' \
  -H 'Content-Type: application/json' -d '{"order_reference":"INV-42","title":"Design deposit","amount_bch":"0.05","receiving_address":"bitcoincash:qpm2qsznhks23z7629mms6s4cwef74vcwvy22gdx6a"}' \
  http://localhost:8000/api/v1/payment-requests
curl -X POST -H 'Authorization: Bearer TOKEN' http://localhost:8000/api/v1/payment-requests/UUID/issue
curl http://localhost:8000/api/v1/public/payment-requests/PUBLIC_TOKEN
curl http://localhost:8000/api/v1/public/payment-requests/PUBLIC_TOKEN/status
curl -X POST -H 'Authorization: Bearer TOKEN' http://localhost:8000/api/v1/payment-requests/UUID/claims/TXID
curl http://localhost:8000/api/v1/public/receipts/RECEIPT_TOKEN
```

The receipt URL is returned only after the required confirmations. List endpoints use bounded `limit` and `offset`; payment requests support search, status, and allowlisted sort fields. Payment history requires UTC-aware `from_at` and `to_at` values and permits at most 366 days per query.

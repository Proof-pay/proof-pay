# ProofPay payment API and operations

FastAPI + SQLModel/PostgreSQL own payment state. Merchant pages use JWT-authenticated
API data. Public checkout and receipt verification require only high-entropy tokens.
All paths below have the `/api/v1` prefix; API schemas are at `/docs`.

| Workflow | API |
| --- | --- |
| Business/receiving settings | `GET/PATCH /merchant/settings` |
| Create/list/search/filter requests | `POST/GET /payment-requests` |
| Inspect/edit/delete unpublished draft | `GET/PATCH/DELETE /payment-requests/{id}` |
| Publish/cancel | `POST /payment-requests/{id}/issue`, `POST /payment-requests/{id}/cancel` |
| Checkout/poll | `GET /public/payment-requests/{token}`, `GET /public/payment-requests/{token}/status` |
| Investigate a transaction hint | `POST /payment-requests/{id}/claims/{txid}` (optional `{"vouts":[0,1]}`) |
| Transactions/export | `GET /payments`, `GET /payments/{id}`, `GET /payments/export.csv` |
| Receipts | `GET /receipts`, `GET /receipts/{id}`, `GET /public/receipts/{token}` |
| Dashboard | `GET /dashboard/summary`, `GET /dashboard/payment-history` |

Lists use bounded `limit`/`offset`; search and allowlisted sort fields are supported.
Creation accepts an `Idempotency-Key` header. Editing is restricted to drafts.
Issuing freezes the destination, amount, deployment network, expiry and confirmation
policy. Merchant-setting changes cannot rewrite issued requests.

## Destinations and accounting

Each request requires a **fresh merchant-wallet address**, supplied from that
wallet's receive screen. ProofPay permanently reserves `(network, address)` in
one database transaction with request creation. Reservation survives draft deletion,
cancellation and expiry. A concurrent reuse fails with 409; use a new wallet address.
The application has no spending keys and never creates a custodial wallet.

This is explicit address allocation, not automatic HD derivation. Generate addresses
sequentially in the merchant wallet and respect its recovery gap limit. Do not paste
arbitrarily far-ahead derived addresses. Verify the address and network in the wallet
before issuing. Receiving-address control is not independently proven. A configured
settings address identifies the receiving wallet and is a default for API clients;
it can be used only once, not shared across requests.

Amounts are BCH decimal strings at input and integer satoshis in storage. Fiat
reference fields are descriptive merchant-entered context, not fiat-denominated
quotes; there is no conversion or exchange-rate claim. Checkout QR/URI requests the
remaining amount after partial funding. No payment URI is returned once fully funded,
confirmed, expired or cancelled.

Lifecycle (`draft/pending/expired/cancelled/confirmed`) is separate from funding
(`pending/partial/detected/confirmed`). Detection never means confirmation. Outputs
are independently checked against the exact locking script and actual amount.
`(network, txid, vout)` is globally unique. Duplicate reconciliation cannot credit twice.
Overpayments are retained in full. New money first observed after expiry/cancellation
is retained as late evidence, excluded from settlement, and needs merchant review.
After a provider outage, discovery time may be later than actual arrival; classification
is deliberately conservative rather than inventing an earlier mempool observation.
Money detected before expiry may still satisfy confirmation policy after expiry.

Receipts snapshot qualifying outputs when settlement first satisfies confirmation
policy. The public verification response includes current evidence and status, so
confirmation loss/orphaning corrects the live proof. The issued amount remains a
snapshot. A receipt verifies blockchain payment to the recorded destination; it
proves neither goods delivery nor payer identity. Public responses exclude internal
payment/invoice IDs, contact details, xpubs and session data.

## BCH Node setup

Use a trusted, synchronized **Bitcoin Cash Node** with `txindex=1`, a persistent data
directory, and a dedicated **watch-only wallet with private keys disabled**. RPC must
be reachable from both backend and worker; do not expose it to the public internet.
Create the empty wallet with `bitcoin-cli createwallet proofpay-watch true true`.
Load it on node startup and point `BCH_RPC_URL` at its wallet-specific RPC URL,
for example `http://bchn:48332/wallet/proofpay-watch` for Chipnet. Configure RPC
authentication using `BCH_RPC_USER` and `BCH_RPC_PASSWORD`.

The adapter checks `getblockchaininfo` network/sync state and watch-wallet health.
Before publishing checkout, `importaddress(address, "proofpay", false)` installs a
watch. New addresses need no historical rescan because they have never been shared.
`listreceivedbyaddress(0, false, true, address)` discovers candidate txids including
unconfirmed receipts. Its balances are **never used for credit**. Every candidate is
fetched through `getrawtransaction(txid, 1)` and outputs independently verified.
Missing watched addresses fail visibly rather than silently reporting an empty history.

| Environment | Meaning |
| --- | --- |
| `BCH_NETWORK` | `mainnet`, `testnet` (testnet3), `chipnet`, or `regtest` |
| `BCH_RPC_URL` | Wallet-specific BCHN RPC URL; blank fails closed on issuing/claims |
| `BCH_RPC_USER`, `BCH_RPC_PASSWORD` | RPC Basic authentication |
| `BCH_REQUIRED_CONFIRMATIONS` | Default new-merchant threshold, minimum 1 |
| `BCH_RECONCILIATION_INTERVAL_SECONDS` | Poll interval, default 60 |
| `PUBLIC_CHECKOUT_BASE_URL` | External application origin for checkout/receipt URLs |

Chipnet shares the `bchtest:` CashAddr prefix with testnet but has distinct node chain
ID `chip`; the backend checks it explicitly. Regtest has no public explorer link.
Network-aware explorer routes follow [BlockExplorer.cash's route documentation](https://blockexplorer.cash/llms.txt).

Provider references: [importaddress](https://docs.bitcoincashnode.org/doc/json-rpc/importaddress/),
[listreceivedbyaddress](https://docs.bitcoincashnode.org/doc/json-rpc/listreceivedbyaddress/),
[getrawtransaction](https://docs.bitcoincashnode.org/doc/json-rpc/getrawtransaction/),
[createwallet](https://docs.bitcoincashnode.org/doc/json-rpc/createwallet/),
[network IDs](https://github.com/bitcoin-cash-node/bitcoin-cash-node/blob/master/src/chainparamsbase.cpp).

## Deployment, recovery and migration

`docker compose up --build -d` starts PostgreSQL, the API/frontend and one independent
`payment-worker`. Backend startup applies Alembic migrations and initial user setup;
the worker starts only after backend health succeeds. It uses a PostgreSQL session
advisory lock so duplicate worker replicas cannot create competing watchers. API
workers never start watchers. The polling worker discovers up to 100 requests and
rechecks up to 500 outputs per cycle in durable oldest-attempt-first order. Failed
items move to the back of the queue without refreshing verification timestamps.
Failures retry with capped backoff; each HTTP request has an eight-second timeout.
Logs contain request IDs and counters, not wallet sessions, addresses or RPC secrets.

A restart resumes from database state and the node's persistent watch wallet,
including expired/cancelled/confirmed destinations to retain late/additional transfers.
Rechecks detect confirmation loss and missing transactions; provider outages retain
last-known evidence and eventually flag it stale (at least 120 seconds or three poll
intervals). A large backlog increases detection latency; size the single worker/node
for the deployment. Do not also schedule legacy reconciliation cron jobs.

Back up PostgreSQL and the BCH node watch wallet. If that wallet is lost, restore it,
or import all issued destinations and run the node's `rescanblockchain` from before
the earliest issue before resuming the worker. Importing without rescan cannot recover
payments received while the watch was missing. Never replace the watch wallet with a
wallet holding private keys.

Migration `3c68e4b2a910` permanently reserves existing destinations. Existing issued
invoices retain manual claims and rechecking; they are not automatically watched,
because earlier versions allowed shared addresses. Do not guess how to attribute
legacy shared-address history. Duplicate legacy drafts must be edited to a new
address before issue. Existing transactions/receipts remain intact.

For a production stack use `docker compose -f compose.yml -f compose.deploy.yml up
--build -d` after configuring domain/TLS and secrets. Docker Compose development
overrides are not intended for production. Validate migrations against a backed-up
or isolated PostgreSQL database before upgrading an existing deployment.

## Validation and remaining work

Payment regression tests use an isolated SQLite database and provider doubles. They
cover privacy/ownership, accounting, duplicate destination/output rejection, discovery
across cycles, outages, reorg correction, late payments and CSV. SDK and browser tests
cover pairing lifecycle and public checkout polling/remaining amounts/mobile layout.
These tests do **not** establish live BCHN/Cashonize interoperability.

WizardConnect currently provides connection, cancellation, disconnect, timeout and
session restoration only. Customer payment uses a standard BCH payment URI/QR and
approval inside the external wallet. **WizardConnect transaction construction/signing,
automatic HD allocation and a real wallet payment demonstration remain unfinished.**
The installed hdwalletv1 handshake does not attest the active network. No fake
signature/payment result is substituted. See the [wallet integration notes](../frontend/src/features/wallet/README.md)
and [completion checklist](../docs/completion-checklist.md).

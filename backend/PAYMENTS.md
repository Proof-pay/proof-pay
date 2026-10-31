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

Requests can reuse a merchant-supplied **BCH receiving address**, including identical
amounts. Permanent `(network, address)` associations now protect merchant isolation;
they survive edits, draft deletion, cancellation and expiry. Another merchant cannot
claim that destination. Unknown or conflicting historical ownership is blocked.
Entering an address is not proof of wallet control. Verify the address and network
in your wallet. ProofPay has no spending keys and never generates keys or wallets.

New destinations can be credited automatically while tracked as associated with
exactly one request. Any reuse permanently disables that policy; historical
associations default to merchant review because exclusivity cannot be proven.
Migration `a4d28e9f170c` adds this permission, false for all historical rows.
Detection stores separate observations; only authorized allocation enters totals
and receipts. Automatic allocation holds the invoice and association locks, so a
concurrent reuse cannot race an exclusivity decision. The request detail
screen lets merchants select a detected transaction or enter an ID, review verified
outputs, and assign selected vouts. Claims reverify through BCHN and never move
existing allocations. Public checkout tokens cannot allocate payments. See
[address reuse, API details and deployment](../docs/reusable-bch-addresses.md).

Amounts are BCH decimal strings at input and integer satoshis in storage. Fiat
reference fields are descriptive merchant-entered context, not fiat-denominated
quotes; there is no conversion or exchange-rate claim. Checkout QR/URI requests the
remaining amount after partial funding. No payment URI is returned once fully funded,
confirmed, expired or cancelled.

Lifecycle (`draft/pending/expired/cancelled/confirmed`) is separate from funding
(`pending/partial/detected/confirmed`). Detection never means confirmation. Outputs
are independently checked against the exact locking script and actual amount.
`(network, txid, vout)` is globally unique. Duplicate reconciliation cannot credit twice.
Overpayments are retained in full. New outputs first allocated after expiry/cancellation
is retained as late evidence, excluded from settlement, and needs merchant review.
After a provider outage, discovery time may be later than actual arrival; classification
is deliberately conservative rather than inventing an earlier mempool observation.
Outputs allocated before expiry may still satisfy confirmation policy after expiry.
Allocation after expiry is conservatively late even if a prior observation exists.

Receipts snapshot qualifying outputs when settlement first satisfies confirmation
policy. The evidence list, last successful verification time, freshness and receipt
status refer only to those frozen `(txid, vout)` references; later invoice allocations
remain visible on the merchant detail screen. Receipt evidence status and overall
invoice payment status are returned separately. An invalidated receipt output is
not silently replaced by a subsequent payment. The public verification response includes current evidence and status, so
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
watch. Reusing an already watched destination avoids repeated imports. To discover
payments predating the initial watch, rescan the watch wallet or review a transaction
ID directly (with `txindex=1`).
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
workers never start watchers. The polling worker discovers up to 100 distinct destinations and
rechecks up to 500 outputs per cycle in durable oldest-attempt-first order. Failed
items move to the back of the queue without refreshing verification timestamps.
Allocated-output checks run at the configured interval independently of address
discovery. Discovery runs in one separate thread under the same process advisory
lock, so a slow scan or failed destination cannot impose a global backoff on known
payment evidence. Each provider HTTP request has an eight-second timeout.
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

Migration `7e91bc24a610` adds merchant scope to historical reservations and creates
unassigned observations. It preserves allocations/receipts and blocks ambiguous or
unknown ownership. Existing legacy destinations are not watched automatically;
restore/import and rescan their watch history as needed. Same-merchant legacy drafts
can issue to reused addresses. Stop old API/workers before deploying this migration
and new code together; old workers must not run the automatic allocation policy.
The migration requires an online connection and rejects unsafe downgrade.

For a production stack use `docker compose -f compose.yml -f compose.deploy.yml up
--build -d` after configuring domain/TLS and secrets. Docker Compose development
overrides are not intended for production. Validate migrations against a backed-up
or isolated PostgreSQL database before upgrading an existing deployment.

## Validation and remaining work

Payment regression tests use an isolated SQLite database and provider doubles. They
cover privacy/ownership, accounting, merchant-scoped destination reuse and duplicate output rejection, discovery
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


## Verification consistency and repair

All invoice views, public checkout, dashboard counts and status filters calculate
funding from allocated integer satoshis and the invoice confirmation threshold.
Persisted state is updated by claims and invoice-level reconciliation in the same
transaction. Reading an API response never refreshes chain verification timestamps.
Provider failure preserves the previous evidence; successful checks (including a
definitive missing/conflicted transaction) update its timestamp and current status.
Completed outputs continue to be polled indefinitely for reorgs. A completed invoice
does not require a recent address-discovery scan to prove its existing payments.

Freshness is separate from payment status: evidence is stale after
`max(120, 3 * BCH_RECONCILIATION_INTERVAL_SECONDS)` seconds. A stale confirmed receipt
still reports its last known confirmed state, with a freshness warning. With the
default 60-second interval this threshold is 180 seconds. Do not extend it merely
to mask a failed or old worker. `verified_at` is the oldest successful check among
credited receipt outputs, or null if snapshot evidence is incomplete.

For a safe audit, from `backend`:

```sh
uv run python -m app.payments.repair --invoice PP-1287C335 --dry-run
```

Dry-run is the default and rolls back all proposed changes. The report includes
stored versus calculated status, verification failures, frozen receipt evidence,
and allocations outside the receipt. No output is attributed, moved, or deleted.
After reviewing and explicitly approving record reconciliation, use `--apply`.
The command is idempotent and preserves receipt snapshots and allocation history.
An output outside the receipt may be a legitimate later payment or a historical
misallocation; the chain cannot determine merchant intent. Such allocations need
merchant review, not automatic reassignment.

The FastAPI development reloader does not reload an existing worker. Stop the old
worker and restart `uv run python -m app.payments.worker` after updating payment
code or `.env`. Compose runs a dedicated `payment-worker` service; rebuild/recreate
it with the API. Vercel's serverless API does not run this durable worker: deploy
it as a separate long-running process with the same database, network, and BCH RPC
configuration. See [development startup](../development.md).


Allocation review identifies “Allocated to this request” or “Allocated to another
request”. Owner IDs/references are returned only to an authorized merchant. The
monitoring endpoint reports saved observations and scan health separately; an empty
list after a failed/absent scan is not reported as successful payment discovery.
The header's “Connecting wallet…” is WizardConnect, not the payment provider or an
event stream. Server polling/verification does not depend on wallet connectivity.

# Reusable BCH receiving addresses

One merchant can create, edit, and issue multiple requests to the same normalized
CashAddr on the same network, including requests with identical amounts. Address
associations persist after draft deletion and address edits. Entering an address
is not proof of wallet ownership; ProofPay retains its existing first-association
merchant isolation and blocks other merchants from using it.

Newly registered destinations can be credited automatically while associated with
exactly one ProofPay request. Migration `a4d28e9f170c` tracks that permission going
forward; any second request permanently disables it, including a draft that is
later deleted or edited away. Historical destinations start with this permission
disabled because their exclusivity cannot be proven. They require authenticated
merchant review, even when only one request is currently pending. Amounts, request
age, and pending status never select an invoice automatically. Existing verified
allocations and receipt snapshots are preserved.

The worker imports/watches destinations through the existing BCHN watch-only
provider and scans each destination once per cycle. It stores observations in
`detected_output`, independently of `payment_output`. Observations never enter
invoice totals, the payments export, dashboard income, or receipts. Only an explicit
merchant allocation or the forward-tracked exclusive policy can credit an output. Existing
allocated outputs continue through the confirmation/reorg reconciliation worker.

On the payment-request detail screen, select a detected transaction or enter its
ID, verify its outputs, then select and assign eligible outputs to the request.
The claim re-verifies the transaction through BCHN; displayed evidence alone does
not authorize credit. Late/cancelled allocations remain recorded as late and do
not settle the invoice. Public checkout tokens grant no allocation authority.

Authenticated API endpoints:

- `GET /api/v1/payment-requests/{id}/detected`: latest 100 unassigned observations
  for the destination. Confirmations are observations as of `last_checked_at`;
  outputs are reverified before allocation.
- `GET /api/v1/payment-requests/{id}/monitoring`: saved outputs plus scan status
  (`never`, `failed`, `stale`, `current`), attempt time and last successful scan.
  Empty observations do not establish a successful scan.
- `GET /api/v1/payment-requests/{id}/transactions/{txid}`: verify and review matching
  outputs, including existing allocation state and the owner ID/reference when the
  current merchant may view it. Existing allocations to this request are also
  reverified and its status refreshed; other allocations are never moved.
- `POST /api/v1/payment-requests/{id}/claims/{txid}`, body `{"vouts": [0]}`:
  reverify and allocate selected outputs. Repeats for the same invoice are
  idempotent; allocation to another invoice returns HTTP 409. The database's
  unique `(network, txid, vout)` key protects concurrent allocations.

## Deployment

Stop old API and payment-worker processes before migration: old workers use the
previous automatic-allocation policy. Back up PostgreSQL using your usual backup
procedure. From the repository root, with the deployment `.env` configured:

```sh
cd backend
uv run alembic upgrade head
```

Migration `a4d28e9f170c` adds forward exclusivity tracking (false for all existing
associations). Apply it before restarting new API/worker processes. Migration
`7e91bc24a610` adds merchant scope to permanent destination associations
and creates the observation table. It inspects all historical invoices and old
reservations. Missing or conflicting merchant history blocks new use/claims at
that destination; existing allocations can still be rechecked. It preserves
invoice, output, receipt, and reservation records. The destination unique key
remains necessary for merchant isolation; it no longer means invoice exclusivity.
This data migration requires an online database connection. Downgrade is rejected
because restoring the old automatic allocation policy after reuse is unsafe.

For Compose deployment, rebuild before starting the new API and worker together:

```sh
docker compose stop backend payment-worker
docker compose build backend payment-worker
docker compose run --rm --no-deps backend alembic upgrade head
docker compose up -d backend payment-worker
```

For native development, restart the API and run `uv run python -m
app.payments.worker` from `backend` after migration. No wallet keys, seed phrases,
or real BCH transactions are needed for tests.

## Validation

```sh
cd backend
uv run pytest tests/api/routes/test_payments.py -q
uv run mypy app
uv run ty check app
uv run ruff check app tests/api/routes/test_payments.py
cd ../frontend
bunx biome check .
bun run build
bunx playwright test --config playwright.wallet.config.ts tests/wallet/payments.spec.ts
```

The complete backend suite needs PostgreSQL. Use an isolated test database:
its shared fixtures create users and delete test records. The payment regression
module uses its own SQLite database and deterministic providers.

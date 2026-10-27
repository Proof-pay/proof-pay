# ProofPay

A non-custodial Bitcoin Cash payment-request application for merchants and
freelancers. Payments go directly to the merchant wallet. FastAPI and a separate
reconciliation worker independently verify blockchain outputs; the browser cannot
mark a request paid.

The application uses React, TypeScript, Vite, TanStack Query/Router, Tailwind and
Bun, with FastAPI, SQLModel, PostgreSQL, Alembic and Docker Compose. The merchant UI
preserves the Emerald Trust theme.

## Current journey

Register/sign in → configure merchant settings → generate a fresh address in your
BCH wallet → create a fixed-amount request → share its checkout link/QR → customer
approves payment in a compatible wallet → backend detects and confirms payment →
merchant dashboard and shareable printable receipt update.

Implemented: persistent requests, draft editing, issuing/cancellation, search,
filters/pagination, downloadable QR, live checkout polling, partial/late/overpayment
reporting, confirmation tracking/reorg correction, receipts, transaction CSV export,
responsive navigation, password/session management and existing Google OAuth.

WizardConnect connection/session handling is present. **WizardConnect payment signing
and automatic HD address derivation are still unfinished.** The current payment flow
uses standard BCH URIs. Fresh addresses are supplied by the merchant and permanently
reserved by the backend. See the [completion checklist](docs/completion-checklist.md)
for verification status and limits; this is not yet a fully verified end-to-end release.

## Run locally

Requires Python 3.14/uv, Bun and PostgreSQL (or Docker). Copy `.env.example` to `.env`
and configure database/authentication values. For actual payment processing, configure
a synchronized BCH Node with `txindex=1` and a persistent wallet with private keys
disabled. See [payment provider setup](backend/PAYMENTS.md). An unconfigured provider
fails closed when a request is issued; no simulated payments are enabled.

```sh
bun install
uv sync
docker compose up -d db mailpit
```

In separate terminals:

```sh
cd backend
../.venv/bin/alembic upgrade head
../.venv/bin/python app/initial_data.py
../.venv/bin/fastapi dev
```

```sh
cd backend
../.venv/bin/python -m app.payments.worker
```

```sh
bun run dev
```

Frontend: `http://localhost:5173`. API/docs: `http://localhost:8000/docs`.
Alternatively `docker compose up --build -d` runs the development stack, migrations
and payment worker. Production uses the base and deploy Compose files; follow
[deployment instructions](deployment-docker-compose.md) and the
[payment operations/recovery notes](backend/PAYMENTS.md).

## Validate

```sh
cd backend
BCH_NETWORK=mainnet ../.venv/bin/pytest tests/api/routes/test_payments.py -q
```

```sh
cd frontend
bun run build
bun run test:wallet-sdk
bun run test:wallet
```

Payment tests isolate their database/provider. Browser tests cover the real frontend
against API/relay doubles. Run the full backend/auth suite against a separate migrated
PostgreSQL test database; do not point destructive test fixtures at merchant data.
Live BCHN payment verification and a real Cashonize payment demonstration remain
required before claiming production readiness.

More: [backend development](backend/README.md), [frontend development](frontend/README.md),
[wallet SDK notes](frontend/src/features/wallet/README.md), [general development](development.md).

Built on the MIT-licensed Full Stack FastAPI Template. See [LICENSE](LICENSE).

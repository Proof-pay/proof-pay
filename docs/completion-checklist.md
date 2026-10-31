# ProofPay completion checklist

Historical checklist: destination allocation and validation details below are superseded
by [reusable BCH addresses](reusable-bch-addresses.md).

## Implemented and checked
- [x] Inspected existing code/docs/manifests/migrations/tests/Compose and clean initial git state; preserved authentication and existing routes.
- [x] Existing merchant API-backed dashboard, request search/filter/pagination, drafts/issue/cancellation, QR download, responsive navigation retained.
- [x] Business/receiving-wallet settings connected to API; deployment network shown.
- [x] Permanent atomic destination reservations; reuse rejected across merchants, aliases, deletion, cancellation and expiry.
- [x] Fresh merchant-provided addresses watched before publication; automatic incoming discovery independently verifies outputs.
- [x] Durable separate Compose worker with PostgreSQL singleton lock, retry/backoff, fair persisted scan attempts, restart recovery, known-output rechecks and reorg correction.
- [x] BCHN adapter validates network/watch-only wallet health; missing watches fail visibly. Chipnet supported explicitly.
- [x] Integer satoshi accounting, frozen issued terms, partial funding/remaining amount URI, detected versus confirmed funding, late/overpayment reporting.
- [x] Checkout/status polling and merchant dashboard/detail/list polling.
- [x] Receipt requested/issued amounts, destination, current confirmations/evidence, network explorer links and verification timestamp; internal IDs excluded publicly.
- [x] Full authenticated streaming CSV export with ownership checks.
- [x] Docker build copies required workspace manifests and SDK patches; Compose startup applies migrations.
- [x] Provider/setup/recovery and legacy shared-address migration instructions updated.

## Validation
- [x] Isolated backend payment tests (12 passing): lifecycle/ownership/privacy, precision, idempotency, permanent address and token-alias rejection, partial/overpayment, outage/recovery, automatic discovery across cycles, disappearing transaction correction, late funding, CSV ownership and RPC/watch-wallet contract.
- [x] Wallet SDK tests: 2 passing.
- [x] Browser tests: 5 passing, covering pairing/copy/cancel/timeouts/restoration, mobile checkout, remaining amount, polling/reload and stale/late funding. Relay doubles produce existing WebSocket-close diagnostics; live wallet interoperability is not established.
- [x] Frontend TypeScript/production build, targeted Biome, backend Ruff and targeted Python type checks.
- [x] Compose configuration validation; Alembic monitoring migration generates PostgreSQL SQL offline.
- [ ] PostgreSQL migration execution, advisory-lock multi-process verification and full auth/backend suite: Docker daemon is stopped; no isolated PostgreSQL service is available.
- [ ] Real BCHN incoming-payment/reorg demonstration: `BCH_RPC_URL` is unset in the current environment. No live chain verification claimed.

## Core work still unfinished
- [ ] WizardConnect customer transaction construction/signing/broadcast with verified network handling and external-wallet approval. Existing integration connects/restores/disconnects only; standard BCH payment URI/QR works independently.
- [ ] Automatic HD destination allocation with persisted derivation indices and tested wallet recovery/gap-limit behavior. Current implementation requires a fresh wallet-generated address per request and permanently reserves it; it does not claim automated derivation.
- [ ] Live Cashonize pairing and customer-payment demonstration on configured network. SDK handshake has no network attestation; UI labels wallet network unverified.

These are remaining core requirements, not optional features. No fake signing,
automatic payment success, or custodial keys are substituted. Full end-to-end
completion is not claimed. Existing issued shared-address records remain manual
claims/rechecking only and are never guessed into automatic attribution.

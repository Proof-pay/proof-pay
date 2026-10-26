# WizardConnect wallet connection

ProofPay uses the official React `useWizardConnect` hook once in
`WalletProvider`, mounted in the authenticated TanStack layout. Consumers use
`useProofPayWallet`; the shared header renders `ConnectWallet`. The app is a
Vite SPA using `createRoot`, with React Strict Mode enabled; no SSR is configured.
No Connect Wallet control existed in the source before this integration.

## Verified SDK

Checked on 2026-10-23 against the official docs, public registry, package exports,
and Cashonize source:

- `@wizardconnect/core@0.2.5`
- `@wizardconnect/dapp@0.2.2`
- `@wizardconnect/react@0.2.3` (React peer range `>=18.0.0`)

The frontend pins these versions. Existing root dependency declarations are
preserved. Install from the repository root with `bun install`; Bun also applies
the reviewed SDK patches in the root `patches/` directory.

References:

- [Official React integration](https://docs.riftenlabs.com/wizardconnect/react/)
- [Dapp lifecycle and persistence](https://docs.riftenlabs.com/wizardconnect/dapp/)
- [Pairing URI format and direction](https://docs.riftenlabs.com/wizardconnect/connection-uri/)
- [Protocol fields](https://docs.riftenlabs.com/wizardconnect/protocol/)
- [Cashonize pairing implementation](https://github.com/cashonize/cashonize-wallet/blob/main/src/stores/wizardconnectStore.ts)

The overview page's introductory pairing direction differs from the current
React/dapp guide, URI guide, installed code, and Cashonize implementation.
This integration follows those detailed sources: **ProofPay generates the URI;
Cashonize scans or pastes it and asks for approval**. The SDK's lowercase `uri`
is copied unchanged. Its distinct uppercase, percent-encoded `qrUri` is passed
unchanged to the official `AlphanumericQRCode` component.

## State and persistence

Only the SDK's validated `walletready` transition produces Connected and a wallet
name. Relay readiness and a cached name do not. Reconnection is shown as waiting.
There is a 90-second approval/reconnect timeout with Retry. Cashonize's initial
approval rejection is local to Cashonize and sends no protocol message, so it
cannot be distinguished from a wallet that has not yet responded.

The SDK manages session serialization and restoration under
`proofpay-wizardconnect-session`. The supported storage adapter tolerates blocked
browser storage and shows a notice. The session contains SDK transport
credentials and public HD wallet data; application code does not copy these into
another store or send them to the backend. No wallet seed or BCH private key is
requested. The public hook exposes no signing or payment methods.

Closing an unfinished pairing dialog cancels and clears its session. Closing a
connected wallet dialog leaves the connection active; Disconnect clears the SDK
session and tears down the relay. Layout unmount stops transports/listeners while
preserving the SDK session for a later remount. Backend login remains separate.

## Chipnet and HD addresses

The installed `hdwalletv1` handshake has no network identifier. No network option
is invented, and no address prefix is used as evidence of Chipnet. The dialog
always says **network unverified** and asks the user to select Chipnet in Cashonize.

No receive address is shown. The documented `manager.getPubkey(0, 0n)` derives a
specific receive public key, but does not identify Cashonize's current receive
index or establish its active network. This task adds connectivity only.

## SDK compatibility patches

The official packages remain in use. Small Bun patches are checked in because
the published versions have lifecycle/privacy gaps relevant to this integration:

- React: guard duplicate starts with synchronous refs; ignore callbacks from a
  disposed session; clear manager refs during Strict Mode cleanup; release
  managers on failure/disconnect; bound an offline courtesy disconnect to 500 ms.
- Dapp: require completed key exchange before accepting initial readiness;
  detach owned listeners and stop timers on destruction; ignore delayed readiness
  after destruction; remove raw session/xpub/error payloads from diagnostic logs.

Recheck these patches before upgrading the SDK. Original package license headers
are retained in the modified files.

## Validation

From `frontend/`:

```sh
bunx tsc --noEmit -p tsconfig.build.json
bunx biome check src/features/wallet src/routes/_layout.tsx tests/wallet sdk-tests playwright.wallet.config.ts package.json
bun run build
bun run test:wallet-sdk
bun run test:wallet
```

The SDK tests use a transport test double. Browser tests use the real React SDK
and simulated relay acknowledgements while stubbing backend auth/summary reads.
They check pending status despite relay readiness, generated QR/copy, cancellation,
timeout/retry, mobile overflow, and Strict Mode restoration without premature
Connected state. They do not prove pairing with a real Cashonize wallet.
Browser traces, screenshots, and video are disabled to avoid recording pairing
credentials. No payment, signing, broadcasting, or backend code is added.

## Manual Cashonize test

1. Run ProofPay with Bun and log in normally. In Cashonize, select an **HD wallet**
   and **Chipnet**. Confirm that selection in Cashonize itself.
2. Click **Connect Wallet** in ProofPay's header. In Cashonize's dapp connection
   screen, scan the QR or paste **Copy connection URI**. Accept the wallet's
   connection/public-data sharing prompt. ProofPay must remain waiting until
   the wallet handshake completes, then show Connected and the returned name.
3. Disconnect and start again. Reject the Cashonize prompt: ProofPay must never
   show Connected. Cancel in ProofPay or let the 90-second timeout expire, then
   use Retry and confirm a new pairing works.
4. Start a pairing and close the dialog with Escape, its close button, or Cancel.
   Check that its SDK storage entry is removed and a new attempt has a fresh URI.
5. After successful pairing, refresh ProofPay with Cashonize available. Expect
   reconnecting without a new QR, then Connected only after a fresh wallet
   handshake. Repeat during relay/network interruption and app switching.
6. Use **Disconnect** in ProofPay. Check that the session key is removed, relay
   sockets close, and a refresh stays disconnected; backend login should remain.
7. Pair again, then disconnect from Cashonize. ProofPay should become disconnected
   and clear its saved session. The SDK allows an approximately eight-second
   grace period for wallet reconnects. Repeat after switching wallet/network in
   Cashonize; ProofPay must continue to label the network unverified.

A real Cashonize handshake has not been observed during automated validation.

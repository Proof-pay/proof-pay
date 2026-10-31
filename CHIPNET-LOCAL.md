# Local Chipnet node

This setup is for the native development backend (FastAPI on the host).
Start the node with `docker compose -f compose.chipnet.yml up -d`.
RPC is published only on `127.0.0.1:48332`. Credentials live in ignored
`.env` and `.env.chipnet.conf` files. Do not commit either file.
The persistent Docker volume retains blockchain data and the watch-only wallet.

Check synchronization:

```sh
docker compose -f compose.chipnet.yml exec bchn bitcoin-cli -datadir=/data -conf=/etc/bitcoin/bitcoin.conf getblockchaininfo
```

Wait until `initialblockdownload` is false. ProofPay deliberately prevents issuing
payment links while the node is syncing. The wallet `proofpay-watch` has private
keys disabled; funds stay in the freelancer's wallet.

Restart FastAPI after changing `.env`. Run the payment reconciliation worker in
another terminal for payment discovery and ongoing confirmation/reorg checks:

```sh
cd backend
../.venv/bin/python -m app.payments.worker
```

If moving the backend into Docker, use the internal wallet endpoint
`http://bchn:48332/wallet/proofpay-watch` and run the services on the same Compose
network. The host-loopback URL in `.env` is for the current native development setup.

Stop the node with `docker compose -f compose.chipnet.yml stop`. Do not delete
its data volume; it contains the watch-only address history.


The API dev server does not reload this separate process. Stop and restart the
worker after payment-code or `.env` changes. Starting `compose.chipnet.yml` starts
only BCHN; it does not start the host's Python worker. The full application Compose
file has a separate `payment-worker` service for container deployments.

To inspect an existing request without persisting changes:

```sh
cd backend
../.venv/bin/python -m app.payments.repair --invoice PP-1287C335 --dry-run
```

This rechecks existing allocations only. It never assigns all transfers to an
address, moves outputs between invoices, or rewrites receipt snapshots. Applying
record changes requires reviewing the report and explicitly using `--apply`.

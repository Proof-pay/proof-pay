# Payment UI demo service

The FastAPI backend has no payment link, transaction, receipt, or chain monitoring endpoints. `service.ts` is an isolated, typed browser-only demo store. It ships one pending sample request and stores newly created requests in the current browser's `localStorage`.

A copied checkout URL for a newly created link only resolves in that same browser. Payment status remains pending; no timer or button can claim network confirmation. The sample request has no wallet address, so it cannot produce an active wallet URI. New requests require a valid Bitcoin Cash mainnet cash address and encode that address and the exact decimal amount in the wallet QR. The merchant QR encodes the checkout URL.

To make links shareable between devices and receipts verifiable, replace this store with authenticated merchant and public payment APIs, plus actual blockchain monitoring. Keep private merchant fields out of public responses.

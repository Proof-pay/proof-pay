# Payment management UI

The dashboard uses the authenticated FastAPI payment API under `/api/v1`.
Payment links are stored in the database and are visible across browsers.
Creating a link creates a draft and immediately issues it. If issuing fails,
the draft remains in the payment links list so it can be retried.

Unpublished drafts can be edited or deleted. Issued unpaid requests can be
cancelled. Published records and their payment history cannot be deleted.
Public checkout and receipt pages read token-scoped endpoints without login.

The QR code contains the payment URI returned by the backend. Scanning or
opening checkout never marks a request paid. This UI does not submit transaction
claims or contact BCH nodes or explorers. Transaction and receipt pages only
show records returned by the existing backend.

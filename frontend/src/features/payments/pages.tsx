import { Link, useNavigate } from "@tanstack/react-router"
import {
  Activity,
  ArrowLeft,
  ArrowRight,
  ArrowUpRight,
  CircleCheck,
  Clock3,
  ExternalLink,
  Link2,
  Plus,
  Receipt,
  ScanLine,
  Wallet,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import useAuth from "@/hooks/useAuth"
import {
  checkoutUrl,
  createLink,
  displayDate,
  getLink,
  isExpired,
  listLinks,
  type PaymentStatus,
  paymentUri,
  receiptUrl,
  sumAmounts,
  validAddress,
} from "./service"
import {
  CopyButton,
  DemoNotice,
  DetailRow,
  EmptyState,
  ExplorerLink,
  LinkStatus,
  PageHeader,
  PaymentTable,
  PaymentTimeline,
  PrintButton,
  QRDisplay,
  SearchField,
  StatCard,
  StatusBadge,
} from "./ui"

const card = "dashboard-card p-5 sm:p-6"
const primaryLink =
  "inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-emerald-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-700"

export function Overview() {
  const links = listLinks()
  const active = links.filter(
    (link) => !isExpired(link) && link.status === "pending",
  )
  return (
    <div className="space-y-7">
      <PageHeader
        eyebrow="Merchant workspace"
        title="Good to see you again"
        description="Here’s what’s happening with your payment requests."
        action={
          <Link className={primaryLink} to="/dashboard/payment-links/new">
            <Plus className="size-4" />
            Create payment link
          </Link>
        }
      />
      <DemoNotice />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total received"
          value="0 BCH"
          hint="No verified payments"
          icon={Wallet}
        />
        <StatCard
          label="Pending amount"
          value={`${sumAmounts(active.map((item) => item.amount))} BCH`}
          hint={`${active.length} open requests`}
          icon={Activity}
          tone="amber"
        />
        <StatCard
          label="Active links"
          value={String(active.length)}
          hint="Ready to share"
          icon={Link2}
          tone="blue"
        />
        <StatCard
          label="Confirmed"
          value="0"
          hint="Verification not connected"
          icon={CircleCheck}
          tone="violet"
        />
      </div>
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold tracking-tight">
                Recent payment requests
              </h2>
              <p className="mt-0.5 text-xs text-slate-500">
                Your latest activity in one place
              </p>
            </div>
            <Link
              to="/dashboard/payment-links"
              className="inline-flex shrink-0 items-center gap-1 text-sm font-semibold text-emerald-700 hover:underline"
            >
              View all <ArrowUpRight className="size-4" />
            </Link>
          </div>
          <PaymentTable links={links.slice(0, 5)} />
        </section>
        <aside className="space-y-4">
          <div className="rounded-2xl bg-[#112d31] p-6 text-white shadow-[0_12px_32px_rgba(16,49,48,.12)]">
            <span className="grid size-11 place-items-center rounded-xl bg-white/10">
              <ScanLine className="size-5 text-emerald-300" />
            </span>
            <h2 className="mt-6 text-lg font-bold tracking-tight">
              Accept BCH, simply.
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-300">
              Create a payment request, then share its checkout page or QR code.
            </p>
            <Link
              to="/dashboard/payment-links/new"
              className="mt-6 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-[#21bf85] px-4 text-sm font-semibold text-[#082e25] transition-colors hover:bg-[#55d9a7]"
            >
              Create a payment link <ArrowRight className="size-4" />
            </Link>
          </div>
          <div className={`${card} space-y-3`}>
            <h2 className="font-semibold">Quick access</h2>
            <Link
              to="/dashboard/transactions"
              className="flex items-center justify-between rounded-lg border px-3 py-2.5 text-sm font-medium hover:bg-slate-50"
            >
              Transactions <ArrowRight className="size-4 text-slate-400" />
            </Link>
            <Link
              to="/dashboard/receipts"
              className="flex items-center justify-between rounded-lg border px-3 py-2.5 text-sm font-medium hover:bg-slate-50"
            >
              Receipts <ArrowRight className="size-4 text-slate-400" />
            </Link>
          </div>
        </aside>
      </div>
    </div>
  )
}

export function LinksPage() {
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState("all")
  const [page, setPage] = useState(1)
  const filtered = listLinks().filter(
    (link) =>
      `${link.title} ${link.merchant}`
        .toLowerCase()
        .includes(search.toLowerCase()) &&
      (filter === "all" ||
        (isExpired(link) ? "expired" : link.status) === filter),
  )
  const pages = Math.max(1, Math.ceil(filtered.length / 8))
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Payments"
        title="Payment links"
        description="Create, share, and track payment requests."
        action={
          <Link className={primaryLink} to="/dashboard/payment-links/new">
            <Plus className="size-4" />
            Create payment link
          </Link>
        }
      />
      <DemoNotice />
      <div className="dashboard-card flex flex-wrap gap-3 p-4">
        <SearchField
          value={search}
          onChange={(value) => {
            setSearch(value)
            setPage(1)
          }}
          placeholder="Search payment links"
        />
        <select
          aria-label="Filter by status"
          className="dashboard-control h-9 px-3 text-sm"
          value={filter}
          onChange={(event) => {
            setFilter(event.target.value)
            setPage(1)
          }}
        >
          <option value="all">All statuses</option>
          <option value="pending">Pending</option>
          <option value="detected">Detected</option>
          <option value="confirmed">Confirmed</option>
          <option value="expired">Expired</option>
        </select>
      </div>
      {filtered.length ? (
        <PaymentTable links={filtered.slice((page - 1) * 8, page * 8)} />
      ) : (
        <EmptyState
          title="No matching links"
          description="Try another search or create a payment link."
        />
      )}
      <div className="flex items-center justify-end gap-3 text-sm">
        <Button
          variant="outline"
          disabled={page === 1}
          onClick={() => setPage(page - 1)}
        >
          Previous
        </Button>
        <span>
          Page {page} of {pages}
        </span>
        <Button
          variant="outline"
          disabled={page >= pages}
          onClick={() => setPage(page + 1)}
        >
          Next
        </Button>
      </div>
    </div>
  )
}

export function NewLinkPage() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const [title, setTitle] = useState("")
  const [amount, setAmount] = useState("")
  const [address, setAddress] = useState("")
  const [description, setDescription] = useState("")
  const [expiry, setExpiry] = useState("")
  const [error, setError] = useState("")
  function submit(event: React.FormEvent) {
    event.preventDefault()
    const normalized = amount.trim()
    if (!/^\d+(\.\d{1,8})?$/.test(normalized) || !/[1-9]/.test(normalized))
      return setError(
        "Enter a positive BCH amount with up to 8 decimal places.",
      )
    if (!validAddress(address.trim()))
      return setError("Enter a valid Bitcoin Cash mainnet cash address.")
    if (expiry && new Date(expiry).getTime() <= Date.now())
      return setError("Choose a future expiry date and time.")
    const link = createLink({
      title: title.trim(),
      amount: normalized,
      address: address.trim(),
      description: description.trim(),
      merchant: user?.full_name || "ProofPay merchant",
      expiresAt: expiry ? new Date(expiry).toISOString() : null,
    })
    toast.success("Demo payment link created")
    navigate({ to: "/dashboard/payment-links/$id", params: { id: link.id } })
  }
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        eyebrow="Payment links"
        title="Create payment link"
        description="Set the details your customer will see at checkout."
      />
      <DemoNotice />
      <form
        onSubmit={submit}
        className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]"
      >
        <div className={`${card} space-y-5`}>
          <div className="border-b pb-4">
            <h2 className="font-semibold">Payment details</h2>
            <p className="mt-1 text-sm text-slate-500">
              Set up the checkout page your customer will open.
            </p>
          </div>
          <Field id="title" label="Title / invoice name" required>
            <Input
              id="title"
              required
              maxLength={100}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Website design deposit"
            />
          </Field>
          <Field id="amount" label="Amount (BCH)" required>
            <Input
              id="amount"
              required
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="0.05"
            />
          </Field>
          <Field id="address" label="Recipient BCH address" required>
            <Input
              id="address"
              required
              value={address}
              onChange={(e) => setAddress(e.target.value)}
              placeholder="bitcoincash:..."
              autoComplete="off"
            />
            <p className="mt-1.5 text-xs text-slate-500">
              Funds go directly to this Bitcoin Cash address. Check it carefully
              before sharing.
            </p>
          </Field>
          <Field id="description" label="Description (optional)">
            <textarea
              id="description"
              className="dashboard-control min-h-24 w-full px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-emerald-700"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              placeholder="What is this payment for?"
            />
          </Field>
          <Field id="expiry" label="Expiry (optional)">
            <Input
              id="expiry"
              type="datetime-local"
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
            />
          </Field>
          {error && (
            <p role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-3 border-t pt-5">
            <Link
              to="/dashboard/payment-links"
              className="inline-flex h-9 items-center rounded-md border px-4 text-sm"
            >
              Cancel
            </Link>
            <Button type="submit">
              Create link <ArrowRight />
            </Button>
          </div>
        </div>
        <aside className="space-y-4">
          <div className={`${card} space-y-3`}>
            <span className="grid size-11 place-items-center rounded-xl bg-emerald-50 text-emerald-700">
              <Wallet className="size-5" />
            </span>
            <h2 className="font-semibold">Direct to your wallet</h2>
            <p className="text-sm leading-6 text-slate-500">
              Customers can scan a QR code or open the payment URI in their BCH
              wallet. Check your address carefully before sharing.
            </p>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-900">
            Demo requests are saved in this browser. Payment detection and
            verification are not connected.
          </div>
        </aside>
      </form>
    </div>
  )
}
function Field({
  id,
  label,
  required,
  children,
}: {
  id: string
  label: string
  required?: boolean
  children: React.ReactNode
}) {
  return (
    <div className="block space-y-2 [&_input]:h-11 [&_input]:rounded-lg [&_input]:border-[#dbe5e7] [&_input]:bg-white">
      <label htmlFor={id} className="block text-sm font-medium">
        {label} {required && <span className="text-red-700">*</span>}
      </label>
      {children}
    </div>
  )
}

export function LinkDetails({ id }: { id: string }) {
  const link = getLink(id)
  if (!link)
    return (
      <EmptyState
        title="Payment link not found"
        description="This demo link may have been created in another browser."
      />
    )
  const url = checkoutUrl(link)
  return (
    <div className="space-y-6">
      <Link
        to="/dashboard/payment-links"
        className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-emerald-700"
      >
        <ArrowLeft className="size-4" />
        Payment links
      </Link>
      <DemoNotice />
      <div className="grid gap-6 lg:grid-cols-[1.2fr_.8fr]">
        <div className={`${card} space-y-6`}>
          <div className="flex size-14 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700">
            <Link2 className="size-7" />
          </div>
          <div>
            <h1 className="text-3xl font-bold tracking-tight">
              Payment link ready
            </h1>
            <p className="mt-2 text-slate-500">
              Share this checkout page with your customer.
            </p>
          </div>
          <div>
            <label
              htmlFor="checkout-url"
              className="mb-2 block text-sm font-medium"
            >
              Public checkout URL
            </label>
            <Input
              id="checkout-url"
              readOnly
              value={url}
              onFocus={(e) => e.currentTarget.select()}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <CopyButton value={url} label="Copy link" variant="default" />
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-9 items-center gap-2 rounded-lg border px-4 text-sm font-medium hover:bg-slate-50"
            >
              <ExternalLink className="size-4" />
              Preview checkout
            </a>
            <Link
              to="/dashboard/payment-links/$id/qr"
              params={{ id }}
              className="inline-flex h-9 items-center gap-2 rounded-lg border px-4 text-sm font-medium hover:bg-slate-50"
            >
              Show QR <ArrowRight className="size-4" />
            </Link>
          </div>
        </div>
        <div className={card}>
          <h2 className="mb-3 font-semibold">Request details</h2>
          <dl>
            <DetailRow label="Invoice" value={link.title} />
            <DetailRow label="Amount" value={`${link.amount} BCH`} />
            <DetailRow label="Status" value={<LinkStatus link={link} />} />
            <DetailRow
              label="Recipient"
              value={link.address || "Demo sample · no wallet address"}
            />
            <DetailRow label="Created" value={displayDate(link.createdAt)} />
            <DetailRow label="Expires" value={displayDate(link.expiresAt)} />
          </dl>
          {link.description && (
            <p className="mt-4 text-sm text-slate-500">{link.description}</p>
          )}
        </div>
      </div>
    </div>
  )
}
export function MerchantQR({ id }: { id: string }) {
  const link = getLink(id)
  if (!link)
    return (
      <EmptyState
        title="Payment link not found"
        description="Check the URL and try again."
      />
    )
  const url = checkoutUrl(link)
  const uri = paymentUri(link)
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        eyebrow="Payment links"
        title="Payment QR code"
        description="Display or share this request with your customer."
      />
      <DemoNotice />
      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className={`${card} space-y-5 text-center`}>
          <p className="text-xs font-bold uppercase tracking-[.16em] text-emerald-700">
            Checkout QR
          </p>
          <QRDisplay value={url} label="Scan to open checkout" large />
          <CopyButton value={url} label="Copy checkout URL" />
          <p className="break-all text-xs text-slate-500">{url}</p>
        </div>
        <div className="space-y-5">
          <div className={card}>
            <p className="text-xs font-bold uppercase tracking-[.16em] text-slate-500">
              Payment request
            </p>
            <h2 className="mt-3 text-xl font-bold">{link.title}</h2>
            <p className="mt-1 text-sm text-slate-500">{link.merchant}</p>
            <p className="mt-5 text-[32px] font-bold tracking-tight text-emerald-700">
              {link.amount} <span className="text-base">BCH</span>
            </p>
            <dl className="mt-5">
              <DetailRow label="Status" value={<LinkStatus link={link} />} />
              <DetailRow label="Expires" value={displayDate(link.expiresAt)} />
            </dl>
            {link.address && (
              <div className="mt-5">
                <p className="mb-2 text-xs font-medium text-slate-500">
                  Recipient address
                </p>
                <p className="break-all rounded-lg bg-[#f6f9f8] p-3 font-mono text-xs">
                  {link.address}
                </p>
                <div className="mt-3">
                  <CopyButton value={link.address} label="Copy address" />
                </div>
              </div>
            )}
          </div>
          {uri && (
            <div className={`${card} space-y-3`}>
              <h2 className="font-semibold">Pay directly with a BCH wallet</h2>
              <p className="text-sm text-slate-500">
                This URI includes the recipient and exact BCH amount.
              </p>
              <CopyButton value={uri} label="Copy payment URI" />
            </div>
          )}
          <PrintButton />
        </div>
      </div>
    </div>
  )
}
export function TransactionsPage() {
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("all")
  const links = listLinks().filter(
    (link) =>
      (status === "all" || link.status === status) &&
      `${link.title} ${link.txid || ""}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Payments"
        title="Transactions"
        description="Network activity associated with your requests."
      />
      <DemoNotice />
      <div className="dashboard-card flex flex-wrap gap-3 p-4">
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search transactions"
        />
        <select
          aria-label="Filter transactions"
          className="dashboard-control h-9 px-3 text-sm"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="pending">Pending</option>
          <option value="detected">Detected</option>
          <option value="confirmed">Confirmed</option>
        </select>
      </div>
      {links.some((link) => link.txid) ? (
        <div className="dashboard-card overflow-x-auto">
          <table className="dashboard-table w-full min-w-[650px] text-left text-sm">
            <thead className="border-b bg-[#f8faf9]">
              <tr>
                <th className="p-4">Date</th>
                <th className="p-4">Payment</th>
                <th className="p-4">Amount</th>
                <th className="p-4">Transaction ID</th>
                <th className="p-4">Confirmations</th>
              </tr>
            </thead>
            <tbody>
              {links
                .filter((link) => link.txid)
                .map((link) => (
                  <tr key={link.id} className="border-b last:border-0">
                    <td className="p-4">{displayDate(link.createdAt)}</td>
                    <td className="p-4">
                      <Link
                        to="/dashboard/transactions/$id"
                        params={{ id: link.id }}
                        className="text-emerald-700 hover:underline"
                      >
                        {link.title}
                      </Link>
                    </td>
                    <td className="p-4">{link.amount} BCH</td>
                    <td className="p-4 font-mono">
                      {link.txid?.slice(0, 12)}…
                    </td>
                    <td className="p-4">{link.confirmations}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title="No detected transactions"
          description="Transactions will appear when a payment monitoring API is connected."
        />
      )}
    </div>
  )
}
export function TransactionDetails({ id }: { id: string }) {
  const link = getLink(id)
  if (!link?.txid)
    return (
      <EmptyState
        title="Transaction unavailable"
        description="No verified transaction is associated with this demo request."
      />
    )
  return (
    <div className="space-y-6">
      <PageHeader title="Transaction details" />
      <DemoNotice />
      <div className={card}>
        <dl>
          <DetailRow label="Payment" value={link.title} />
          <DetailRow label="Amount" value={`${link.amount} BCH`} />
          <DetailRow label="Transaction ID" value={link.txid} />
          <DetailRow label="Confirmations" value={link.confirmations} />
          <DetailRow label="Status" value={<LinkStatus link={link} />} />
          <DetailRow
            label="Explorer"
            value={<ExplorerLink txid={link.txid} />}
          />
        </dl>
        {link.receiptId && (
          <Link
            to="/r/$publicReceiptId"
            params={{ publicReceiptId: link.receiptId }}
            className="mt-4 inline-flex text-emerald-700"
          >
            View receipt
          </Link>
        )}
      </div>
    </div>
  )
}
export function ReceiptsPage() {
  const [search, setSearch] = useState("")
  const receipts = listLinks().filter(
    (link) =>
      link.receiptId &&
      `${link.title} ${link.receiptId}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  )
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Payments"
        title="Receipts"
        description="Share proof when a payment has been verified."
      />
      <DemoNotice />
      <div className="dashboard-card p-4">
        <SearchField
          value={search}
          onChange={setSearch}
          placeholder="Search receipts"
        />
      </div>
      {receipts.length ? (
        <div className="dashboard-card overflow-x-auto">
          <table className="dashboard-table w-full min-w-[650px] text-left text-sm">
            <thead className="border-b bg-[#f8faf9]">
              <tr>
                <th className="p-4">Receipt ID</th>
                <th className="p-4">Invoice</th>
                <th className="p-4">Amount</th>
                <th className="p-4">Payment date</th>
                <th className="p-4">Status</th>
                <th className="p-4">Actions</th>
              </tr>
            </thead>
            <tbody>
              {receipts.map((link) => (
                <tr key={link.id} className="border-b last:border-0">
                  <td className="p-4 font-medium">{link.receiptId}</td>
                  <td className="p-4">{link.title}</td>
                  <td className="p-4">{link.amount} BCH</td>
                  <td className="p-4">
                    {link.txid ? displayDate(link.createdAt) : "Not paid"}
                  </td>
                  <td className="p-4">
                    <StatusBadge status={link.status} />
                  </td>
                  <td className="flex gap-3 p-4">
                    <Link
                      to="/r/$publicReceiptId"
                      params={{ publicReceiptId: link.receiptId! }}
                      className="text-emerald-700 hover:underline"
                    >
                      View
                    </Link>
                    <CopyButton
                      value={receiptUrl(link.receiptId!)}
                      label="Copy link"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title="No receipts yet"
          description="Receipts become available after verified payment data is connected."
        />
      )}
    </div>
  )
}
function PublicShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f5f8f8] px-4 py-8 text-slate-900 sm:py-14">
      <div className="mx-auto max-w-xl">
        <Link
          to="/"
          className="mb-8 inline-flex items-center gap-2 text-xl font-bold tracking-tight text-[#14252f]"
        >
          <span className="grid size-9 place-items-center rounded-xl bg-emerald-700 text-white">
            <CircleCheck className="size-5" />
          </span>{" "}
          Proof<span className="text-emerald-700">Pay</span>
        </Link>
        {children}
        <p className="mt-8 text-center text-xs text-slate-500">
          Simple payments. Verifiable receipts. Built for Bitcoin Cash.
        </p>
      </div>
    </div>
  )
}
function MissingPublic() {
  return (
    <PublicShell>
      <EmptyState
        title="Request not found"
        description="This demo request may exist in a different browser, or the link is incorrect."
      />
    </PublicShell>
  )
}
export function Checkout({ publicId }: { publicId: string }) {
  const link = getLink(publicId)
  if (!link) return <MissingPublic />
  const uri = paymentUri(link)
  const expired = isExpired(link)
  return (
    <PublicShell>
      <div className="space-y-5">
        <DemoNotice />
        <div className={`${card} text-center`}>
          <div className="mx-auto mb-4 grid size-14 place-items-center rounded-full bg-emerald-50 text-emerald-700">
            <Wallet className="size-7" />
          </div>
          <p className="text-sm text-slate-500">Payment request from</p>
          <h1 className="text-xl font-semibold">{link.merchant}</h1>
          <p className="mt-4 text-sm text-slate-500">{link.title}</p>
          {link.description && (
            <p className="mt-1 text-sm text-slate-500">{link.description}</p>
          )}
          <p className="mt-5 rounded-xl bg-emerald-50 py-4 text-3xl font-bold text-emerald-800">
            {link.amount} BCH
          </p>
          {expired ? (
            <p className="mt-5 text-red-700">This request has expired.</p>
          ) : uri ? (
            <>
              <div className="my-6">
                <QRDisplay value={uri} label="Scan to pay with a BCH wallet" />
              </div>
              <p className="text-xs text-slate-500">Recipient address</p>
              <p className="mt-1 break-all rounded-lg bg-slate-50 p-3 font-mono text-xs">
                {link.address}
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                <a href={uri} className={primaryLink}>
                  <Wallet className="size-4" />
                  Open wallet
                </a>
                <CopyButton value={link.address} label="Copy address" />
                <CopyButton value={link.amount} label="Copy amount" />
              </div>
            </>
          ) : (
            <p className="mt-6 text-sm text-amber-800">
              This sample request has no wallet address. Create a link with your
              own valid BCH address to try checkout.
            </p>
          )}
        </div>
        <Link
          to="/p/$publicId/status"
          params={{ publicId }}
          className="flex items-center justify-between rounded-xl border bg-white px-5 py-4 text-sm font-medium"
        >
          View payment status <ArrowRight className="size-4" />
        </Link>
      </div>
    </PublicShell>
  )
}
export function PaymentStatusPage({ publicId }: { publicId: string }) {
  const link = getLink(publicId)
  if (!link) return <MissingPublic />
  const state: PaymentStatus = isExpired(link) ? "expired" : link.status
  return (
    <PublicShell>
      <div className="space-y-5">
        <DemoNotice />
        <div className={`${card} space-y-6 text-center`}>
          <div className="mx-auto grid size-16 place-items-center rounded-full bg-emerald-50 text-emerald-700">
            {state === "confirmed" ? (
              <CircleCheck className="size-8" />
            ) : (
              <Clock3 className="size-8" />
            )}
          </div>
          <div>
            <StatusBadge status={state} />
            <h1 className="mt-3 text-2xl font-semibold">
              {state === "confirmed"
                ? "Payment confirmed"
                : state === "detected"
                  ? "Payment detected"
                  : state === "expired"
                    ? "Request expired"
                    : "Waiting for payment"}
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              {state === "pending"
                ? "No payment has been detected. Automatic payment detection is unavailable in demo mode."
                : state === "detected"
                  ? "A payment was detected and is awaiting network confirmation."
                  : state === "confirmed"
                    ? "Payment was confirmed by the network."
                    : "This request is no longer accepting payments."}
            </p>
          </div>
          <PaymentTimeline status={state} />
          <div className="text-left">
            <dl>
              <DetailRow label="Invoice" value={link.title} />
              <DetailRow label="Amount" value={`${link.amount} BCH`} />
              <DetailRow
                label="Transaction ID"
                value={link.txid || "Not available"}
              />
              <DetailRow
                label="Confirmations"
                value={link.txid ? link.confirmations : "Not available"}
              />
              <DetailRow
                label="Explorer"
                value={<ExplorerLink txid={link.txid} />}
              />
            </dl>
          </div>
          {link.receiptId && (
            <Link
              to="/r/$publicReceiptId"
              params={{ publicReceiptId: link.receiptId }}
              className="text-sm font-medium text-emerald-700"
            >
              View receipt <ArrowRight className="inline size-4" />
            </Link>
          )}
        </div>
        <Link
          to="/p/$publicId"
          params={{ publicId }}
          className="inline-flex items-center gap-2 text-sm text-emerald-700"
        >
          <ArrowLeft className="size-4" />
          Back to checkout
        </Link>
      </div>
    </PublicShell>
  )
}
export function PublicReceipt({
  publicReceiptId,
}: {
  publicReceiptId: string
}) {
  const link = listLinks().find((item) => item.receiptId === publicReceiptId)
  if (!link) return <MissingPublic />
  const confirmed = link.status === "confirmed" && !!link.txid
  return (
    <PublicShell>
      <div className="space-y-5">
        <DemoNotice />
        <div className={`${card} space-y-6`}>
          <div className="text-center">
            <div className="mx-auto mb-4 grid size-16 place-items-center rounded-full bg-emerald-50 text-emerald-700">
              <Receipt className="size-8" />
            </div>
            <h1 className="text-2xl font-semibold">
              {confirmed ? "Payment confirmed" : "Awaiting confirmation"}
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              {confirmed
                ? "Payment details from the Bitcoin Cash network."
                : "This demo receipt is not proof of payment."}
            </p>
          </div>
          <dl>
            <DetailRow label="Amount" value={`${link.amount} BCH`} />
            <DetailRow label="Merchant" value={link.merchant} />
            <DetailRow label="Invoice" value={link.title} />
            <DetailRow label="Receipt ID" value={publicReceiptId} />
            <DetailRow
              label="Transaction ID"
              value={link.txid || "Not available"}
            />
            <DetailRow
              label="Date"
              value={link.txid ? displayDate(link.createdAt) : "Not paid"}
            />
            <DetailRow
              label="Status"
              value={
                <StatusBadge status={confirmed ? "confirmed" : "pending"} />
              }
            />
          </dl>
          <div className="flex flex-wrap justify-center gap-2">
            <CopyButton
              value={receiptUrl(publicReceiptId)}
              label="Copy receipt link"
              variant="default"
            />
            <PrintButton />
            {link.txid && <ExplorerLink txid={link.txid} />}
          </div>
        </div>
      </div>
    </PublicShell>
  )
}

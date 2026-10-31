import {
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { Link, useNavigate } from "@tanstack/react-router"
import {
  ArrowLeft,
  ArrowRight,
  CircleCheck,
  Clock3,
  ExternalLink,
  Link2,
  Plus,
  Receipt as ReceiptIcon,
  Wallet,
} from "lucide-react"
import { type FormEvent, type ReactNode, useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  allocateOutputs,
  asLink,
  cancelLink,
  checkoutUrl,
  createLink,
  deleteLink,
  detectedOutputs,
  displayDate,
  errorMessage,
  explorerUrl,
  exportPayments,
  getLink,
  getMerchantSettings,
  getPayment,
  getPublicLink,
  getPublicReceipt,
  getSummary,
  isExpired,
  issueLink,
  listLinks,
  listPayments,
  listReceipts,
  type PaymentLink,
  type PaymentStatus,
  type ReviewedOutput,
  receiptUrl,
  reviewOutputs,
  satsToBch,
  updateLink,
  validAddress,
} from "./service"
import {
  CopyButton,
  DemoNotice,
  DetailRow,
  EmptyState,
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
  "inline-flex h-10 items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-white transition-colors hover:bg-emerald-800"
const linkQuery = (id: string) => ({
  queryKey: ["payment-link", id],
  queryFn: () => getLink(id),
  refetchInterval: 10000,
})

async function refreshPaymentQueries(cache: QueryClient, link: PaymentLink) {
  cache.setQueryData(["payment-link", link.id], link)
  await Promise.all(
    [
      ["payment-link", link.id],
      ["payment-links"],
      ["payment-summary"],
      ["payments"],
      ["payment"],
      ["receipts"],
      ["public-receipt"],
      ["public-link", link.publicId],
      ["public-link-status", link.publicId],
      ["detected-outputs", link.id],
    ].map((queryKey) => cache.invalidateQueries({ queryKey })),
  )
}

function QueryState({ loading, error }: { loading: boolean; error: unknown }) {
  if (loading)
    return (
      <p role="status" className="p-6 text-sm text-slate-500">
        Loading payment information…
      </p>
    )
  if (error)
    return (
      <div
        role="alert"
        className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
      >
        {errorMessage(error)}
      </div>
    )
  return null
}
function Field({
  id,
  label,
  children,
  required,
}: {
  id: string
  label: string
  children: ReactNode
  required?: boolean
}) {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
        {required && " *"}
      </label>
      {children}
    </div>
  )
}
function PageControls({
  page,
  count,
  size,
  setPage,
}: {
  page: number
  count: number
  size: number
  setPage: (page: number) => void
}) {
  return (
    <div className="flex items-center justify-end gap-3 text-sm">
      <Button
        variant="outline"
        disabled={page === 1}
        onClick={() => setPage(page - 1)}
      >
        Previous
      </Button>
      <span>
        Page {page} of {Math.max(1, Math.ceil(count / size))}
      </span>
      <Button
        variant="outline"
        disabled={page * size >= count}
        onClick={() => setPage(page + 1)}
      >
        Next
      </Button>
    </div>
  )
}

export function Overview() {
  const summary = useQuery({
    queryKey: ["payment-summary"],
    queryFn: getSummary,
    refetchInterval: 10000,
  })
  if (!summary.data)
    return <QueryState loading={summary.isPending} error={summary.error} />
  const data = summary.data
  const links = data.recent_activity.map(asLink)
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
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Total received"
          value={`${satsToBch(data.confirmed_received_sats)} BCH`}
          hint="Confirmed payments"
          icon={Wallet}
        />
        <StatCard
          label="Pending amount"
          value={`${satsToBch(data.outstanding_requested_sats)} BCH`}
          hint="Outstanding requests"
          icon={Clock3}
          tone="amber"
        />
        <StatCard
          label="Active links"
          value={String(data.request_counts.pending ?? 0)}
          hint="Ready to share"
          icon={Link2}
          tone="blue"
        />
        <StatCard
          label="Confirmed"
          value={String(data.request_counts.confirmed ?? 0)}
          hint="Completed requests"
          icon={CircleCheck}
          tone="violet"
        />
      </div>
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold">Recent payment requests</h2>
        <Link
          to="/dashboard/payment-links"
          className="text-sm font-semibold text-emerald-700"
        >
          View all →
        </Link>
      </div>
      {links.length ? (
        <PaymentTable links={links} />
      ) : (
        <EmptyState
          title="No payment links yet"
          description="Create a payment link to start accepting BCH."
        />
      )}
    </div>
  )
}

export function LinksPage() {
  const [search, setSearch] = useState("")
  const [filter, setFilter] = useState("all")
  const [page, setPage] = useState(1)
  const size = 8
  const query = useQuery({
    queryKey: ["payment-links", search, filter, page],
    refetchInterval: 10000,
    queryFn: () =>
      listLinks({
        search: search || undefined,
        status: filter === "all" ? undefined : filter,
        limit: size,
        offset: (page - 1) * size,
      }),
  })
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
          {["all", "draft", "pending", "confirmed", "expired", "cancelled"].map(
            (status) => (
              <option key={status} value={status}>
                {status === "all"
                  ? "All statuses"
                  : status[0].toUpperCase() + status.slice(1)}
              </option>
            ),
          )}
        </select>
      </div>
      {query.data ? (
        query.data.data.length ? (
          <PaymentTable links={query.data.data} />
        ) : (
          <EmptyState
            title="No matching links"
            description="Try another search or create a payment link."
          />
        )
      ) : (
        <QueryState loading={query.isPending} error={query.error} />
      )}
      {!!query.data?.count && (
        <PageControls
          page={page}
          count={query.data.count}
          size={size}
          setPage={setPage}
        />
      )}
    </div>
  )
}

function LinkFields({
  values,
  setValues,
  includeReference = false,
}: {
  values: LinkForm
  setValues: (value: LinkForm) => void
  includeReference?: boolean
}) {
  function set(key: keyof LinkForm, value: string) {
    setValues({ ...values, [key]: value })
  }
  return (
    <div className="space-y-5">
      {includeReference && (
        <Field id="reference" label="Invoice reference" required>
          <Input
            id="reference"
            required
            maxLength={255}
            value={values.orderReference}
            onChange={(e) => set("orderReference", e.target.value)}
          />
        </Field>
      )}
      <Field id="title" label="Title / invoice name" required>
        <Input
          id="title"
          required
          maxLength={255}
          value={values.title}
          onChange={(e) => set("title", e.target.value)}
          placeholder="Website design deposit"
        />
      </Field>
      <Field id="amount" label="Amount (BCH)" required>
        <Input
          id="amount"
          required
          inputMode="decimal"
          value={values.amount}
          onChange={(e) => set("amount", e.target.value)}
          placeholder="0.05"
        />
      </Field>
      <Field id="address" label="BCH receiving address" required>
        <Input
          id="address"
          required
          value={values.address}
          onChange={(e) => set("address", e.target.value)}
          placeholder="CashAddr for the selected network"
          autoComplete="off"
        />
        <p className="mt-1 text-xs text-slate-500">
          You can reuse your receiving address. Reused or historical
          destinations require reviewing detected outputs on the request detail
          screen. Newly tracked single-request destinations can be credited
          automatically.
        </p>
      </Field>
      <Field id="description" label="Description (optional)">
        <textarea
          id="description"
          className="dashboard-control min-h-24 w-full px-3 py-2 text-sm"
          maxLength={2000}
          value={values.description}
          onChange={(e) => set("description", e.target.value)}
        />
      </Field>
      <Field id="expiry" label="Expiry (optional)">
        <Input
          id="expiry"
          type="datetime-local"
          value={values.expiry}
          onChange={(e) => set("expiry", e.target.value)}
        />
      </Field>
    </div>
  )
}
type LinkForm = {
  orderReference: string
  title: string
  amount: string
  address: string
  description: string
  expiry: string
}
function localDatetime(value: string) {
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16)
}
function defaultForm(): LinkForm {
  return {
    orderReference: `PP-${crypto.randomUUID().slice(0, 8).toUpperCase()}`,
    title: "",
    amount: "",
    address: "",
    description: "",
    expiry: "",
  }
}
function validateForm(values: LinkForm): string | null {
  if (!values.orderReference.trim() || !values.title.trim())
    return "Enter an invoice reference and title."
  if (
    !/^\d+(\.\d{1,8})?$/.test(values.amount.trim()) ||
    !/[1-9]/.test(values.amount)
  )
    return "Enter a positive BCH amount with up to 8 decimal places."
  if (!validAddress(values.address.trim()))
    return "Enter a valid BCH CashAddr for the deployment network."
  if (values.expiry && new Date(values.expiry).getTime() <= Date.now())
    return "Choose a future expiry date and time."
  return null
}
export function NewLinkPage() {
  const navigate = useNavigate()
  const cache = useQueryClient()
  const [values, setValues] = useState<LinkForm>(defaultForm)
  const settings = useQuery({
    queryKey: ["merchant-settings"],
    queryFn: getMerchantSettings,
  })
  const [error, setError] = useState("")
  const create = useMutation({
    mutationFn: createLink,
    onSuccess: (link) => {
      cache.invalidateQueries({ queryKey: ["payment-links"] })
      cache.invalidateQueries({ queryKey: ["payment-summary"] })
      toast.success("Payment link created")
      navigate({ to: "/dashboard/payment-links/$id", params: { id: link.id } })
    },
    onError: (reason) => setError(errorMessage(reason)),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    const problem =
      validateForm(values) ||
      (settings.data &&
      !validAddress(values.address.trim(), settings.data.network)
        ? `Use a valid ${settings.data.network} receiving address.`
        : null)
    if (problem) {
      setError(problem)
      return
    }
    setError("")
    create.mutate({
      ...values,
      title: values.title.trim(),
      orderReference: values.orderReference.trim(),
      address: values.address.trim(),
      amount: values.amount.trim(),
      expiresAt: values.expiry ? new Date(values.expiry).toISOString() : null,
    })
  }
  return (
    <div className="mx-auto max-w-5xl space-y-6">
      <PageHeader
        eyebrow="Payment links"
        title="Create payment link"
        description="Set the details your customer will see at checkout."
      />
      <form
        onSubmit={submit}
        className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]"
      >
        <div className={`${card} space-y-5`}>
          <h2 className="border-b pb-4 font-semibold">Payment details</h2>
          <p className="text-sm text-emerald-800">
            Network: {settings.data?.network ?? "Loading…"} · Receiving wallet:{" "}
            {settings.data?.business_name ?? "Your merchant wallet"}
          </p>
          <LinkFields values={values} setValues={setValues} includeReference />
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
            <Button type="submit" disabled={create.isPending}>
              Create link <ArrowRight />
            </Button>
          </div>
        </div>
        <aside className="space-y-4">
          <div className={`${card} space-y-3`}>
            <Wallet className="size-6 text-emerald-700" />
            <h2 className="font-semibold">Direct to your wallet</h2>
            <p className="text-sm leading-6 text-slate-500">
              Customers can scan the QR code or open the payment URI in a BCH
              wallet.
            </p>
          </div>
          <DemoNotice />
        </aside>
      </form>
    </div>
  )
}

function DraftEditor({ link }: { link: PaymentLink }) {
  const cache = useQueryClient()
  const [values, setValues] = useState<LinkForm>({
    orderReference: link.orderReference,
    title: link.title,
    amount: link.amount,
    address: link.address,
    description: link.description,
    expiry: localDatetime(link.expiresAt),
  })
  const [error, setError] = useState("")
  const update = useMutation({
    mutationFn: () =>
      updateLink(link.id, {
        ...values,
        expiresAt: values.expiry ? new Date(values.expiry).toISOString() : null,
      }),
    onSuccess: () => {
      cache.invalidateQueries({ queryKey: ["payment-link", link.id] })
      cache.invalidateQueries({ queryKey: ["payment-links"] })
      toast.success("Draft saved")
    },
    onError: (reason) => setError(errorMessage(reason)),
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    const problem = validateForm(values)
    if (problem) {
      setError(problem)
      return
    }
    update.mutate()
  }
  return (
    <form onSubmit={submit} className={`${card} space-y-5`}>
      <h2 className="font-semibold">Edit draft</h2>
      <LinkFields values={values} setValues={setValues} />
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
      <Button type="submit" disabled={update.isPending}>
        Save draft
      </Button>
    </form>
  )
}
export function LinkDetails({ id }: { id: string }) {
  const cache = useQueryClient()
  const navigate = useNavigate()
  const query = useQuery(linkQuery(id))
  const [error, setError] = useState("")
  const issue = useMutation({
    mutationFn: () => issueLink(id),
    onSuccess: () => {
      cache.invalidateQueries({ queryKey: ["payment-link", id] })
      cache.invalidateQueries({ queryKey: ["payment-links"] })
      cache.invalidateQueries({ queryKey: ["payment-summary"] })
      toast.success("Request issued")
    },
    onError: (reason) => setError(errorMessage(reason)),
  })
  const cancel = useMutation({
    mutationFn: () => cancelLink(id),
    onSuccess: () => {
      cache.invalidateQueries({ queryKey: ["payment-link", id] })
      cache.invalidateQueries({ queryKey: ["payment-links"] })
      cache.invalidateQueries({ queryKey: ["payment-summary"] })
      toast.success("Request cancelled")
    },
    onError: (reason) => setError(errorMessage(reason)),
  })
  const remove = useMutation({
    mutationFn: () => deleteLink(id),
    onSuccess: () => {
      cache.invalidateQueries({ queryKey: ["payment-links"] })
      cache.invalidateQueries({ queryKey: ["payment-summary"] })
      toast.success("Draft deleted")
      navigate({ to: "/dashboard/payment-links" })
    },
    onError: (reason) => setError(errorMessage(reason)),
  })
  if (!query.data)
    return <QueryState loading={query.isPending} error={query.error} />
  const link = query.data
  const shareable = link.status !== "draft" && link.status !== "cancelled"
  const url = checkoutUrl(link)
  return (
    <div className="space-y-6">
      <Link
        to="/dashboard/payment-links"
        className="inline-flex items-center gap-1 text-sm text-slate-500"
      >
        <ArrowLeft className="size-4" />
        Payment links
      </Link>
      <div className="grid gap-6 lg:grid-cols-[1.2fr_.8fr]">
        <section className={`${card} space-y-5`}>
          <div className="grid size-14 place-items-center rounded-2xl bg-emerald-50 text-emerald-700">
            <Link2 />
          </div>
          <h1 className="text-3xl font-bold">{link.title}</h1>
          <LinkStatus link={link} />
          {shareable ? (
            <>
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
                  onFocus={(event) => event.currentTarget.select()}
                />
              </div>
              <div className="flex flex-wrap gap-2">
                <CopyButton value={url} label="Copy link" variant="default" />
                <a
                  href={url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-2 rounded-lg border px-4 text-sm"
                >
                  <ExternalLink className="size-4" />
                  Preview checkout
                </a>
                <Link
                  to="/dashboard/payment-links/$id/qr"
                  params={{ id }}
                  className="inline-flex items-center rounded-lg border px-4 text-sm"
                >
                  Show QR
                </Link>
              </div>
            </>
          ) : (
            <p className="text-sm text-slate-500">
              {link.status === "draft"
                ? "Issue this draft to make checkout available."
                : "This request has been cancelled."}
            </p>
          )}
          <div className="flex flex-wrap gap-2 border-t pt-4">
            {link.status === "draft" && (
              <>
                <Button
                  disabled={issue.isPending}
                  onClick={() => issue.mutate()}
                >
                  Issue request
                </Button>
                <Button
                  variant="outline"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm("Delete this unpublished draft?"))
                      remove.mutate()
                  }}
                >
                  Delete draft
                </Button>
              </>
            )}
            {link.status === "pending" && !isExpired(link) && (
              <Button
                variant="outline"
                disabled={cancel.isPending}
                onClick={() => {
                  if (window.confirm("Cancel this unpaid request?"))
                    cancel.mutate()
                }}
              >
                Cancel request
              </Button>
            )}
          </div>
          {error && (
            <p role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
        </section>
        <section className={card}>
          <h2 className="mb-3 font-semibold">Request details</h2>
          {link.verificationStale && link.status !== "draft" && (
            <p role="status" className="mb-3 text-sm text-amber-800">
              Payment verification is not current.
            </p>
          )}
          <dl>
            <DetailRow label="Reference" value={link.orderReference} />
            <DetailRow label="Amount" value={`${link.amount} BCH`} />
            <DetailRow label="Network" value={link.network} />
            <DetailRow
              label="Confirmation policy"
              value={link.requiredConfirmations}
            />
            <DetailRow label="Recipient" value={link.address} />
            <DetailRow label="Created" value={displayDate(link.createdAt)} />
            <DetailRow label="Expires" value={displayDate(link.expiresAt)} />
            <DetailRow label="Payment" value={link.paymentStatus} />
          </dl>
          <div className="mt-4 space-y-3 text-sm">
            {link.payments.map((p) => (
              <div key={p.id} className="rounded-lg border p-3">
                <ExplorerLink network={link.network} txid={p.txid} />
                <p>
                  {satsToBch(p.amount_sats)} BCH · {p.confirmations}{" "}
                  confirmations · {p.status}
                  {p.is_late ? " · Late payment — review required" : ""}
                </p>
              </div>
            ))}
          </div>
          {link.description && (
            <p className="mt-4 text-sm text-slate-500">{link.description}</p>
          )}
          {link.receiptId && (
            <Link
              to="/r/$publicReceiptId"
              params={{ publicReceiptId: link.receiptId }}
              className="mt-4 inline-block text-emerald-700"
            >
              View receipt →
            </Link>
          )}
        </section>
      </div>
      {link.status !== "draft" && <PaymentAllocation link={link} />}
      {link.status === "draft" && (
        <DraftEditor key={link.id + link.createdAt} link={link} />
      )}
    </div>
  )
}

function PaymentAllocation({ link }: { link: PaymentLink }) {
  const cache = useQueryClient()
  const [txid, setTxid] = useState("")
  const [reviewedTxid, setReviewedTxid] = useState("")
  const [rows, setRows] = useState<ReviewedOutput[]>([])
  const [selected, setSelected] = useState<number[]>([])
  const [error, setError] = useState("")
  const detected = useQuery({
    queryKey: ["detected-outputs", link.id],
    queryFn: () => detectedOutputs(link.id),
    refetchInterval: 10000,
  })
  const review = useMutation({
    mutationFn: (transaction: string) => reviewOutputs(link.id, transaction),
    onSuccess: async (data, transaction) => {
      setRows(data)
      setReviewedTxid(transaction)
      setSelected([])
      setError("")
      await Promise.all(
        [
          ["payment-link", link.id],
          ["payment-links"],
          ["payment-summary"],
          ["receipts"],
          ["public-receipt"],
          ["public-link", link.publicId],
        ].map((queryKey) => cache.invalidateQueries({ queryKey })),
      )
    },
    onError: (reason) => setError(errorMessage(reason)),
  })
  const allocate = useMutation({
    mutationFn: () => allocateOutputs(link.id, reviewedTxid, selected),
    onSuccess: async (updated) => {
      setRows([])
      setSelected([])
      setError("")
      await refreshPaymentQueries(cache, updated)
      toast.success("Verified outputs assigned to this request")
    },
    onError: (reason) => setError(errorMessage(reason)),
  })
  return (
    <section className={`${card} space-y-4`}>
      <h2 className="font-semibold">Review and allocate payments</h2>
      <p className="text-sm text-slate-500">
        Detected outputs are unassigned and do not count toward this request or
        its receipt. Confirm which request the payment belongs to before
        assigning it. Expired or cancelled requests retain the late-payment
        policy.
      </p>
      {detected.isPending && <p role="status">Loading detected payments…</p>}
      {detected.error && <p role="alert">{errorMessage(detected.error)}</p>}
      <p className="text-sm text-slate-500">
        Server payment monitoring runs independently of the wallet connection.
      </p>
      {detected.data && (
        <div className="text-sm" role="status">
          <p>
            Last successful address scan:{" "}
            {displayDate(detected.data.last_successful_scan_at)}
          </p>
          {detected.data.scan_status === "failed" && (
            <p className="text-amber-800">
              The latest address scan failed. Saved observations may be
              incomplete; an empty list does not mean no payment arrived.
            </p>
          )}
          {detected.data.scan_status === "never" && (
            <p className="text-amber-800">
              No successful address scan yet. Check the payment worker and
              provider.
            </p>
          )}
          {detected.data.scan_status === "stale" && (
            <p className="text-amber-800">
              Address monitoring is stale. Displaying saved observations.
            </p>
          )}
          {detected.data.scan_status === "current" &&
            detected.data.outputs.length === 0 && (
              <p>
                No unassigned outputs detected in the last successful scan. You
                can also enter a transaction ID.
              </p>
            )}
        </div>
      )}
      {detected.data?.outputs.map((output) => (
        <div
          key={`${output.txid}:${output.vout}`}
          className="flex flex-wrap items-center gap-3 rounded-lg border p-3 text-sm"
        >
          <span className="break-all">
            {output.txid}:{output.vout} · {satsToBch(output.amount_sats)} BCH ·{" "}
            {output.confirmations} confirmations
          </span>
          <Button
            variant="outline"
            disabled={review.isPending || allocate.isPending}
            onClick={() => {
              setTxid(output.txid)
              setRows([])
              review.mutate(output.txid)
            }}
          >
            Review transaction
          </Button>
        </div>
      ))}
      <form
        className="flex gap-3"
        onSubmit={(event) => {
          event.preventDefault()
          setRows([])
          review.mutate(txid.trim())
        }}
      >
        <Input
          aria-label="Transaction ID"
          placeholder="Transaction ID"
          value={txid}
          onChange={(event) => {
            setTxid(event.target.value)
            setRows([])
            setSelected([])
          }}
          required
          pattern="[a-fA-F0-9]{64}"
        />
        <Button type="submit" disabled={review.isPending || allocate.isPending}>
          {review.isPending ? "Verifying…" : "Verify outputs"}
        </Button>
      </form>
      {rows.map((output) => (
        <label
          key={output.vout}
          className="flex items-center gap-3 rounded-lg border p-3 text-sm"
        >
          <input
            type="checkbox"
            disabled={output.allocated || allocate.isPending}
            checked={selected.includes(output.vout)}
            onChange={(event) =>
              setSelected(
                event.target.checked
                  ? [...selected, output.vout]
                  : selected.filter((vout) => vout !== output.vout),
              )
            }
          />
          Output {output.vout} · {satsToBch(output.amount_sats)} BCH ·{" "}
          {output.confirmations} confirmations
          {output.allocated &&
            (output.assigned_to_this_invoice
              ? " · Allocated to this request"
              : " · Allocated to another request")}
          {output.allocated &&
            !output.assigned_to_this_invoice &&
            output.allocated_invoice_id && (
              <Link
                to="/dashboard/payment-links/$id"
                params={{ id: output.allocated_invoice_id }}
                className="text-emerald-700 underline"
              >
                {output.allocated_order_reference ?? "View allocated request"}
              </Link>
            )}
        </label>
      ))}
      {rows.length > 0 && (
        <Button
          disabled={
            selected.length === 0 || allocate.isPending || review.isPending
          }
          onClick={() => allocate.mutate()}
        >
          {allocate.isPending
            ? "Assigning…"
            : "Assign selected outputs to this request"}
        </Button>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      )}
    </section>
  )
}

export function MerchantQR({ id }: { id: string }) {
  const query = useQuery(linkQuery(id))
  if (!query.data)
    return <QueryState loading={query.isPending} error={query.error} />
  const link = query.data
  if (link.status === "draft" || link.status === "cancelled")
    return (
      <EmptyState
        title="QR unavailable"
        description="Issue the request before sharing it."
      />
    )
  const url = checkoutUrl(link)
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        eyebrow="Payment links"
        title="Payment QR code"
        description="Display or share this request with your customer."
      />
      <div className="grid gap-6 md:grid-cols-2">
        <div className={`${card} space-y-5 text-center`}>
          <h2 className="font-semibold">Checkout QR</h2>
          <QRDisplay value={url} label="Scan to open checkout" large />
          <CopyButton value={url} label="Copy checkout URL" />
          <p className="break-all text-xs text-slate-500">{url}</p>
        </div>
        <div className={`${card} space-y-5`}>
          <h2 className="text-xl font-bold">{link.title}</h2>
          <p className="text-3xl font-bold text-emerald-700">
            {link.amount} BCH
          </p>
          <dl>
            <DetailRow label="Status" value={<LinkStatus link={link} />} />
            <DetailRow label="Expires" value={displayDate(link.expiresAt)} />
            <DetailRow label="Network" value={link.network} />
            <DetailRow
              label="Confirmation policy"
              value={link.requiredConfirmations}
            />
            <DetailRow label="Recipient" value={link.address} />
          </dl>
          {link.paymentUri && (
            <CopyButton value={link.paymentUri} label="Copy payment URI" />
          )}
          <PrintButton />
        </div>
      </div>
    </div>
  )
}

export function TransactionsPage() {
  const csv = useMutation({
    mutationFn: exportPayments,
    onError: (error) => toast.error(errorMessage(error)),
  })
  const [search, setSearch] = useState("")
  const [status, setStatus] = useState("all")
  const [page, setPage] = useState(1)
  const size = 10
  const query = useQuery({
    queryKey: ["payments", search, status, page],
    refetchInterval: 10000,
    queryFn: () =>
      listPayments({
        search: search || undefined,
        status: status === "all" ? undefined : status,
        limit: size,
        offset: (page - 1) * size,
      }),
  })
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Payments"
        title="Transactions"
        description="Payment outputs associated with your requests."
        action={
          <Button
            variant="outline"
            disabled={csv.isPending}
            onClick={() => csv.mutate()}
          >
            {csv.isPending ? "Exporting…" : "Export CSV"}
          </Button>
        }
      />
      <div className="dashboard-card flex flex-wrap gap-3 p-4">
        <SearchField
          value={search}
          onChange={(value) => {
            setSearch(value)
            setPage(1)
          }}
          placeholder="Search transactions"
        />
        <select
          aria-label="Filter transactions"
          className="dashboard-control h-9 px-3 text-sm"
          value={status}
          onChange={(event) => {
            setStatus(event.target.value)
            setPage(1)
          }}
        >
          {["all", "detected", "confirmed", "orphaned"].map((value) => (
            <option key={value} value={value}>
              {value === "all"
                ? "All statuses"
                : value[0].toUpperCase() + value.slice(1)}
            </option>
          ))}
        </select>
      </div>
      {query.data ? (
        query.data.data.length ? (
          <div className="dashboard-card overflow-x-auto">
            <table className="dashboard-table w-full min-w-[650px] text-left text-sm">
              <thead className="border-b bg-[#f8faf9]">
                <tr>
                  <th className="p-4">Date</th>
                  <th className="p-4">Amount</th>
                  <th className="p-4">Transaction ID</th>
                  <th className="p-4">Status</th>
                  <th className="p-4">Confirmations</th>
                </tr>
              </thead>
              <tbody>
                {query.data.data.map((payment) => (
                  <tr key={payment.id} className="border-b last:border-0">
                    <td className="p-4">
                      {displayDate(payment.first_seen_at)}
                    </td>
                    <td className="p-4">
                      {satsToBch(payment.amount_sats)} BCH
                    </td>
                    <td className="p-4 font-mono">
                      <Link
                        to="/dashboard/transactions/$id"
                        params={{ id: payment.id }}
                        className="text-emerald-700 hover:underline"
                      >
                        {payment.txid.slice(0, 16)}…
                      </Link>
                    </td>
                    <td className="p-4">
                      <StatusBadge status={payment.status} />
                    </td>
                    <td className="p-4">{payment.confirmations}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No transactions yet"
            description="Transaction records appear when a payment is observed."
          />
        )
      ) : (
        <QueryState loading={query.isPending} error={query.error} />
      )}
      {!!query.data?.count && (
        <PageControls
          page={page}
          count={query.data.count}
          size={size}
          setPage={setPage}
        />
      )}
    </div>
  )
}
export function TransactionDetails({ id }: { id: string }) {
  const payment = useQuery({
    queryKey: ["payment", id],
    queryFn: () => getPayment(id),
    refetchInterval: 10000,
  })
  const invoice = useQuery({
    queryKey: ["payment-link", payment.data?.invoice_id],
    queryFn: () => getLink(payment.data!.invoice_id),
    enabled: !!payment.data,
    refetchInterval: 10000,
  })
  if (!payment.data)
    return <QueryState loading={payment.isPending} error={payment.error} />
  const data = payment.data
  return (
    <div className="space-y-6">
      <PageHeader title="Transaction details" />
      {invoice.error && <QueryState loading={false} error={invoice.error} />}
      <div className={card}>
        <dl>
          <DetailRow
            label="Payment"
            value={invoice.data?.title ?? data.invoice_id}
          />
          <DetailRow
            label="Amount"
            value={`${satsToBch(data.amount_sats)} BCH`}
          />
          <DetailRow label="Network" value={data.network} />
          <DetailRow
            label="Late payment"
            value={data.is_late ? "Yes — merchant review required" : "No"}
          />
          <DetailRow
            label="Transaction ID"
            value={<ExplorerLink network={data.network} txid={data.txid} />}
          />
          <DetailRow label="Output" value={data.vout} />
          <DetailRow label="Confirmations" value={data.confirmations} />
          <DetailRow
            label="Status"
            value={<StatusBadge status={data.status} />}
          />
        </dl>
        {invoice.data?.receiptId && (
          <Link
            to="/r/$publicReceiptId"
            params={{ publicReceiptId: invoice.data.receiptId }}
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
  const [page, setPage] = useState(1)
  const size = 10
  const query = useQuery({
    queryKey: ["receipts", search, page],
    refetchInterval: 10000,
    queryFn: () =>
      listReceipts({
        search: search || undefined,
        limit: size,
        offset: (page - 1) * size,
      }),
  })
  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Payments"
        title="Receipts"
        description="Share proof when a payment has been verified."
      />
      <div className="dashboard-card p-4">
        <SearchField
          value={search}
          onChange={(value) => {
            setSearch(value)
            setPage(1)
          }}
          placeholder="Search receipts"
        />
      </div>
      {query.data ? (
        query.data.data.length ? (
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
                {query.data.data.map((receipt) => (
                  <tr key={receipt.id} className="border-b last:border-0">
                    <td className="p-4 font-medium">{receipt.reference}</td>
                    <td className="p-4">{receipt.invoice_reference}</td>
                    <td className="p-4">
                      {satsToBch(receipt.amount_sats)} BCH
                    </td>
                    <td className="p-4">{displayDate(receipt.verified_at)}</td>
                    <td className="p-4">{receipt.current_status}</td>
                    <td className="flex gap-3 p-4">
                      <Link
                        to="/r/$publicReceiptId"
                        params={{ publicReceiptId: receipt.public_token }}
                        className="text-emerald-700 hover:underline"
                      >
                        View
                      </Link>
                      <CopyButton
                        value={receiptUrl(receipt.public_token)}
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
            description="Receipts become available after a payment has been verified."
          />
        )
      ) : (
        <QueryState loading={query.isPending} error={query.error} />
      )}
      {!!query.data?.count && (
        <PageControls
          page={page}
          count={query.data.count}
          size={size}
          setPage={setPage}
        />
      )}
    </div>
  )
}

function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-[#f5f8f8] px-4 py-8 text-slate-900 sm:py-14">
      <div className="mx-auto max-w-xl">
        <Link
          to="/"
          className="mb-8 inline-flex items-center gap-2 text-xl font-bold tracking-tight text-[#14252f]"
        >
          <span className="grid size-9 place-items-center rounded-xl bg-emerald-700 text-white">
            <CircleCheck className="size-5" />
          </span>
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
function PublicState({ loading, error }: { loading: boolean; error: unknown }) {
  return (
    <PublicShell>
      {loading ? (
        <QueryState loading error={null} />
      ) : (
        <EmptyState
          title="Request unavailable"
          description={
            error ? errorMessage(error) : "This request could not be found."
          }
        />
      )}
    </PublicShell>
  )
}
function effectiveStatus(
  status: PaymentStatus,
  expiresAt: string,
  paymentStatus: string,
): PaymentStatus {
  if (status === "pending" && new Date(expiresAt).getTime() <= Date.now())
    return "expired"
  if (status === "pending" && ["detected", "partial"].includes(paymentStatus))
    return paymentStatus as PaymentStatus
  return status
}
export function Checkout({ publicId }: { publicId: string }) {
  const query = useQuery({
    queryKey: ["public-link", publicId],
    queryFn: () => getPublicLink(publicId),
    refetchInterval: 5000,
  })
  if (!query.data)
    return <PublicState loading={query.isPending} error={query.error} />
  const link = query.data
  const status = effectiveStatus(
    link.status,
    link.expires_at,
    link.payment_status,
  )
  const payable =
    link.status === "pending" &&
    link.payment_status !== "detected" &&
    !!link.payment_uri
  return (
    <PublicShell>
      <div className="space-y-5">
        <div className={`${card} text-center`}>
          <div className="mx-auto mb-4 grid size-14 place-items-center rounded-full bg-emerald-50 text-emerald-700">
            <Wallet className="size-7" />
          </div>
          <p className="text-sm text-slate-500">Payment request from</p>
          <h1 className="text-xl font-semibold">{link.merchant_name}</h1>
          <p className="mt-2 text-sm font-medium text-emerald-800">
            Network: {link.network} · {link.required_confirmations}{" "}
            confirmation(s) required
          </p>
          <p className="mt-2 text-xs text-slate-500">
            Expires {displayDate(link.expires_at)}
          </p>
          <FundingEvidence link={link} />
          <p className="mt-4 text-sm text-slate-500">{link.title}</p>
          {link.description && (
            <p className="mt-1 text-sm text-slate-500">{link.description}</p>
          )}
          <p className="mt-5 rounded-xl bg-emerald-50 py-4 text-3xl font-bold text-emerald-800">
            {link.amount_bch} BCH
          </p>
          <div className="mt-5">
            <StatusBadge status={status} />
          </div>
          {payable ? (
            <>
              <div className="my-6">
                <QRDisplay
                  value={link.qr_payload || link.payment_uri!}
                  label="Scan to pay with a BCH wallet"
                />
              </div>
              <p className="text-xs text-slate-500">Recipient address</p>
              <p className="mt-1 break-all rounded-lg bg-slate-50 p-3 font-mono text-xs">
                {link.receiving_address}
              </p>
              <div className="mt-5 flex flex-wrap justify-center gap-2">
                <a href={link.payment_uri!} className={primaryLink}>
                  <Wallet className="size-4" />
                  Open wallet
                </a>
                <CopyButton
                  value={link.receiving_address}
                  label="Copy address"
                />
                <CopyButton
                  value={link.amount_due_bch}
                  label="Copy amount due"
                />
                <CopyButton
                  value={link.payment_uri!}
                  label="Copy payment URI"
                />
              </div>
            </>
          ) : (
            <p className="mt-5 text-sm text-slate-600">
              This request is not currently accepting payments.
            </p>
          )}
        </div>
        <DemoNotice />
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
  const query = useQuery({
    queryKey: ["public-link-status", publicId],
    queryFn: () => getPublicLink(publicId, true),
    refetchInterval: 5000,
  })
  if (!query.data)
    return <PublicState loading={query.isPending} error={query.error} />
  const link = query.data
  const status = effectiveStatus(
    link.status,
    link.expires_at,
    link.payment_status,
  )
  const heading = {
    draft: "Request unavailable",
    pending: "Waiting for payment",
    partial: "Partially paid",
    detected: "Payment detected",
    confirmed: "Payment confirmed",
    expired: "Request expired",
    cancelled: "Request cancelled",
    orphaned: "Payment requires review",
  }[status]
  return (
    <PublicShell>
      <div className="space-y-5">
        <div className={`${card} space-y-6 text-center`}>
          <div className="mx-auto grid size-16 place-items-center rounded-full bg-emerald-50 text-emerald-700">
            {status === "confirmed" ? (
              <CircleCheck className="size-8" />
            ) : (
              <Clock3 className="size-8" />
            )}
          </div>
          <div>
            <StatusBadge status={status} />
            <h1 className="mt-3 text-2xl font-semibold">{heading}</h1>
            <p className="mt-2 text-sm text-slate-500">
              A checkout visit or QR scan does not confirm payment.
            </p>
          </div>
          <FundingEvidence link={link} />
          <PaymentTimeline status={status} />
          <p className="mt-3 text-sm text-slate-500">
            After sending BCH, the merchant reviews and assigns the verified
            payment to this request. The status updates after allocation and
            chain confirmation.
          </p>
          <dl className="text-left">
            <DetailRow label="Invoice" value={link.title} />
            <DetailRow label="Amount" value={`${link.amount_bch} BCH`} />
            <DetailRow label="Recipient" value={link.receiving_address} />
            <DetailRow label="Expires" value={displayDate(link.expires_at)} />
          </dl>
          {link.receipt_url && (
            <Link
              to="/r/$publicReceiptId"
              params={{ publicReceiptId: link.receipt_url.split("/").pop()! }}
              className="text-sm font-medium text-emerald-700"
            >
              View receipt →
            </Link>
          )}
          <Button
            variant="outline"
            onClick={() => query.refetch()}
            disabled={query.isFetching}
          >
            Refresh status
          </Button>
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
  const query = useQuery({
    queryKey: ["public-receipt", publicReceiptId],
    queryFn: () => getPublicReceipt(publicReceiptId),
    refetchInterval: 10000,
  })
  if (!query.data)
    return <PublicState loading={query.isPending} error={query.error} />
  const receipt = query.data
  return (
    <PublicShell>
      <div className={`${card} space-y-6`}>
        <div className="text-center">
          <div className="mx-auto mb-4 grid size-16 place-items-center rounded-full bg-emerald-50 text-emerald-700">
            <ReceiptIcon className="size-8" />
          </div>
          <h1 className="text-2xl font-semibold">Payment receipt</h1>
          <p className="mt-2 text-sm text-slate-500">{receipt.statement}</p>
        </div>
        <dl>
          <DetailRow
            label="Amount"
            value={`${satsToBch(receipt.amount_sats)} BCH`}
          />
          <DetailRow
            label="Requested"
            value={`${satsToBch(receipt.requested_amount_sats)} BCH`}
          />
          <DetailRow label="Network" value={receipt.network} />
          <DetailRow label="Destination" value={receipt.receiving_address} />
          <DetailRow label="Merchant" value={receipt.merchant_name} />
          <DetailRow label="Invoice" value={receipt.invoice_reference} />
          <DetailRow label="Receipt ID" value={receipt.reference} />
          <DetailRow
            label="Verified"
            value={displayDate(receipt.verified_at)}
          />
          <DetailRow
            label="Receipt evidence status"
            value={receipt.current_status}
          />
          <DetailRow
            label="Invoice payment status"
            value={receipt.invoice_payment_status}
          />
          <DetailRow
            label="Outputs"
            value={receipt.output_refs.join(", ") || "Unavailable"}
          />
        </dl>
        {receipt.verification_stale && (
          <p role="status" className="text-sm text-amber-800">
            Verification is stale. The provider has not recently checked this
            evidence. The status above is the last known payment status.
          </p>
        )}
        {receipt.missing_output_refs?.length > 0 && (
          <p role="alert" className="text-sm text-amber-800">
            Some credited output records are unavailable. This receipt requires
            reconciliation.
          </p>
        )}
        <div className="space-y-2 text-sm">
          <h2 className="font-semibold">Credited receipt outputs</h2>
          <p className="text-slate-500">
            Only the outputs recorded when this receipt was issued appear here.
            Later invoice payments are listed on the merchant request detail
            screen.
          </p>
          {receipt.payments.map((p) => (
            <p key={`${p.txid}:${p.vout}`}>
              <ExplorerLink network={receipt.network} txid={p.txid} /> · output{" "}
              {p.vout} · {satsToBch(p.amount_sats)} BCH · {p.confirmations}{" "}
              confirmations · {p.status}
            </p>
          ))}
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <CopyButton
            value={receiptUrl(publicReceiptId)}
            label="Copy receipt link"
            variant="default"
          />
          <PrintButton />
        </div>
      </div>
    </PublicShell>
  )
}

function ExplorerLink({ network, txid }: { network: string; txid: string }) {
  const url = explorerUrl(network, txid)
  return url ? (
    <a
      className="break-all text-emerald-700 underline"
      href={url}
      target="_blank"
      rel="noreferrer"
    >
      {txid}
    </a>
  ) : (
    <span className="break-all">{txid}</span>
  )
}
function FundingEvidence({
  link,
}: {
  link: import("./service").PublicCheckout
}) {
  return (
    <div className="my-3 space-y-2 text-sm text-slate-600" aria-live="polite">
      <p>
        Received: {satsToBch(link.received_amount_sats)} BCH · confirmed:{" "}
        {satsToBch(link.confirmed_amount_sats)} BCH
      </p>
      {link.payment_status === "partial" && (
        <p>
          Partially paid. Remaining due: {link.amount_due_bch} BCH. The QR
          requests only this remaining amount.
        </p>
      )}
      {link.overpaid_amount_sats > 0 && (
        <p>
          Overpayment: {satsToBch(link.overpaid_amount_sats)} BCH. Contact the
          merchant.
        </p>
      )}
      {link.late_amount_sats > 0 && (
        <p>
          Late payment recorded: {satsToBch(link.late_amount_sats)} BCH.
          Merchant review required.
        </p>
      )}
      {link.verification_stale && (
        <p className="text-amber-800">
          Verification is not current. Waiting for the backend provider.
        </p>
      )}
    </div>
  )
}

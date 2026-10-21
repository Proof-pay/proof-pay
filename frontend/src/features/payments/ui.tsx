import { Link } from "@tanstack/react-router"
import {
  Check,
  CircleAlert,
  Clock3,
  Copy,
  Download,
  ExternalLink,
  type LucideIcon,
  Printer,
  Radio,
  Search,
} from "lucide-react"
import { QRCodeSVG } from "qrcode.react"
import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import type { PaymentLink, PaymentStatus } from "./service"
import { checkoutUrl, displayDate, isExpired } from "./service"

export function DemoNotice() {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-[#f2dfb4] bg-[#fff9ec] px-4 py-3 text-sm text-[#79551d]">
      <CircleAlert className="mt-0.5 size-4 shrink-0" />
      <p>
        <strong>Demo mode</strong> · Payment requests are stored in this
        browser. No blockchain monitoring or payment verification is connected.
      </p>
    </div>
  )
}
export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "emerald",
}: {
  label: string
  value: string
  hint: string
  icon: LucideIcon
  tone?: "emerald" | "blue" | "amber" | "violet"
}) {
  const toneStyles = {
    emerald: "bg-emerald-50 text-emerald-700",
    blue: "bg-sky-50 text-sky-700",
    amber: "bg-amber-50 text-amber-700",
    violet: "bg-violet-50 text-violet-700",
  }
  return (
    <div className="dashboard-card p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-slate-500">{label}</p>
        <span
          className={`grid size-10 shrink-0 place-items-center rounded-xl ${toneStyles[tone]}`}
        >
          <Icon className="size-[19px]" />
        </span>
      </div>
      <p className="mt-3 text-[28px] font-bold tracking-[-.045em] text-[#14252f]">
        {value}
      </p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
    </div>
  )
}
export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-4">
      <div>
        {eyebrow && (
          <p className="mb-2 text-[11px] font-bold uppercase tracking-[.16em] text-emerald-700">
            {eyebrow}
          </p>
        )}
        <h1 className="text-[28px] font-bold tracking-[-.045em] text-[#14252f] sm:text-[32px]">
          {title}
        </h1>
        {description && (
          <p className="mt-1.5 text-sm text-slate-500">{description}</p>
        )}
      </div>
      {action}
    </div>
  )
}
export function StatusBadge({ status }: { status: PaymentStatus }) {
  const styles = {
    pending: "border border-amber-200 bg-amber-50 text-amber-800",
    detected: "border border-blue-200 bg-blue-50 text-blue-800",
    confirmed: "border border-green-200 bg-green-50 text-green-800",
    expired: "border border-red-200 bg-red-50 text-red-800",
  }
  const Icon = {
    pending: Clock3,
    detected: Radio,
    confirmed: Check,
    expired: CircleAlert,
  }[status]
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${styles[status]}`}
    >
      <Icon className="size-3.5" />
      {status === "detected"
        ? "Awaiting confirmation"
        : status[0].toUpperCase() + status.slice(1)}
    </span>
  )
}
export function LinkStatus({ link }: { link: PaymentLink }) {
  return <StatusBadge status={isExpired(link) ? "expired" : link.status} />
}
export function CopyButton({
  value,
  label = "Copy",
  variant = "outline",
}: {
  value: string
  label?: string
  variant?: "outline" | "default"
}) {
  const [copied, setCopied] = useState(false)
  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      toast.success("Copied to clipboard")
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error("Could not copy. Please select and copy the text.")
    }
  }
  return (
    <Button type="button" variant={variant} onClick={copy}>
      <Copy />
      {copied ? "Copied" : label}
    </Button>
  )
}
export function QRDisplay({
  value,
  label,
  large = false,
}: {
  value: string
  label: string
  large?: boolean
}) {
  const size = large ? 300 : 212
  function download() {
    const svg = document.getElementById(`qr-${label.replace(/\W/g, "-")}`)
    if (!svg) return
    const serialized = new XMLSerializer().serializeToString(svg)
    const blob = new Blob([serialized], { type: "image/svg+xml;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = "proofpay-qr.svg"
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <div className="flex flex-col items-center gap-4">
      <div className="max-w-full rounded-2xl border border-[#e3eaed] bg-white p-4 shadow-[0_8px_28px_rgba(20,45,50,.06)] sm:p-5">
        <QRCodeSVG
          id={`qr-${label.replace(/\W/g, "-")}`}
          value={value}
          size={size}
          marginSize={0}
          level="M"
          className="max-w-full h-auto"
        />
      </div>
      <p className="text-center text-sm text-slate-500">{label}</p>
      <Button type="button" variant="outline" onClick={download}>
        <Download />
        Download QR
      </Button>
    </div>
  )
}
export function EmptyState({
  title,
  description,
}: {
  title: string
  description: string
}) {
  return (
    <div className="dashboard-card px-6 py-16 text-center">
      <span className="mx-auto mb-4 grid size-14 place-items-center rounded-2xl bg-emerald-50 text-emerald-700">
        <Search className="size-6" />
      </span>
      <h2 className="font-semibold text-slate-900">{title}</h2>
      <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">
        {description}
      </p>
    </div>
  )
}
export function SearchField({
  value,
  onChange,
  placeholder = "Search",
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
}) {
  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-slate-400" />
      <Input
        aria-label={placeholder}
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="dashboard-control w-full pl-9 sm:w-72"
      />
    </div>
  )
}
export function PaymentTable({ links }: { links: PaymentLink[] }) {
  return (
    <div className="dashboard-card overflow-hidden">
      <div className="divide-y md:hidden">
        {links.map((link) => (
          <div key={link.id} className="p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <Link
                  to="/dashboard/payment-links/$id"
                  params={{ id: link.id }}
                  className="font-semibold text-slate-900 hover:text-emerald-700"
                >
                  {link.title}
                </Link>
                <p className="mt-1 text-xs text-slate-500">
                  {link.merchant} · {displayDate(link.createdAt)}
                </p>
              </div>
              <p className="shrink-0 font-bold text-slate-900">
                {link.amount} BCH
              </p>
            </div>
            <div className="mt-3 flex items-center justify-between gap-3">
              <LinkStatus link={link} />
              <Link
                to="/dashboard/payment-links/$id"
                params={{ id: link.id }}
                className="text-sm font-semibold text-emerald-700"
              >
                Details →
              </Link>
            </div>
          </div>
        ))}
      </div>
      <div className="hidden overflow-x-auto md:block">
        <table className="dashboard-table w-full min-w-[700px] text-left text-sm">
          <thead className="border-b bg-[#f8faf9]">
            <tr>
              <th className="px-5 py-4">Invoice</th>
              <th className="px-5 py-4">Amount</th>
              <th className="px-5 py-4">Created</th>
              <th className="px-5 py-4">Status</th>
              <th className="px-5 py-4">Action</th>
            </tr>
          </thead>
          <tbody>
            {links.map((link) => (
              <tr key={link.id} className="border-b last:border-0">
                <td className="px-5 py-4 font-medium">
                  <Link
                    to="/dashboard/payment-links/$id"
                    params={{ id: link.id }}
                    className="hover:text-emerald-700"
                  >
                    {link.title}
                  </Link>
                  <span className="block text-xs font-normal text-slate-500">
                    {link.merchant}
                  </span>
                </td>
                <td className="whitespace-nowrap px-5 py-4 font-semibold">
                  {link.amount} BCH
                </td>
                <td className="px-5 py-4 text-slate-500">
                  {displayDate(link.createdAt)}
                </td>
                <td className="px-5 py-4">
                  <LinkStatus link={link} />
                </td>
                <td className="px-5 py-4">
                  <div className="flex items-center gap-3 whitespace-nowrap">
                    <Link
                      to="/dashboard/payment-links/$id"
                      params={{ id: link.id }}
                      className="font-medium text-emerald-700 hover:underline"
                    >
                      Details
                    </Link>
                    <button
                      type="button"
                      className="text-emerald-700 hover:underline"
                      onClick={() =>
                        navigator.clipboard
                          .writeText(checkoutUrl(link))
                          .then(() => toast.success("Checkout link copied"))
                          .catch(() => toast.error("Could not copy link"))
                      }
                    >
                      Copy
                    </button>
                    <a
                      href={checkoutUrl(link)}
                      target="_blank"
                      rel="noreferrer"
                      className="text-emerald-700 hover:underline"
                    >
                      Preview
                    </a>
                    <Link
                      to="/dashboard/payment-links/$id/qr"
                      params={{ id: link.id }}
                      className="text-emerald-700 hover:underline"
                    >
                      QR
                    </Link>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
export function DetailRow({
  label,
  value,
}: {
  label: string
  value: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap justify-between gap-2 border-b py-3 text-sm last:border-0">
      <dt className="text-slate-500">{label}</dt>
      <dd className="max-w-full break-all font-medium text-slate-900">
        {value}
      </dd>
    </div>
  )
}
export function PrintButton() {
  return (
    <Button variant="outline" onClick={() => window.print()}>
      <Printer />
      Print
    </Button>
  )
}
export function ExplorerLink({ txid }: { txid: string | null }) {
  return txid ? (
    <a
      className="inline-flex items-center gap-1 text-emerald-700 hover:underline"
      href={`https://blockchair.com/bitcoin-cash/transaction/${txid}`}
      rel="noreferrer"
      target="_blank"
    >
      View on explorer <ExternalLink className="size-4" />
    </a>
  ) : (
    <span className="text-slate-400">Unavailable</span>
  )
}

export function PaymentTimeline({ status }: { status: PaymentStatus }) {
  const stage = status === "confirmed" ? 2 : status === "detected" ? 1 : 0
  return (
    <ol
      aria-label="Payment progress"
      className="grid grid-cols-3 gap-2 text-center text-xs"
    >
      {["Waiting", "Detected", "Confirmed"].map((label, index) => (
        <li key={label} className="space-y-2">
          <div
            className={`mx-auto grid size-7 place-items-center rounded-full ${index <= stage && status !== "expired" ? "bg-emerald-700 text-white" : "bg-slate-100 text-slate-500"}`}
          >
            {index < stage ? <Check className="size-4" /> : index + 1}
          </div>
          <span
            className={
              index <= stage && status !== "expired"
                ? "font-medium text-emerald-800"
                : "text-slate-500"
            }
          >
            {label}
          </span>
        </li>
      ))}
    </ol>
  )
}

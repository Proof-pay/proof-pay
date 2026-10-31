import { isAxiosError } from "axios"
import cashaddr from "cashaddrjs"
import { client } from "@/client/client.gen"

export type PaymentStatus =
  | "draft"
  | "pending"
  | "partial"
  | "detected"
  | "confirmed"
  | "expired"
  | "cancelled"
  | "orphaned"
export type Payment = {
  id: string
  invoice_id: string
  network: string
  is_late: boolean
  txid: string
  vout: number
  amount_sats: number
  confirmations: number
  status: "detected" | "confirmed" | "orphaned"
  first_seen_at: string
}
export type PaymentLink = {
  network: string
  requiredConfirmations: number
  verificationStale: boolean
  id: string
  publicId: string
  orderReference: string
  title: string
  description: string
  amount: string
  address: string
  createdAt: string
  expiresAt: string
  status: PaymentStatus
  paymentStatus: string
  checkoutPath: string
  paymentUri: string | null
  receiptId: string | null
  payments: Payment[]
}
export type InvoiceResponse = {
  network: string
  required_confirmations: number
  verification_stale: boolean
  id: string
  public_token: string
  order_reference: string
  title: string
  description: string | null
  amount_bch: string
  receiving_address: string
  created_at: string
  expires_at: string
  status: PaymentStatus
  payment_status: string
  checkout_url: string
  payment_uri: string | null
  receipt_token: string | null
  payments: Payment[]
}
export type PublicCheckout = {
  amount_due_bch: string
  network: string
  required_confirmations: number
  verification_stale: boolean
  late_amount_sats: number
  overpaid_amount_sats: number
  merchant_name: string
  title: string
  description: string | null
  order_reference: string
  amount_bch: string
  receiving_address: string
  expires_at: string
  status: PaymentStatus
  payment_status: string
  payment_uri: string | null
  qr_payload: string | null
  receipt_url: string | null
  received_amount_sats: number
  confirmed_amount_sats: number
}
export type Receipt = {
  network: string
  requested_amount_sats: number
  receiving_address: string
  verification_stale: boolean
  payments: Payment[]
  id: string
  public_token: string
  reference: string
  invoice_reference: string
  merchant_name: string
  amount_sats: number
  output_refs: string[]
  issued_at: string
  verified_at: string | null
  missing_output_refs: string[]
  invoice_payment_status: string
  verification_url: string
  current_status: string
  statement: string
}
export type PublicReceipt = Omit<Receipt, "id" | "public_token">
export type Summary = {
  confirmed_received_sats: number
  outstanding_requested_sats: number
  request_counts: Record<string, number>
  recent_activity: InvoiceResponse[]
}
export type Page<T> = { data: T[]; count: number }

const auth = [{ scheme: "bearer" as const, type: "http" as const }]
const base = "/api/v1"

export function errorMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === "string") return detail
    if (Array.isArray(detail))
      return detail.map((entry) => entry.msg).join("; ")
  }
  return error instanceof Error
    ? error.message
    : "The request failed. Please try again."
}
export function asLink(invoice: InvoiceResponse): PaymentLink {
  return {
    id: invoice.id,
    network: invoice.network,
    requiredConfirmations: invoice.required_confirmations,
    verificationStale: invoice.verification_stale,
    publicId: invoice.public_token,
    orderReference: invoice.order_reference,
    title: invoice.title,
    description: invoice.description ?? "",
    amount: invoice.amount_bch,
    address: invoice.receiving_address,
    createdAt: invoice.created_at,
    expiresAt: invoice.expires_at,
    status: invoice.status,
    paymentStatus: invoice.payment_status,
    checkoutPath: invoice.checkout_url,
    paymentUri: invoice.payment_uri,
    receiptId: invoice.receipt_token,
    payments: invoice.payments,
  }
}
export async function listLinks(
  params: {
    search?: string
    status?: string
    limit?: number
    offset?: number
  } = {},
) {
  const { data } = await client.get<
    { 200: Page<InvoiceResponse> },
    unknown,
    true
  >({
    url: `${base}/payment-requests`,
    security: auth,
    query: params,
    responseType: "json",
  })
  return { data: data.data.map(asLink), count: data.count }
}
export async function getLink(id: string) {
  const { data } = await client.get<{ 200: InvoiceResponse }, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}`,
    security: auth,
    responseType: "json",
  })
  return asLink(data)
}
export async function issueLink(id: string) {
  const { data } = await client.post<{ 200: InvoiceResponse }, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}/issue`,
    security: auth,
    responseType: "json",
  })
  return asLink(data)
}
export async function createLink(input: {
  title: string
  description: string
  amount: string
  address: string
  expiresAt: string | null
  orderReference: string
}) {
  const { data: draft } = await client.post<
    { 201: InvoiceResponse },
    unknown,
    true
  >({
    url: `${base}/payment-requests`,
    security: auth,
    responseType: "json",
    body: {
      order_reference: input.orderReference,
      title: input.title,
      description: input.description || null,
      amount_bch: input.amount,
      receiving_address: input.address,
      expires_at: input.expiresAt,
    },
  })
  try {
    return await issueLink(draft.id)
  } catch (error) {
    throw new Error(
      `Request saved as a draft, but could not be issued: ${errorMessage(error)}. Open payment links to retry.`,
    )
  }
}
export async function updateLink(
  id: string,
  input: {
    title: string
    description: string
    amount: string
    address: string
    expiresAt: string | null
  },
) {
  const { data } = await client.patch<{ 200: InvoiceResponse }, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}`,
    security: auth,
    responseType: "json",
    body: {
      title: input.title,
      description: input.description || null,
      amount_bch: input.amount,
      receiving_address: input.address,
      ...(input.expiresAt ? { expires_at: input.expiresAt } : {}),
    },
  })
  return asLink(data)
}
export async function cancelLink(id: string) {
  const { data } = await client.post<{ 200: InvoiceResponse }, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}/cancel`,
    security: auth,
    responseType: "json",
  })
  return asLink(data)
}
export async function deleteLink(id: string) {
  await client.delete<unknown, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}`,
    security: auth,
  })
}
export async function getPublicLink(token: string, status = false) {
  const { data } = await client.get<{ 200: PublicCheckout }, unknown, true>({
    url: `${base}/public/payment-requests/${encodeURIComponent(token)}${status ? "/status" : ""}`,
    responseType: "json",
  })
  return data
}
export async function listPayments(
  params: {
    search?: string
    status?: string
    limit?: number
    offset?: number
  } = {},
) {
  const { data } = await client.get<{ 200: Page<Payment> }, unknown, true>({
    url: `${base}/payments`,
    security: auth,
    query: params,
    responseType: "json",
  })
  return data
}
export async function getPayment(id: string) {
  const { data } = await client.get<{ 200: Payment }, unknown, true>({
    url: `${base}/payments/${encodeURIComponent(id)}`,
    security: auth,
    responseType: "json",
  })
  return data
}
export async function listReceipts(
  params: { search?: string; limit?: number; offset?: number } = {},
) {
  const { data } = await client.get<{ 200: Page<Receipt> }, unknown, true>({
    url: `${base}/receipts`,
    security: auth,
    query: params,
    responseType: "json",
  })
  return data
}
export async function getPublicReceipt(token: string) {
  const { data } = await client.get<{ 200: PublicReceipt }, unknown, true>({
    url: `${base}/public/receipts/${encodeURIComponent(token)}`,
    responseType: "json",
  })
  return data
}
export async function getSummary() {
  const { data } = await client.get<{ 200: Summary }, unknown, true>({
    url: `${base}/dashboard/summary`,
    security: auth,
    responseType: "json",
  })
  return data
}

export function validAddress(value: string, network?: string) {
  try {
    const prefix =
      network === "mainnet"
        ? "bitcoincash"
        : network === "regtest"
          ? "bchreg"
          : "bchtest"
    const decoded = cashaddr.decode(
      value.includes(":")
        ? value
        : `${network ? prefix : "bitcoincash"}:${value}`,
    )
    return network
      ? decoded.prefix === prefix
      : ["bitcoincash", "bchtest", "bchreg"].includes(decoded.prefix)
  } catch {
    // cashaddrjs predates token-aware z/r aliases. Let the authoritative API
    // validate their checksum and canonicalize to the identical BCH script.
    const prefix =
      network === "mainnet"
        ? "bitcoincash"
        : network === "regtest"
          ? "bchreg"
          : "bchtest"
    return new RegExp(
      `^${network ? prefix : "(?:bitcoincash|bchtest|bchreg)"}:[zr][qpzry9x8gf2tvdw0s3jn54khce6mua7l]{41,}$`,
      "i",
    ).test(value)
  }
}
export function explorerUrl(network: string, txid: string): string | null {
  if (!/^[a-f0-9]{64}$/i.test(txid)) return null
  const host = {
    mainnet: "https://blockexplorer.cash/mainnet/tx/",
    chipnet: "https://blockexplorer.cash/chipnet/tx/",
    testnet: "https://blockexplorer.cash/testnet3/tx/",
  }[network]
  return host ? `${host}${txid}` : null
}
export type MerchantSettings = {
  business_name: string
  receiving_address: string | null
  contact_email: string | null
  contact_phone: string | null
  network: string
  default_expiry_hours: number
  required_confirmations: number
}
export async function getMerchantSettings() {
  const { data } = await client.get<{ 200: MerchantSettings }, unknown, true>({
    url: `${base}/merchant/settings`,
    security: auth,
    responseType: "json",
  })
  return data
}
export async function saveMerchantSettings(
  body: Omit<MerchantSettings, "network">,
) {
  const { data } = await client.patch<{ 200: MerchantSettings }, unknown, true>(
    {
      url: `${base}/merchant/settings`,
      security: auth,
      responseType: "json",
      body,
    },
  )
  return data
}
export function checkoutUrl(link: PaymentLink) {
  const path = new URL(link.checkoutPath, window.location.origin).pathname
  return `${window.location.origin}${path}`
}
export function receiptUrl(id: string) {
  return `${window.location.origin}/r/${encodeURIComponent(id)}`
}
export function displayDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "No expiry"
}
export function isExpired(link: PaymentLink) {
  return (
    link.status === "expired" ||
    (link.status === "pending" &&
      new Date(link.expiresAt).getTime() < Date.now())
  )
}
export function satsToBch(sats: number) {
  const whole = Math.floor(sats / 100000000)
  const fraction = (sats % 100000000)
    .toString()
    .padStart(8, "0")
    .replace(/0+$/, "")
  return fraction ? `${whole}.${fraction}` : String(whole)
}

export async function exportPayments() {
  const { data } = await client.get<{ 200: Blob }, unknown, true>({
    url: `${base}/payments/export.csv`,
    security: auth,
    responseType: "blob",
  })
  const url = URL.createObjectURL(data)
  const anchor = document.createElement("a")
  anchor.href = url
  anchor.download = "proofpay-payments.csv"
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export type ReviewedOutput = {
  txid: string
  vout: number
  amount_sats: number
  confirmations: number
  allocated?: boolean
  allocated_invoice_id?: string | null
  allocated_order_reference?: string | null
  assigned_to_this_invoice?: boolean
}
export type PaymentMonitoring = {
  outputs: ReviewedOutput[]
  scan_status: "never" | "failed" | "stale" | "current"
  last_successful_scan_at: string | null
  last_scan_attempt_at: string | null
}
export async function detectedOutputs(id: string) {
  const { data } = await client.get<{ 200: PaymentMonitoring }, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}/monitoring`,
    security: auth,
    responseType: "json",
  })
  return data
}
export async function reviewOutputs(id: string, txid: string) {
  const { data } = await client.get<{ 200: ReviewedOutput[] }, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}/transactions/${encodeURIComponent(txid)}`,
    security: auth,
    responseType: "json",
  })
  return data
}
export async function allocateOutputs(
  id: string,
  txid: string,
  vouts: number[],
) {
  const { data } = await client.post<{ 200: InvoiceResponse }, unknown, true>({
    url: `${base}/payment-requests/${encodeURIComponent(id)}/claims/${encodeURIComponent(txid)}`,
    security: auth,
    responseType: "json",
    body: { vouts },
  })
  return asLink(data)
}

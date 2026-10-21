import { isAxiosError } from "axios"
import cashaddr from "cashaddrjs"
import { client } from "@/client/client.gen"

export type PaymentStatus =
  | "draft"
  | "pending"
  | "detected"
  | "confirmed"
  | "expired"
  | "cancelled"
  | "orphaned"
export type Payment = {
  id: string
  invoice_id: string
  txid: string
  vout: number
  amount_sats: number
  confirmations: number
  status: "detected" | "confirmed" | "orphaned"
  first_seen_at: string
}
export type PaymentLink = {
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
  id: string
  public_token: string
  reference: string
  invoice_reference: string
  merchant_name: string
  amount_sats: number
  output_refs: string[]
  issued_at: string
  verified_at: string
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

export function validAddress(value: string) {
  try {
    return (
      cashaddr.decode(
        value.startsWith("bitcoincash:") ? value : `bitcoincash:${value}`,
      ).prefix === "bitcoincash"
    )
  } catch {
    return false
  }
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

import cashaddr from "cashaddrjs"

export type PaymentStatus = "pending" | "detected" | "confirmed" | "expired"
export type PaymentLink = {
  id: string
  publicId: string
  title: string
  description: string
  amount: string
  address: string
  merchant: string
  createdAt: string
  expiresAt: string | null
  status: PaymentStatus
  txid: string | null
  confirmations: number
  receiptId: string | null
  demo: true
}

const key = "proofpay_demo_links_v1"
const fixture: PaymentLink = {
  id: "sample-request",
  publicId: "sample-request",
  title: "Website design deposit",
  description: "Initial design milestone",
  amount: "0.05",
  address: "",
  merchant: "Aung Studio",
  createdAt: "2026-10-15T09:00:00.000Z",
  expiresAt: null,
  status: "pending",
  txid: null,
  confirmations: 0,
  receiptId: "sample-receipt",
  demo: true,
}

export function listLinks(): PaymentLink[] {
  try {
    const stored = JSON.parse(
      localStorage.getItem(key) || "[]",
    ) as PaymentLink[]
    return [...stored, fixture]
  } catch {
    return [fixture]
  }
}

export function getLink(id: string) {
  return listLinks().find((link) => link.id === id || link.publicId === id)
}

export function createLink(
  input: Pick<
    PaymentLink,
    "title" | "description" | "amount" | "address" | "merchant" | "expiresAt"
  >,
) {
  const id = crypto.randomUUID()
  const link: PaymentLink = {
    ...input,
    id,
    publicId: id,
    createdAt: new Date().toISOString(),
    status: "pending",
    txid: null,
    confirmations: 0,
    receiptId: null,
    demo: true,
  }
  const stored = listLinks().filter((item) => item.id !== fixture.id)
  localStorage.setItem(key, JSON.stringify([link, ...stored]))
  return link
}

export function validAddress(value: string) {
  try {
    const decoded = cashaddr.decode(
      value.startsWith("bitcoincash:") ? value : `bitcoincash:${value}`,
    )
    return decoded.prefix === "bitcoincash"
  } catch {
    return false
  }
}

export function checkoutUrl(link: PaymentLink) {
  return `${window.location.origin}/p/${encodeURIComponent(link.publicId)}`
}
export function receiptUrl(id: string) {
  return `${window.location.origin}/r/${encodeURIComponent(id)}`
}
export function paymentUri(link: PaymentLink) {
  if (!link.address || !validAddress(link.address)) return null
  const address = link.address.startsWith("bitcoincash:")
    ? link.address
    : `bitcoincash:${link.address}`
  return `${address}?amount=${link.amount}`
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
    link.expiresAt !== null && new Date(link.expiresAt).getTime() < Date.now()
  )
}

export function sumAmounts(amounts: string[]) {
  const satoshis = amounts.reduce((total, amount) => {
    const [whole, fraction = ""] = amount.split(".")
    return total + BigInt(whole) * 100000000n + BigInt(fraction.padEnd(8, "0"))
  }, 0n)
  const whole = satoshis / 100000000n
  const fraction = (satoshis % 100000000n)
    .toString()
    .padStart(8, "0")
    .replace(/0+$/, "")
  return fraction ? `${whole}.${fraction}` : whole.toString()
}

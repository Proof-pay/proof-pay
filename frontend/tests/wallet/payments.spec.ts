import { expect, test } from "@playwright/test"

const checkout = {
  merchant_name: "Test merchant",
  title: "Design deposit",
  description: "A fixed BCH request",
  order_reference: "INV-42",
  network: "chipnet",
  required_confirmations: 2,
  expected_amount_sats: 100000000,
  amount_bch: "1",
  amount_due_bch: "0.6",
  receiving_address: "bchtest:q-example",
  expires_at: "2099-10-01T00:00:00Z",
  status: "pending",
  payment_status: "partial",
  payment_uri: "bchtest:q-example?amount=0.6",
  qr_payload: "bchtest:q-example?amount=0.6",
  received_amount_sats: 40000000,
  confirmed_amount_sats: 0,
  late_amount_sats: 0,
  overpaid_amount_sats: 0,
  receipt_url: null,
  verification_stale: false,
}

test("checkout uses remaining amount, reports network and polls authoritative confirmation", async ({
  page,
}) => {
  let confirmed = false
  await page.route("**/api/v1/public/payment-requests/*", (route) =>
    route.fulfill({
      json: confirmed
        ? {
            ...checkout,
            status: "confirmed",
            payment_status: "confirmed",
            amount_due_bch: "0",
            payment_uri: null,
            qr_payload: null,
            received_amount_sats: 100000000,
            confirmed_amount_sats: 100000000,
          }
        : checkout,
    }),
  )
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/p/test-token")
  await expect(
    page.getByText("Network: chipnet", { exact: false }),
  ).toBeVisible()
  await expect(page.getByText("Partial", { exact: true })).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Open wallet", exact: true }),
  ).toHaveAttribute("href", checkout.payment_uri)
  await expect(
    page.getByRole("button", { name: "Copy amount due" }),
  ).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  confirmed = true
  await expect(page.getByText("Confirmed", { exact: true })).toBeVisible({
    timeout: 12000,
  })
  await expect(
    page.getByRole("link", { name: "Open wallet", exact: true }),
  ).toHaveCount(0)
  await page.reload()
  await expect(page.getByText("Confirmed", { exact: true })).toBeVisible()
})

test("expired checkout records late funding and stale verification without payment controls", async ({
  page,
}) => {
  await page.route("**/api/v1/public/payment-requests/*", (route) =>
    route.fulfill({
      json: {
        ...checkout,
        status: "expired",
        payment_status: "pending",
        amount_due_bch: "1",
        payment_uri: null,
        qr_payload: null,
        received_amount_sats: 0,
        late_amount_sats: 40000000,
        verification_stale: true,
      },
    }),
  )
  await page.goto("/p/late-token")
  await expect(page.getByText("Expired", { exact: true })).toBeVisible()
  await expect(page.getByText(/Late payment recorded: 0.4 BCH/)).toBeVisible()
  await expect(page.getByText(/Verification is not current/)).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Open wallet", exact: true }),
  ).toHaveCount(0)
})

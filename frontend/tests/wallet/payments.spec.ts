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

test("merchant reviews outputs, handles allocation conflicts and assigns selected vouts", async ({
  page,
}) => {
  const txid = "a".repeat(64)
  let conflict = true
  let allocated = false
  const invoice = {
    ...checkout,
    id: "test-request",
    public_token: "test-token",
    created_at: "2026-10-01T00:00:00Z",
    checkout_url: "/p/test-token",
    receipt_token: null,
    payments: [],
  }
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "allocation-test"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        id: "test-user",
        email: "merchant@example.com",
        full_name: "Merchant",
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/payment-requests/test-request", (route) =>
    route.fulfill({ json: invoice }),
  )
  await page.route(
    "**/api/v1/payment-requests/test-request/monitoring",
    (route) =>
      route.fulfill({
        json: {
          outputs: allocated
            ? []
            : [{ txid, vout: 1, amount_sats: 100000000, confirmations: 2 }],
          scan_status: "current",
          last_successful_scan_at: "2026-10-31T12:00:00Z",
          last_scan_attempt_at: "2026-10-31T12:00:00Z",
        },
      }),
  )
  await page.route(
    `**/api/v1/payment-requests/test-request/transactions/${txid}`,
    (route) =>
      route.fulfill({
        json: [
          {
            txid,
            vout: 0,
            amount_sats: 20000000,
            confirmations: 2,
            allocated: true,
          },
          {
            txid,
            vout: 1,
            amount_sats: 100000000,
            confirmations: 2,
            allocated: false,
          },
        ],
      }),
  )
  await page.route(
    `**/api/v1/payment-requests/test-request/claims/${txid}`,
    (route) => {
      expect(route.request().postDataJSON()).toEqual({ vouts: [1] })
      if (conflict)
        return route.fulfill({
          status: 409,
          json: { detail: "Transaction output already allocated" },
        })
      allocated = true
      return route.fulfill({ json: invoice })
    },
  )
  await page.goto("/dashboard/payment-links/test-request")
  await expect(
    page.getByText("Review and allocate payments", { exact: true }),
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Review transaction", exact: true })
    .click()
  const checkboxes = page.getByRole("checkbox")
  await expect(checkboxes.nth(0)).toBeDisabled()
  await checkboxes.nth(1).check()
  await page
    .getByRole("button", { name: "Assign selected outputs to this request" })
    .click()
  await expect(page.getByRole("alert")).toContainText("already allocated")
  conflict = false
  await page
    .getByRole("button", { name: "Assign selected outputs to this request" })
    .click()
  await expect(
    page.getByText("Verified outputs assigned to this request"),
  ).toBeVisible()
  await expect(page.getByRole("checkbox")).toHaveCount(0)
})

test("receipt polls credited snapshot evidence and freshness independently of confirmed status", async ({
  page,
}) => {
  const txid = "a".repeat(64)
  let fresh = false
  let requests = 0
  await page.route("**/api/v1/public/receipts/test-receipt", (route) => {
    requests++
    return route.fulfill({
      json: {
        reference: "PP-TEST",
        invoice_reference: "INV-42",
        merchant_name: "Test merchant",
        network: "chipnet",
        requested_amount_sats: 100000,
        amount_sats: 100000,
        receiving_address: "bchtest:q-example",
        required_confirmations: 1,
        output_refs: [`${txid}:0`],
        missing_output_refs: [],
        issued_at: "2026-10-31T09:00:00Z",
        verified_at: fresh ? "2026-10-31T10:10:00Z" : "2026-10-31T09:00:00Z",
        verification_stale: !fresh,
        current_status: "confirmed",
        invoice_payment_status: "confirmed",
        statement: "Observed BCH payment against this request.",
        payments: [
          {
            txid,
            vout: 0,
            network: "chipnet",
            amount_sats: 100000,
            confirmations: fresh ? 11 : 10,
            status: "confirmed",
            is_late: false,
          },
        ],
      },
    })
  })
  await page.goto("/r/test-receipt")
  await expect(
    page.getByRole("heading", { name: "Credited receipt outputs" }),
  ).toBeVisible()
  await expect(page.getByRole("link", { name: txid, exact: true })).toHaveCount(
    1,
  )
  await expect(
    page.getByText("Verification is stale.", { exact: false }),
  ).toBeVisible()
  await expect(
    page.getByText("Receipt evidence status", { exact: true }),
  ).toBeVisible()
  fresh = true
  await expect(
    page.getByText("11 confirmations", { exact: false }),
  ).toBeVisible({ timeout: 15000 })
  await expect(
    page.getByText("Verification is stale.", { exact: false }),
  ).toHaveCount(0)
  expect(requests).toBeGreaterThan(1)
})

test("merchant request details replace cached pending data after background confirmation", async ({
  page,
}) => {
  let confirmed = false
  let requests = 0
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "polling-test"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        id: "test-user",
        email: "merchant@example.com",
        full_name: "Merchant",
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/payment-requests/poll-request", (route) => {
    requests++
    return route.fulfill({
      json: {
        ...checkout,
        id: "poll-request",
        public_token: "test-token",
        created_at: "2026-10-01T00:00:00Z",
        checkout_url: "/p/test-token",
        receipt_token: null,
        payments: [],
        status: confirmed ? "confirmed" : "pending",
        payment_status: confirmed ? "confirmed" : "pending",
      },
    })
  })
  await page.route(
    "**/api/v1/payment-requests/poll-request/monitoring",
    (route) =>
      route.fulfill({
        json: {
          outputs: [],
          scan_status: "never",
          last_successful_scan_at: null,
          last_scan_attempt_at: null,
        },
      }),
  )
  await page.goto("/dashboard/payment-links/poll-request")
  await expect(page.getByText("Pending", { exact: true })).toBeVisible()
  confirmed = true
  await expect(page.getByText("Confirmed", { exact: true })).toBeVisible({
    timeout: 15000,
  })
  expect(requests).toBeGreaterThan(1)
})

for (const owner of ["current", "other"] as const) {
  test(`allocated output identifies ${owner} request and failed scan is not an empty success`, async ({
    page,
  }) => {
    const txid = "c".repeat(64)
    let confirmed = false
    await page.addInitScript(() =>
      localStorage.setItem("access_token", "ownership-test"),
    )
    await page.route("**/api/v1/users/me", (route) =>
      route.fulfill({
        json: {
          id: "test-user",
          email: "merchant@example.com",
          full_name: "Merchant",
          is_active: true,
          is_superuser: false,
        },
      }),
    )
    await page.route("**/api/v1/payment-requests/ownership-request", (route) =>
      route.fulfill({
        json: {
          ...checkout,
          id: "ownership-request",
          public_token: "test-token",
          created_at: "2026-10-01T00:00:00Z",
          checkout_url: "/p/test-token",
          receipt_token: null,
          payments: [],
          status: confirmed ? "confirmed" : "pending",
          payment_status: confirmed ? "confirmed" : "pending",
        },
      }),
    )
    await page.route(
      "**/api/v1/payment-requests/ownership-request/monitoring",
      (route) =>
        route.fulfill({
          json: {
            outputs: [],
            scan_status: "failed",
            last_successful_scan_at: null,
            last_scan_attempt_at: "2026-10-31T12:00:00Z",
          },
        }),
    )
    await page.route(
      `**/api/v1/payment-requests/ownership-request/transactions/${txid}`,
      (route) => {
        confirmed = owner === "current"
        return route.fulfill({
          json: [
            {
              txid,
              vout: 0,
              amount_sats: 800000,
              confirmations: 3,
              allocated: true,
              assigned_to_this_invoice: owner === "current",
              allocated_invoice_id:
                owner === "current" ? "ownership-request" : "actual-owner",
              allocated_order_reference:
                owner === "current" ? "CURRENT" : "PP-1287C335",
            },
          ],
        })
      },
    )
    await page.goto("/dashboard/payment-links/ownership-request")
    await expect(
      page.getByText("The latest address scan failed.", { exact: false }),
    ).toBeVisible()
    await expect(
      page.getByText("No unassigned outputs detected", { exact: false }),
    ).toHaveCount(0)
    await expect(
      page.getByText("Server payment monitoring runs independently", {
        exact: false,
      }),
    ).toBeVisible()
    await page.getByRole("textbox", { name: "Transaction ID" }).fill(txid)
    await page
      .getByRole("button", { name: "Verify outputs", exact: true })
      .click()
    await expect(page.getByRole("checkbox")).toBeDisabled()
    if (owner === "current") {
      await expect(
        page.getByText("Allocated to this request", { exact: false }),
      ).toBeVisible()
      await expect(page.getByText("Confirmed", { exact: true })).toBeVisible()
    } else {
      await expect(
        page.getByText("Allocated to another request", { exact: false }),
      ).toBeVisible()
      await expect(
        page.getByRole("link", { name: "PP-1287C335", exact: true }),
      ).toHaveAttribute("href", "/dashboard/payment-links/actual-owner")
      await expect(page.getByText("Pending", { exact: true })).toBeVisible()
    }
  })
}

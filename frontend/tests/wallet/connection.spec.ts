import { expect, type Page, test } from "@playwright/test"
import {
  DEFAULT_RELAY_URLS,
  generateKeyExchangeCredentials,
} from "@wizardconnect/core"

const sessionKey = "proofpay-wizardconnect-session"

async function dashboard(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("access_token", "wallet-ui-test"),
  )
  await page.route("**/api/v1/users/me", (route) =>
    route.fulfill({
      json: {
        id: "00000000-0000-0000-0000-000000000001",
        email: "wallet-test@example.com",
        full_name: "Wallet UI Test",
        is_active: true,
        is_superuser: false,
      },
    }),
  )
  await page.route("**/api/v1/dashboard/summary", (route) =>
    route.fulfill({
      json: {
        confirmed_received_sats: 0,
        outstanding_requested_sats: 0,
        request_counts: {},
        recent_activity: [],
      },
    }),
  )
  // A connected relay acknowledges subscriptions but sends no wallet approval.
  // Neither the application nor the SDK is mocked.
  const active = new Set()
  await page.routeWebSocket(/wss:\/\//, (socket) => {
    active.add(socket)
    socket.onMessage((raw) => {
      const message = JSON.parse(String(raw))
      if (message[0] === "REQ")
        socket.send(JSON.stringify(["EOSE", message[1]]))
      if (message[0] === "EVENT")
        socket.send(JSON.stringify(["OK", message[1].id, true, ""]))
    })
    socket.onClose(() => {
      active.delete(socket)
    })
  })
  return { active: () => active.size }
}

test("relay connection stays pending; QR, copy, mobile layout and cancel work", async ({
  page,
  context,
}) => {
  const sockets = await dashboard(page)
  await context.grantPermissions(["clipboard-read", "clipboard-write"])
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto("/dashboard")
  await page
    .getByRole("button", { name: "Connect Wallet", exact: true })
    .click()
  await expect(
    page.getByRole("heading", { name: "Waiting for wallet approval" }),
  ).toBeVisible()
  await expect(
    page
      .getByRole("img", { name: "WizardConnect pairing QR code" })
      .locator("canvas"),
  ).toBeVisible()
  const uri = await page
    .getByLabel("Connection URI", { exact: true })
    .inputValue()
  expect(uri.startsWith("wiz://")).toBe(true)
  await expect(page.getByText("Wallet network unverified")).toBeVisible()
  await page
    .getByRole("button", { name: "Copy connection URI", exact: true })
    .click()
  expect(
    await page.evaluate(
      (expected) =>
        navigator.clipboard.readText().then((value) => value === expected),
      uri,
    ),
  ).toBe(true)
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true)
  await expect(
    page.getByRole("heading", { name: "Wallet connected", exact: true }),
  ).toHaveCount(0)
  await page.keyboard.press("Escape")
  await expect(page.getByRole("dialog")).toHaveCount(0)
  await expect
    .poll(() =>
      page.evaluate((key) => localStorage.getItem(key) === null, sessionKey),
    )
    .toBe(true)
  await expect.poll(sockets.active).toBe(0)
  // Cancelling a wallet connection must preserve backend login.
  expect(
    await page.evaluate(
      () => localStorage.getItem("access_token") === "wallet-ui-test",
    ),
  ).toBe(true)
})

test("no approval times out with retry and creates a new pairing", async ({
  page,
}) => {
  await dashboard(page)
  await page.clock.install()
  await page.goto("/dashboard")
  await page
    .getByRole("button", { name: "Connect Wallet", exact: true })
    .click()
  const first = await page
    .getByLabel("Connection URI", { exact: true })
    .inputValue()
  await page.clock.fastForward(91_000)
  await expect(
    page.getByRole("heading", { name: "Connection failed" }),
  ).toBeVisible()
  await expect(page.getByRole("alert")).toContainText("No wallet approval")
  await page.clock.fastForward(1_000)
  await page.getByRole("button", { name: "Retry connection" }).click()
  await page.clock.fastForward(1_000)
  await expect(page.getByLabel("Connection URI", { exact: true })).toBeVisible()
  expect(
    (await page.getByLabel("Connection URI", { exact: true }).inputValue()) !==
      first,
  ).toBe(true)
  await page.getByRole("button", { name: "Cancel connection" }).click()
  await page.clock.fastForward(1_000)
})

test("Strict Mode restores credentials without claiming a wallet handshake", async ({
  page,
}) => {
  const sockets = await dashboard(page)
  // Synthetic transport credentials only, no wallet seed or signing keys.
  const credentials = generateKeyExchangeCredentials()
  const peer = generateKeyExchangeCredentials()
  await page.addInitScript(
    ({ key, stored }) => {
      localStorage.setItem(key, JSON.stringify(stored))
    },
    {
      key: sessionKey,
      stored: {
        ...credentials,
        walletPublicKey: peer.publicKey,
        walletName: "Protocol test peer",
      },
    },
  )
  await page.goto("/dashboard")
  await page
    .getByRole("button", { name: "Wallet connection in progress" })
    .click()
  await expect(
    page.getByRole("heading", { name: "Reconnecting wallet" }),
  ).toBeVisible()
  await expect(page.getByLabel("Connection URI", { exact: true })).toHaveCount(
    0,
  )
  await expect(
    page.getByRole("heading", { name: "Wallet connected", exact: true }),
  ).toHaveCount(0)
  // Exactly one connection per configured relay survives the Strict Mode replay.
  await expect.poll(sockets.active).toBe(DEFAULT_RELAY_URLS.length)
  await page.getByRole("button", { name: "Cancel connection" }).click()
  await expect.poll(sockets.active).toBe(0)
  await expect
    .poll(() =>
      page.evaluate((key) => localStorage.getItem(key) === null, sessionKey),
    )
    .toBe(true)
})

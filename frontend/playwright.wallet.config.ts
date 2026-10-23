import { defineConfig, devices } from "@playwright/test"

// Wallet UI tests isolate backend auth and relay transport. The real SDK runs
// in the browser; these tests do not claim Cashonize interoperability.
export default defineConfig({
  testDir: "./tests/wallet",
  testMatch: "*.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://localhost:5173",
    // Pairing credentials must not be written into trace/screenshot artifacts.
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  webServer: {
    command: "bun run dev",
    url: "http://localhost:5173",
    reuseExistingServer: true,
  },
})

import { describe, expect, test } from "bun:test"
import { EventEmitter } from "node:events"
import { type RelayClient, RelayStatus } from "@wizardconnect/core"
import { DappConnectionManager, type SessionStorage } from "@wizardconnect/dapp"

// Exercises the installed/patched SDK using a transport test double, not a
// production wallet substitute. No seed, payment or transaction is involved.
function fixture(paired: boolean) {
  const data = new Map<string, string>()
  const storage: SessionStorage = {
    getItem: (key) => data.get(key) ?? null,
    setItem: (key, value) => {
      data.set(key, value)
    },
    removeItem: (key) => {
      data.delete(key)
    },
  }
  const transport = Object.assign(new EventEmitter(), {
    isKeyExchangeComplete: () => paired,
    setPeerCapabilities: () => {},
    relay: async () => {},
  })
  const manager = new DappConnectionManager("ProofPay", undefined, {
    session: { storage },
  })
  manager.updateConnection(
    transport as unknown as RelayClient,
    RelayStatus.disconnected(),
  )
  return { manager, transport }
}
const message = {
  action: "wallet_ready",
  time: 1,
  wallet_name: "Protocol test peer",
  wallet_icon: "",
  supported_protocols: ["hdwalletv1"],
  dapp_discovered: true,
  session: { hdwalletv1: { paths: [] } },
}

describe("WizardConnect SDK integration safeguards", () => {
  test("wallet_ready cannot bypass an unsuccessful key exchange", () => {
    const { manager, transport } = fixture(false)
    let ready = false
    manager.on("walletready", () => {
      ready = true
    })
    transport.emit("message", message)
    expect(ready).toBe(false)
    expect(manager.walletName).toBeNull()
    manager.destroy()
  })
  test("validated handshake emits readiness and destroy detaches listeners", () => {
    const { manager, transport } = fixture(true)
    let ready = 0
    manager.on("walletready", () => {
      ready++
    })
    transport.emit("message", message)
    expect(ready).toBe(1)
    expect(manager.walletName).toBe("Protocol test peer")
    manager.clearStoredSession()
    manager.destroy()
    expect(transport.listenerCount("message")).toBe(0)
    expect(manager.listenerCount("walletready")).toBe(0)
    transport.emit("message", message)
    expect(ready).toBe(1)
  })
})

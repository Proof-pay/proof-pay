import { DisconnectReason } from "@wizardconnect/core"
import type { SessionStorage } from "@wizardconnect/dapp"
import { useWizardConnect } from "@wizardconnect/react"
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

export const WALLET_SESSION_KEY = "proofpay-wizardconnect-session"
const APPROVAL_TIMEOUT_MS = 90_000

type WalletState = "disconnected" | "connecting" | "connected" | "failed"
type WalletContextValue = {
  state: WalletState
  walletName: string | null
  uri: string | null
  qrUri: string | null
  error: string | null
  restoring: boolean
  busy: boolean
  storageUnavailable: boolean
  connect: () => void
  disconnect: () => Promise<void>
  retry: () => Promise<void>
}
const WalletContext = createContext<WalletContextValue | null>(null)

/** One SDK hook owns the session for the authenticated TanStack layout. */
export function WalletProvider({ children }: { children: ReactNode }) {
  const [storageUnavailable, setStorageUnavailable] = useState(false)
  // Use the SDK's documented storage interface; serialization stays in the SDK.
  const storage = useMemo<SessionStorage>(
    () => ({
      getItem(key) {
        try {
          return window.localStorage.getItem(key)
        } catch {
          setStorageUnavailable(true)
          return null
        }
      },
      setItem(key, value) {
        try {
          window.localStorage.setItem(key, value)
        } catch {
          setStorageUnavailable(true)
        }
      },
      removeItem(key) {
        try {
          window.localStorage.removeItem(key)
        } catch {
          setStorageUnavailable(true)
        }
      },
    }),
    [],
  )
  const wc = useWizardConnect({
    dappName: "ProofPay",
    sessionKey: WALLET_SESSION_KEY,
    persistSession: true,
    storage,
  })
  const [failure, setFailure] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const operation = useRef<Promise<void> | null>(null)

  const stop = useCallback(() => {
    if (operation.current) return operation.current
    setBusy(true)
    const pending = wc.disconnect().finally(() => {
      operation.current = null
      setBusy(false)
    })
    operation.current = pending
    return pending
  }, [wc.disconnect])

  const connect = useCallback(() => {
    if (operation.current) return
    setFailure(null)
    try {
      wc.connect()
    } catch {
      setFailure("Could not start the wallet connection. Please retry.")
    }
  }, [wc.connect])

  const disconnect = useCallback(async () => {
    setFailure(null)
    await stop()
  }, [stop])

  const retry = useCallback(async () => {
    if (operation.current) return
    await stop()
    connect()
  }, [connect, stop])

  useEffect(() => {
    const manager = wc.manager
    if (!manager) return
    const onDisconnect = (reason: DisconnectReason) => {
      if (reason === DisconnectReason.ProtocolMismatch) {
        setFailure(
          "This wallet does not support the required WizardConnect protocol. Update Cashonize and retry.",
        )
      }
    }
    manager.on("disconnect", onDisconnect)
    return () => {
      manager.off("disconnect", onDisconnect)
    }
  }, [wc.manager])

  const waiting = wc.state === "connecting" || wc.state === "reconnecting"
  useEffect(() => {
    if (!waiting) return
    // Cashonize rejection is local to the wallet; no handshake follows.
    // Bound waiting without ever mistaking relay connectivity for approval.
    const timer = window.setTimeout(() => {
      setFailure(
        "No wallet approval was received. Open Cashonize, check your connection, and retry.",
      )
      void stop()
    }, APPROVAL_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [waiting, stop])

  // Avoid displaying untrusted SDK error details, which can include session data.
  const error =
    failure ||
    (wc.error ? "Could not start the wallet connection. Please retry." : null)
  const state: WalletState = error
    ? "failed"
    : wc.state === "connected"
      ? "connected"
      : waiting
        ? "connecting"
        : "disconnected"
  return (
    <WalletContext.Provider
      value={{
        state,
        walletName: state === "connected" ? wc.walletName : null,
        uri: state === "connecting" ? wc.uri : null,
        qrUri: state === "connecting" ? wc.qrUri : null,
        restoring: waiting && (!wc.uri || wc.state === "reconnecting"),
        error,
        busy,
        storageUnavailable,
        connect,
        disconnect,
        retry,
      }}
    >
      {children}
    </WalletContext.Provider>
  )
}

/** Exposes connection controls only; wallet connection is not backend login. */
export function useProofPayWallet() {
  const wallet = useContext(WalletContext)
  if (!wallet) throw new Error("useProofPayWallet requires WalletProvider")
  return wallet
}

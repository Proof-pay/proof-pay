import { AlphanumericQRCode } from "@wizardconnect/react"
import { Check, Copy, LoaderCircle, Unplug, Wallet } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { useProofPayWallet } from "./WalletProvider"

export function ConnectWallet() {
  const wallet = useProofPayWallet()
  const [open, setOpen] = useState(false)
  const [copiedUri, setCopiedUri] = useState<string | null>(null)
  const connected = wallet.state === "connected"
  const waiting = wallet.state === "connecting"
  const title = connected
    ? "Wallet connected"
    : wallet.state === "failed"
      ? "Connection failed"
      : waiting
        ? wallet.restoring
          ? "Reconnecting wallet"
          : "Waiting for wallet approval"
        : "Wallet disconnected"

  function changeOpen(next: boolean) {
    setOpen(next)
    setCopiedUri(null)
    if (!next && waiting) void wallet.disconnect()
  }
  function openWallet() {
    setOpen(true)
    if (wallet.state === "disconnected") wallet.connect()
  }
  async function copyUri() {
    if (!wallet.uri) return
    try {
      await navigator.clipboard.writeText(wallet.uri)
      setCopiedUri(wallet.uri)
      toast.success("Connection URI copied")
    } catch {
      toast.error(
        "Could not copy. Select the connection URI below and copy it.",
      )
    }
  }
  return (
    <Dialog open={open} onOpenChange={changeOpen}>
      <Button
        type="button"
        variant="outline"
        onClick={openWallet}
        disabled={wallet.busy}
        aria-label={
          connected
            ? `Connected wallet: ${wallet.walletName || "Wallet"}`
            : waiting
              ? "Wallet connection in progress"
              : wallet.state === "failed"
                ? "Wallet connection failed"
                : "Connect Wallet"
        }
        className="h-9 max-w-40 gap-2 rounded-lg border-[#dbe5e7] px-2.5 text-xs text-[#17303a] sm:px-3.5"
      >
        {waiting ? (
          <LoaderCircle className="size-4 animate-spin" />
        ) : (
          <Wallet className="size-4" />
        )}
        <span className="hidden truncate sm:inline">
          {connected
            ? wallet.walletName || "Connected wallet"
            : waiting
              ? "Connecting…"
              : wallet.state === "failed"
                ? "Retry wallet"
                : "Connect Wallet"}
        </span>
        {connected && (
          <span className="size-1.5 shrink-0 rounded-full bg-emerald-600" />
        )}
      </Button>
      <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl p-5 sm:p-6">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {connected
              ? `Connected to ${wallet.walletName || "your wallet"} through WizardConnect.`
              : wallet.restoring
                ? "Open Cashonize to restore your saved connection."
                : "In Cashonize, select your HD wallet, then scan this QR code or paste the connection URI in its dapp connection screen."}
          </DialogDescription>
        </DialogHeader>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">
          <strong>Chipnet testing · network unverified</strong>
          <p className="mt-1">
            Select Chipnet in Cashonize before connecting. WizardConnect does
            not report a verified wallet network.
          </p>
        </div>
        {wallet.error && (
          <p
            role="alert"
            className="rounded-lg bg-red-50 p-3 text-sm text-red-800"
          >
            {wallet.error}
          </p>
        )}
        {waiting && (
          <div className="space-y-4">
            <p
              role="status"
              className="flex items-center justify-center gap-2 text-sm text-slate-600"
            >
              <LoaderCircle className="size-4 animate-spin" />
              {wallet.restoring
                ? "Waiting for the wallet to reconnect…"
                : "Connecting / waiting for wallet approval…"}
            </p>
            {!wallet.restoring && wallet.qrUri && wallet.uri && (
              <>
                <div
                  role="img"
                  aria-label="WizardConnect pairing QR code"
                  className="mx-auto w-fit max-w-full rounded-xl border bg-white p-3 [&_canvas]:max-w-full [&_canvas]:!h-auto"
                >
                  <AlphanumericQRCode
                    value={wallet.qrUri}
                    size={240}
                    quietZone={12}
                    foreground="#0E1E28"
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  onClick={copyUri}
                >
                  {copiedUri === wallet.uri ? <Check /> : <Copy />}
                  {copiedUri === wallet.uri
                    ? "Connection URI copied"
                    : "Copy connection URI"}
                </Button>
                <label
                  className="block text-xs text-slate-500"
                  htmlFor="wallet-connection-uri"
                >
                  Connection URI
                </label>
                <textarea
                  id="wallet-connection-uri"
                  readOnly
                  spellCheck={false}
                  value={wallet.uri}
                  onFocus={(event) => event.currentTarget.select()}
                  className="w-full resize-none rounded-lg border bg-slate-50 p-2 font-mono text-xs"
                  rows={3}
                />
              </>
            )}
            <p className="text-xs leading-5 text-slate-500">
              Approve the connection in Cashonize. If you decline there, cancel
              here or wait for the request to time out.
            </p>
          </div>
        )}
        {connected && (
          <div
            role="status"
            className="flex items-center gap-3 rounded-xl bg-emerald-50 p-4 text-emerald-900"
          >
            <Check className="size-5" />
            <div>
              <p className="font-semibold">Connected</p>
              <p className="text-sm">{wallet.walletName || "Wallet"}</p>
            </div>
          </div>
        )}
        {wallet.storageUnavailable && (
          <p role="status" className="text-sm text-amber-800">
            Browser storage is unavailable. This connection may not survive a
            refresh.
          </p>
        )}
        <DialogFooter>
          {connected ? (
            <Button
              variant="outline"
              disabled={wallet.busy}
              onClick={() => void wallet.disconnect()}
            >
              <Unplug />
              Disconnect
            </Button>
          ) : wallet.state === "failed" ? (
            <Button disabled={wallet.busy} onClick={() => void wallet.retry()}>
              Retry connection
            </Button>
          ) : waiting ? (
            <Button
              variant="outline"
              disabled={wallet.busy}
              onClick={() => changeOpen(false)}
            >
              Cancel connection
            </Button>
          ) : (
            <Button disabled={wallet.busy} onClick={wallet.connect}>
              Connect Wallet
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

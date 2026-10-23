import {
  createFileRoute,
  Link,
  Outlet,
  redirect,
  useRouterState,
} from "@tanstack/react-router"
import { ChevronRight, Plus } from "lucide-react"

import { UsersService } from "@/client"
import { Footer } from "@/components/Common/Footer"
import AppSidebar from "@/components/Sidebar/AppSidebar"
import {
  SidebarInset,
  SidebarProvider,
  SidebarTrigger,
} from "@/components/ui/sidebar"
import { ConnectWallet } from "@/features/wallet/ConnectWallet"
import { WalletProvider } from "@/features/wallet/WalletProvider"
import { isLoggedIn } from "@/hooks/useAuth"
import { isSessionError } from "@/utils/session"

export const Route = createFileRoute("/_layout")({
  component: Layout,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({
        to: "/login",
      })
    }

    try {
      await UsersService.readUserMe()
    } catch (error) {
      if (!isSessionError(error, true)) throw error

      localStorage.removeItem("access_token")
      throw redirect({ to: "/login" })
    }
  },
})

function Layout() {
  const pathname = useRouterState({
    select: (state) => state.location.pathname,
  })
  const isPaymentLinks = pathname.startsWith("/dashboard/payment-links")
  const isTransactions = pathname.startsWith("/dashboard/transactions")
  const section = pathname.startsWith("/dashboard/payment-links")
    ? "Payment links"
    : pathname.startsWith("/dashboard/transactions")
      ? "Transactions"
      : pathname.startsWith("/dashboard/receipts")
        ? "Receipts"
        : pathname.startsWith("/settings")
          ? "Settings"
          : pathname.startsWith("/items")
            ? "Items"
            : pathname.startsWith("/admin")
              ? "Admin"
              : "Overview"
  const detail = isPaymentLinks
    ? pathname.endsWith("/new")
      ? "Create link"
      : pathname.endsWith("/qr")
        ? "Payment QR"
        : pathname !== "/dashboard/payment-links"
          ? "Link details"
          : null
    : isTransactions && pathname !== "/dashboard/transactions"
      ? "Transaction details"
      : null
  const pageTitle = detail || section
  return (
    <WalletProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset className="min-w-0">
          <header className="sticky top-0 z-10 flex h-[72px] shrink-0 items-center justify-between gap-3 border-b border-[#e1e9eb] bg-white/95 px-4 backdrop-blur md:px-8">
            <div className="flex min-w-0 items-center gap-3 text-sm">
              <SidebarTrigger
                className="-ml-1 size-9 rounded-lg border border-[#e1e9eb] text-[#445d67] hover:bg-[#f2f7f6] hover:text-emerald-700"
                aria-label="Toggle navigation"
              />
              <span
                className="hidden h-6 w-px bg-[#e1e9eb] sm:block"
                aria-hidden="true"
              />
              <nav
                aria-label="Breadcrumb"
                className="flex min-w-0 items-center gap-2 sm:gap-3"
              >
                <Link
                  to="/dashboard"
                  activeOptions={{ exact: true }}
                  className="hidden text-[#7c919a] transition-colors hover:text-emerald-700 sm:inline"
                >
                  Workspace
                </Link>
                <ChevronRight
                  className="hidden size-4 shrink-0 text-[#bdcbd0] sm:block"
                  aria-hidden="true"
                />
                {detail && isPaymentLinks ? (
                  <>
                    <Link
                      to="/dashboard/payment-links"
                      activeOptions={{ exact: true }}
                      className="hidden text-[#7c919a] hover:text-emerald-700 sm:inline"
                    >
                      Payment links
                    </Link>
                    <ChevronRight
                      className="hidden size-4 shrink-0 text-[#bdcbd0] sm:block"
                      aria-hidden="true"
                    />
                  </>
                ) : detail && isTransactions ? (
                  <>
                    <Link
                      to="/dashboard/transactions"
                      activeOptions={{ exact: true }}
                      className="hidden text-[#7c919a] hover:text-emerald-700 sm:inline"
                    >
                      Transactions
                    </Link>
                    <ChevronRight
                      className="hidden size-4 shrink-0 text-[#bdcbd0] sm:block"
                      aria-hidden="true"
                    />
                  </>
                ) : null}
                <span
                  className="truncate font-semibold text-[#17303a]"
                  aria-current={
                    section === "Overview" && pathname === "/dashboard"
                      ? undefined
                      : "page"
                  }
                >
                  {pageTitle}
                </span>
              </nav>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <ConnectWallet />
              <span className="hidden items-center gap-2 rounded-full border border-[#e3ebe9] bg-[#f5f9f7] px-3 py-1.5 text-xs font-semibold text-[#536d70] lg:inline-flex">
                <span className="size-1.5 rounded-full bg-[#e6a13c]" /> Demo
                workspace
              </span>
              <Link
                to="/dashboard/payment-links/new"
                className="inline-flex h-9 items-center gap-2 rounded-lg bg-[#087a55] px-3.5 text-xs font-semibold text-white shadow-[0_3px_8px_rgba(8,122,85,.15)] transition-colors hover:bg-[#065f46] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600"
              >
                <Plus className="size-4" />{" "}
                <span className="hidden sm:inline">New payment</span>
                <span className="sm:hidden">New</span>
              </Link>
            </div>
          </header>
          <main className="flex-1 px-4 py-7 md:px-8 md:py-9">
            <div className="mx-auto max-w-[1360px]">
              <Outlet />
            </div>
          </main>
          <Footer />
        </SidebarInset>
      </SidebarProvider>
    </WalletProvider>
  )
}

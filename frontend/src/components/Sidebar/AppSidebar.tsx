import {
  Briefcase,
  LayoutDashboard,
  Link2,
  List,
  Receipt,
  Settings,
  Users,
} from "lucide-react"

import { SidebarAppearance } from "@/components/Common/Appearance"
import { Logo } from "@/components/Common/Logo"
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/sidebar"
import useAuth from "@/hooks/useAuth"
import { type Item, Main } from "./Main"
import { User } from "./User"

const baseItems: Item[] = [
  { icon: LayoutDashboard, title: "Overview", path: "/dashboard" },
  { icon: Link2, title: "Payment Links", path: "/dashboard/payment-links" },
  { icon: List, title: "Transactions", path: "/dashboard/transactions" },
  { icon: Receipt, title: "Receipts", path: "/dashboard/receipts" },
  { icon: Briefcase, title: "Items", path: "/items" },
  { icon: Settings, title: "Settings", path: "/settings" },
]

export function AppSidebar() {
  const { user: currentUser } = useAuth()

  const items = currentUser?.is_superuser
    ? [...baseItems, { icon: Users, title: "Admin", path: "/admin" }]
    : baseItems

  return (
    <Sidebar
      collapsible="icon"
      className="proofpay-sidebar border-sidebar-border"
    >
      <SidebarHeader className="min-h-[84px] justify-center border-b border-sidebar-border px-5 py-4 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-1">
        <Logo variant="responsive" />
      </SidebarHeader>
      <SidebarContent className="pt-7">
        <div className="px-6 pb-3 text-[10px] font-bold uppercase tracking-[.18em] text-[#839aa4] group-data-[collapsible=icon]:hidden">
          Workspace
        </div>
        <Main items={items} />
      </SidebarContent>
      <SidebarFooter className="gap-1 border-t border-sidebar-border px-3 pb-4 pt-4 group-data-[collapsible=icon]:px-1">
        <div className="mb-3 rounded-xl border border-[#2b4951] bg-[#182f38] p-3.5 group-data-[collapsible=icon]:hidden">
          <p className="text-[13px] font-semibold text-white">
            Bitcoin Cash payments
          </p>
          <p className="mt-1 text-xs leading-5 text-[#9eb2ba]">
            Create and share payment requests with confidence.
          </p>
        </div>
        <SidebarAppearance />
        <User user={currentUser} />
      </SidebarFooter>
    </Sidebar>
  )
}

export default AppSidebar

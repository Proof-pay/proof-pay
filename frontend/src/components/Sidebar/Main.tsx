import { Link as RouterLink, useRouterState } from "@tanstack/react-router"
import type { LucideIcon } from "lucide-react"

import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar"

export type Item = {
  icon: LucideIcon
  title: string
  path: string
}

interface MainProps {
  items: Item[]
}

export function Main({ items }: MainProps) {
  const { isMobile, setOpenMobile } = useSidebar()
  const router = useRouterState()
  const currentPath = router.location.pathname

  const handleMenuClick = () => {
    if (isMobile) {
      setOpenMobile(false)
    }
  }

  return (
    <SidebarGroup className="px-3 group-data-[collapsible=icon]:px-1">
      <SidebarGroupContent>
        <SidebarMenu>
          {items.map((item) => {
            const isActive =
              currentPath === item.path ||
              (item.path === "/dashboard" && currentPath === "/") ||
              (item.path !== "/dashboard" &&
                currentPath.startsWith(`${item.path}/`))

            return (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton
                  className="h-11 rounded-[10px] px-3 text-[13px] font-medium text-[#c3d1d6] hover:bg-sidebar-accent hover:text-white focus-visible:ring-sidebar-ring data-[active=true]:bg-sidebar-accent data-[active=true]:text-white"
                  tooltip={item.title}
                  isActive={isActive}
                  asChild
                >
                  <RouterLink to={item.path} onClick={handleMenuClick}>
                    <item.icon
                      className={isActive ? "text-[#48dba5]" : "text-[#91a6af]"}
                    />
                    <span>{item.title}</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            )
          })}
        </SidebarMenu>
      </SidebarGroupContent>
    </SidebarGroup>
  )
}

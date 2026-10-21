import { createFileRoute } from "@tanstack/react-router"

import ChangePassword from "@/components/UserSettings/ChangePassword"
import DeleteAccount from "@/components/UserSettings/DeleteAccount"
import UserInformation from "@/components/UserSettings/UserInformation"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import useAuth from "@/hooks/useAuth"

const tabsConfig = [
  { value: "my-profile", title: "My profile", component: UserInformation },
  { value: "password", title: "Password", component: ChangePassword },
  { value: "danger-zone", title: "Danger zone", component: DeleteAccount },
]

export const Route = createFileRoute("/_layout/settings")({
  component: UserSettings,
  head: () => ({
    meta: [
      {
        title: "Settings - ProofPay",
      },
    ],
  }),
})

function UserSettings() {
  const { user: currentUser } = useAuth()
  const finalTabs = currentUser?.is_superuser
    ? tabsConfig.slice(0, 3)
    : tabsConfig

  if (!currentUser) {
    return null
  }

  return (
    <div className="flex max-w-4xl flex-col gap-6">
      <div>
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[.16em] text-emerald-700">
          Account
        </p>
        <h1 className="text-[32px] font-bold tracking-[-.045em]">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage your account and security preferences.
        </p>
      </div>

      <Tabs defaultValue="my-profile" className="gap-5">
        <TabsList className="h-auto max-w-full justify-start overflow-x-auto rounded-xl border bg-white p-1.5">
          {finalTabs.map((tab) => (
            <TabsTrigger
              key={tab.value}
              value={tab.value}
              className="px-4 py-2 data-[state=active]:bg-emerald-50 data-[state=active]:text-emerald-800"
            >
              {tab.title}
            </TabsTrigger>
          ))}
        </TabsList>
        {finalTabs.map((tab) => (
          <TabsContent
            key={tab.value}
            value={tab.value}
            className="dashboard-card min-h-72 p-5 sm:p-7"
          >
            <tab.component />
          </TabsContent>
        ))}
      </Tabs>
    </div>
  )
}

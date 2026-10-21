import { createFileRoute, redirect } from "@tanstack/react-router"

import { AuthLayout } from "@/components/Common/AuthLayout"
import { isLoggedIn } from "@/hooks/useAuth"

export const Route = createFileRoute("/oauth/callback")({
  beforeLoad: () => {
    const hashParams = new URLSearchParams(
      window.location.hash.replace(/^#/, ""),
    )
    const accessToken = hashParams.get("access_token")

    if (accessToken) {
      localStorage.setItem("access_token", accessToken)
      window.history.replaceState(null, "", window.location.pathname)
      throw redirect({ to: "/", replace: true })
    }

    if (isLoggedIn()) {
      throw redirect({ to: "/", replace: true })
    }

    throw redirect({ to: "/login", replace: true })
  },
  component: OAuthCallback,
  head: () => ({
    meta: [
      {
        title: "Signing In - ProofPay",
      },
    ],
  }),
})

function OAuthCallback() {
  return (
    <AuthLayout>
      <div className="flex flex-col items-center justify-center gap-3 py-8 text-center">
        <p className="text-sm text-muted-foreground">
          Completing Google sign-in...
        </p>
      </div>
    </AuthLayout>
  )
}

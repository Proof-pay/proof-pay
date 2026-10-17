import { createFileRoute } from "@tanstack/react-router"
import { NewLinkPage } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/payment-links/new")({
  component: NewLinkPage,
})

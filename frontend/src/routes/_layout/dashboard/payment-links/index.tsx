import { createFileRoute } from "@tanstack/react-router"
import { LinksPage } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/payment-links/")({
  component: LinksPage,
})

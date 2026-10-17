import { createFileRoute } from "@tanstack/react-router"
import { ReceiptsPage } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/receipts/")({
  component: ReceiptsPage,
})

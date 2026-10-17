import { createFileRoute } from "@tanstack/react-router"
import { TransactionsPage } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/transactions/")({
  component: TransactionsPage,
})

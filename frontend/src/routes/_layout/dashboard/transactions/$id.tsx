import { createFileRoute } from "@tanstack/react-router"
import { TransactionDetails } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/transactions/$id")({
  component: () => {
    const { id } = Route.useParams()
    return <TransactionDetails id={id} />
  },
})

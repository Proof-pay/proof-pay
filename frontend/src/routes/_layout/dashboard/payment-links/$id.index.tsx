import { createFileRoute } from "@tanstack/react-router"
import { LinkDetails } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/payment-links/$id/")({
  component: () => {
    const { id } = Route.useParams()
    return <LinkDetails id={id} />
  },
})

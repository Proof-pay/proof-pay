import { createFileRoute } from "@tanstack/react-router"
import { PaymentStatusPage } from "@/features/payments/pages"
export const Route = createFileRoute("/p/$publicId/status")({
  component: () => {
    const { publicId } = Route.useParams()
    return <PaymentStatusPage publicId={publicId} />
  },
})

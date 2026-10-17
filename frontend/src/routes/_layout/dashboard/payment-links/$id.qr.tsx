import { createFileRoute } from "@tanstack/react-router"
import { MerchantQR } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/payment-links/$id/qr")(
  {
    component: () => {
      const { id } = Route.useParams()
      return <MerchantQR id={id} />
    },
  },
)

import { createFileRoute } from "@tanstack/react-router"
import { Checkout } from "@/features/payments/pages"
export const Route = createFileRoute("/p/$publicId/")({
  component: () => {
    const { publicId } = Route.useParams()
    return <Checkout publicId={publicId} />
  },
})

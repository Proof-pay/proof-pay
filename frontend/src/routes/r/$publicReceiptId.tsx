import { createFileRoute } from "@tanstack/react-router"
import { PublicReceipt } from "@/features/payments/pages"
export const Route = createFileRoute("/r/$publicReceiptId")({
  component: () => {
    const { publicReceiptId } = Route.useParams()
    return <PublicReceipt publicReceiptId={publicReceiptId} />
  },
})

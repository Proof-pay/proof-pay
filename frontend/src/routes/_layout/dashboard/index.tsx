import { createFileRoute } from "@tanstack/react-router"
import { Overview } from "@/features/payments/pages"
export const Route = createFileRoute("/_layout/dashboard/")({
  component: Overview,
})

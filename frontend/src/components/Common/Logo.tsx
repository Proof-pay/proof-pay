import { Link } from "@tanstack/react-router"
import { cn } from "@/lib/utils"

const logoSrc = "/assets/images/proofpay-logo.png"

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}) {
  const content = (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <span
        className="relative block size-10 shrink-0 overflow-hidden rounded-[10px]"
        aria-hidden="true"
      >
        <img
          src={logoSrc}
          alt=""
          className="absolute left-[-22px] top-[-86px] h-auto w-[210px] max-w-none"
        />
      </span>
      {variant !== "icon" && (
        <span
          className={cn(
            "whitespace-nowrap text-xl font-bold tracking-[-.05em] text-inherit",
            variant === "responsive" && "group-data-[collapsible=icon]:hidden",
          )}
        >
          Proof<span className="text-[#23c88b]">Pay</span>
        </span>
      )}
    </span>
  )
  return asLink ? (
    <Link to="/dashboard" aria-label="ProofPay dashboard">
      {content}
    </Link>
  ) : (
    content
  )
}

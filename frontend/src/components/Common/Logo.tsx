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
  const fullLogo = (
    <span
      className={cn(
        "relative block h-10 aspect-[9/2] overflow-hidden rounded-sm bg-[#D1FAE5]",
        variant === "responsive" && "group-data-[collapsible=icon]:hidden",
        className,
      )}
    >
      <img
        src={logoSrc}
        alt="ProofPay"
        className="absolute left-0 top-1/2 w-full -translate-y-1/2"
      />
    </span>
  )

  const iconLogo = (
    <span
      className={cn(
        "relative block size-9 shrink-0 overflow-hidden rounded-sm bg-[#D1FAE5]",
        variant === "responsive" &&
          "hidden group-data-[collapsible=icon]:block",
        variant === "icon" && className,
      )}
    >
      <img
        src={logoSrc}
        alt="ProofPay"
        className="absolute -left-[22px] -top-[82px] max-w-none size-[200px]"
      />
    </span>
  )

  const content = (
    <span className="inline-flex items-center">
      {variant !== "icon" && fullLogo}
      {variant !== "full" && iconLogo}
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

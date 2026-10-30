import type { ReactNode } from "react";

export type BadgeVariant =
  | "neutral"
  | "accent"
  | "success"
  | "warning"
  | "error";

interface BadgeProps {
  variant?: BadgeVariant;
  children: ReactNode;
  className?: string;
}

const VARIANTS: Record<BadgeVariant, string> = {
  neutral: "bg-surface-2 text-muted",
  accent: "bg-accent-soft text-accent-strong",
  success: "bg-success-soft text-success-strong",
  warning: "bg-warning-soft text-warning-strong",
  error: "bg-error-soft text-error-strong",
};

/** Insignia/Pill de estado. Los colores de estado no se usan como acento. */
export default function Badge({
  variant = "neutral",
  children,
  className = "",
}: BadgeProps) {
  return (
    <span
      className={`badge rounded-full ${VARIANTS[variant]} ${className}`}
    >
      {children}
    </span>
  );
}

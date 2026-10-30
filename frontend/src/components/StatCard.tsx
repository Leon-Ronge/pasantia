import type { ReactNode } from "react";

type Accent =
  | "neutral"
  | "accent"
  | "success"
  | "warning"
  | "error"
  // Alias usados por las páginas existentes (mapean a los tokens).
  | "brand"
  | "emerald"
  | "rose"
  | "amber"
  | "slate";

interface StatCardProps {
  title: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: Accent;
  children?: ReactNode;
}

const ACCENTS: Record<Accent, string> = {
  neutral: "text-fg",
  accent: "text-accent-strong",
  success: "text-success-strong",
  warning: "text-warning-strong",
  error: "text-error-strong",
  brand: "text-accent-strong",
  emerald: "text-success-strong",
  rose: "text-error-strong",
  amber: "text-warning-strong",
  slate: "text-fg",
};

/** Tarjeta de resumen del Dashboard y módulos (valores con tabular-nums). */
export default function StatCard({
  title,
  value,
  sub,
  accent = "neutral",
  children,
}: StatCardProps) {
  return (
    <div className="card flex flex-col gap-1">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">
        {title}
      </p>
      <p
        className={`text-2xl font-semibold leading-tight tabular-nums ${ACCENTS[accent]}`}
      >
        {value}
      </p>
      {sub ? <p className="text-xs text-muted">{sub}</p> : null}
      {children}
    </div>
  );
}

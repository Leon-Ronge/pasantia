import type { ReactNode } from "react";

interface ProgressRingProps {
  value: number;
  max: number;
  /** Diámetro en px (default 96). */
  size?: number;
  /** Grosor del anillo en px (default 8). */
  thickness?: number;
  /** Texto del centro (default: porcentaje). */
  center?: ReactNode;
  /** Etiqueta accesible. */
  label?: string;
}

/** Anillo de progreso con texto en el centro (horas del día, semana…). */
export default function ProgressRing({
  value,
  max,
  size = 96,
  thickness = 8,
  center,
  label,
}: ProgressRingProps) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const pct = Math.round(ratio * 100);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label ?? "Progreso"}
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={thickness}
          className="stroke-surface-2"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - ratio)}
          className={`transition-all duration-500 ${
            ratio >= 1 ? "stroke-success" : "stroke-accent"
          }`}
        />
      </svg>
      <div className="absolute text-center">
        {center ?? (
          <span className="text-sm font-semibold tabular-nums">{pct}%</span>
        )}
      </div>
    </div>
  );
}

interface ProgressBarProps {
  value: number;
  max: number;
  label?: string;
}

/** Barra de progreso semanal (objetivo vs. trabajado). */
export default function ProgressBar({ value, max, label }: ProgressBarProps) {
  const ratio = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  const pct = Math.round(ratio * 100);
  const done = ratio >= 1;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-muted">
        <span>{label ?? "Progreso"}</span>
        <span className="font-medium tabular-nums">{pct}%</span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={max}
        aria-label={label ?? "Progreso"}
        className="h-2.5 w-full overflow-hidden rounded-full bg-surface-2"
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            done ? "bg-success" : "bg-accent"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

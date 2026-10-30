interface SkeletonProps {
  className?: string;
}

/** Bloque de carga con shimmer (mismo tono que las superficies). */
export default function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      aria-hidden
      className={`h-4 w-32 animate-pulse rounded-lg bg-surface-2 ${className}`}
    />
  );
}

/** Tarjeta completa en esqueleto (para listas y paneles). */
export function SkeletonCard({ className = "" }: SkeletonProps) {
  return (
    <div
      aria-hidden
      className={`card space-y-3 ${className}`}
    >
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-6 w-32" />
      <Skeleton className="h-3 w-40" />
    </div>
  );
}

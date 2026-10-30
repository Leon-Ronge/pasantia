import { useEffect, type ReactNode } from "react";
import { IconPlus } from "./icons";

interface BottomSheetProps {
  open: boolean;
  title?: string;
  onClose: () => void;
  /** Default true: tocar el fondo cierra la hoja. */
  dismissOnBackdrop?: boolean;
  children: ReactNode;
}

/** Hoja inferior táctil (móvil) con safe-area; se cierra con Escape o tap afuera. */
export default function BottomSheet({
  open,
  title,
  onClose,
  dismissOnBackdrop = true,
  children,
}: BottomSheetProps) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-40 flex items-end bg-[var(--overlay)]"
      onClick={dismissOnBackdrop ? onClose : undefined}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="max-h-[90vh] w-full overflow-y-auto rounded-t-2xl border-t border-line bg-surface p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom))] shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-line" />
        {title ? (
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-base font-semibold">{title}</h2>
            <button
              onClick={onClose}
              aria-label="Cerrar"
              className="rounded-lg p-2 text-muted hover:bg-surface-2"
            >
              <IconPlus className="h-5 w-5 rotate-45" />
            </button>
          </div>
        ) : null}
        {children}
      </div>
    </div>
  );
}

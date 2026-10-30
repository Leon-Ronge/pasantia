import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
  type ReactNode,
} from "react";

type ToastKind = "success" | "error" | "info";

interface ToastOptions {
  message: string;
  kind?: ToastKind;
  /** Acción opcional; por defecto se ofrece «Deshacer». */
  action?: { label?: string; onClick: () => void };
  /** Milisegundos visibles (default 6000). */
  duration?: number;
}

type ToastFn = (options: ToastOptions) => void;

const ToastContext = createContext<ToastFn>(() => {});

/** Hook para disparar toasts desde cualquier pantalla. */
export function useToast(): ToastFn {
  return useContext(ToastContext);
}

const KIND_STYLES: Record<ToastKind, string> = {
  success: "bg-success-soft text-success-strong",
  error: "bg-error-soft text-error-strong",
  info: "bg-surface-2 text-fg",
};

/** Proveedor global de toasts (montado en App). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<(ToastOptions & { id: number }) | null>(
    null
  );
  const timer = useRef<number | undefined>(undefined);

  const dismiss = useCallback(() => {
    window.clearTimeout(timer.current);
    setToast(null);
  }, []);

  const show = useCallback(
    (options: ToastOptions) => {
      window.clearTimeout(timer.current);
      setToast({ ...options, id: Date.now() });
      timer.current = window.setTimeout(
        dismiss,
        options.duration ?? 6000
      );
    },
    [dismiss]
  );

  return (
    <ToastContext.Provider value={show}>
      {children}
      {toast ? (
        <div
          role="status"
          aria-live="polite"
          className={`fixed inset-x-4 bottom-[calc(4.5rem+env(safe-area-inset-bottom))] z-50 mx-auto flex max-w-md items-center justify-between gap-3 rounded-xl border border-line px-4 py-3 shadow-xl sm:inset-x-auto sm:right-6 ${KIND_STYLES[toast.kind ?? "info"]}`}
        >
          <span className="text-sm">{toast.message}</span>
          <div className="flex shrink-0 items-center gap-1">
            {toast.action ? (
              <button
                onClick={() => {
                  toast.action!.onClick();
                  dismiss();
                }}
                className="rounded-lg px-2 py-1 text-sm font-semibold text-accent-strong hover:bg-surface-2"
              >
                {toast.action.label ?? "Deshacer"}
              </button>
            ) : null}
            <button
              onClick={dismiss}
              aria-label="Cerrar aviso"
              className="rounded-lg p-1.5 text-muted hover:bg-surface-2"
            >
              ✕
            </button>
          </div>
        </div>
      ) : null}
    </ToastContext.Provider>
  );
}

interface NoticeProps {
  kind: "success" | "error" | "info";
  message: string;
  onClose?: () => void;
}

/** Mensaje breve de confirmación o error. */
export default function Notice({ kind, message, onClose }: NoticeProps) {
  const styles = {
    success: "bg-success-soft text-success-strong",
    error: "bg-error-soft text-error-strong",
    info: "bg-accent-soft text-accent-strong",
  }[kind];
  return (
    <div
      className={`flex items-start justify-between gap-3 rounded-xl px-3 py-2 text-sm ${styles}`}
      role="status"
    >
      <span>{message}</span>
      {onClose ? (
        <button
          onClick={onClose}
          aria-label="Cerrar aviso"
          className="shrink-0 opacity-60 hover:opacity-100"
        >
          ✕
        </button>
      ) : null}
    </div>
  );
}

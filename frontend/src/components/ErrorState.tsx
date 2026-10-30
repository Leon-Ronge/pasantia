import Button from "./Button";
import { IconReload } from "./icons";

interface ErrorStateProps {
  message?: string;
  onRetry: () => void;
}

/** Estado de error con reintento. */
export default function ErrorState({
  message = "No se pudo cargar la información.",
  onRetry,
}: ErrorStateProps) {
  return (
    <div
      role="alert"
      className="card flex flex-col items-center gap-3 py-8 text-center"
    >
      <p className="text-sm text-error-strong">{message}</p>
      <Button variant="secondary" onClick={onRetry}>
        <IconReload className="h-4 w-4" />
        Reintentar
      </Button>
    </div>
  );
}

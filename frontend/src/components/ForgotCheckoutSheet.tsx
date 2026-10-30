import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import BottomSheet from "./BottomSheet";
import Button from "./Button";
import Notice from "./Notice";
import { useToast } from "./Toast";
import { notifyWorkDataChanged } from "../lib/refresh";
import {
  fmtDateShort,
  fmtTime,
  fromDatetimeLocal,
  minutesToHM,
  weekdayShort,
} from "../lib/format";
import type { CheckoutConfirmation } from "../types";

/**
 * Prompt global de cierre olvidado: si /api/today/ trae una jornada que
 * pide confirmación, abre una hoja inferior (no se cierra tocando afuera).
 * Se chequea al montar y cada vez que la app vuelve a primer plano.
 */
export default function ForgotCheckoutSheet() {
  const toast = useToast();
  const [confirmation, setConfirmation] = useState<CheckoutConfirmation | null>(
    null
  );
  const [open, setOpen] = useState(false);
  const [time, setTime] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  /** Si la API contesta NEEDS_CONFIRMATION, se pide re-confirmar. */
  const [askConfirm, setAskConfirm] = useState<number | null>(null);
  const dismissedRef = useRef<number | null>(null);

  const check = useCallback(async () => {
    try {
      const today = await api.today();
      const c = today.needs_checkout_confirmation;
      if (c && c.session_id !== dismissedRef.current) {
        setConfirmation(c);
        setTime(fmtTime(c.planned_end));
        setAskConfirm(null);
        setError("");
        setOpen(true);
      } else if (!c) {
        setOpen(false);
        setConfirmation(null);
      }
    } catch {
      /* sin red no se molesta: se reintenta en el próximo primer plano */
    }
  }, []);

  useEffect(() => {
    check();
    const onVisible = () => {
      if (!document.hidden) check();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", onVisible);
    };
  }, [check]);

  const close = () => {
    dismissedRef.current = confirmation?.session_id ?? null;
    setOpen(false);
  };

  const submit = async (withConfirm: boolean) => {
    if (!confirmation || !time) return;
    setBusy(true);
    setError("");
    try {
      const endAt = fromDatetimeLocal(`${confirmation.work_date}T${time}`);
      await api.checkOutById(confirmation.session_id, {
        end_at: endAt,
        ...(withConfirm ? { confirm: true } : {}),
      });
      toast({ kind: "success", message: "Jornada cerrada." });
      setOpen(false);
      setConfirmation(null);
      notifyWorkDataChanged();
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as { code?: string }) : null;
      if (body?.code === "DURATION_EXCEEDS_MAX") {
        // Minutos según la sesión vigente en el servidor (evita números
        // desactualizados si la jornada se corrigió con el prompt abierto).
        let startIso = confirmation.started_at;
        try {
          const current = await api.currentSession();
          if (current.session && current.session.id === confirmation.session_id) {
            startIso = current.session.start_at;
          }
        } catch {
          /* se usa el dato del prompt */
        }
        const start = new Date(startIso).getTime();
        const end = new Date(
          fromDatetimeLocal(`${confirmation.work_date}T${time}`)
        ).getTime();
        setAskConfirm(Math.max(0, Math.round((end - start) / 60000)));
      } else {
        setError(e instanceof ApiError ? e.message : "No se pudo cerrar la jornada.");
      }
    } finally {
      setBusy(false);
    }
  };

  const snooze = async () => {
    if (!confirmation) return;
    setBusy(true);
    setError("");
    try {
      await api.snooze(confirmation.session_id);
      toast({ kind: "info", message: "Perfecto: seguís con la jornada abierta." });
      setOpen(false);
      setConfirmation(null);
      notifyWorkDataChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo posponer.");
    } finally {
      setBusy(false);
    }
  };

  if (!confirmation) return null;

  const isToday = confirmation.scope === "TODAY";
  const title = isToday
    ? "¿A qué hora saliste hoy?"
    : `¿A qué hora saliste ayer (${weekdayShort(confirmation.work_date).toLowerCase()} ${fmtDateShort(confirmation.work_date)})?`;

  return (
    <BottomSheet
      open={open}
      title={title}
      onClose={close}
      dismissOnBackdrop={false}
    >
      <div className="space-y-4">
        <p className="text-sm text-muted">
          Entraste a las <span className="font-medium text-fg">{fmtTime(confirmation.started_at)}</span>
        </p>

        {askConfirm !== null ? (
          <div className="space-y-3">
            <p className="text-sm">
              Eso da <span className="font-semibold">{minutesToHM(askConfirm)}</span>, ¿es correcto?
            </p>
            <div className="flex gap-2">
              <Button
                className="flex-1"
                onClick={() => submit(true)}
                loading={busy}
              >
                Confirmar
              </Button>
              <Button
                variant="secondary"
                onClick={() => setAskConfirm(null)}
                disabled={busy}
              >
                Corregir
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div>
              <label className="label" htmlFor="forgot-checkout-time">
                Hora de salida
              </label>
              <input
                id="forgot-checkout-time"
                type="time"
                className="input"
                value={time}
                onChange={(e) => setTime(e.target.value)}
              />
            </div>
            {error ? <Notice kind="error" message={error} /> : null}
            <div className="flex flex-col gap-2">
              <Button onClick={() => submit(false)} loading={busy} disabled={!time}>
                Confirmar hora de salida
              </Button>
              {isToday ? (
                <Button variant="secondary" onClick={snooze} disabled={busy}>
                  Sigo trabajando
                </Button>
              ) : null}
            </div>
          </>
        )}
      </div>
    </BottomSheet>
  );
}

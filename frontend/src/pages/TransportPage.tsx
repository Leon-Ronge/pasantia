import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import BottomSheet from "../components/BottomSheet";
import Button from "../components/Button";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Modal from "../components/Modal";
import Notice from "../components/Notice";
import ProgressBar from "../components/ProgressBar";
import SegmentedControl from "../components/SegmentedControl";
import { SkeletonCard } from "../components/Skeleton";
import StatCard from "../components/StatCard";
import { useToast } from "../components/Toast";
import Badge from "../components/Badge";
import {
  IconEye,
  IconEyeOff,
  IconPlus,
} from "../components/icons";
import type {
  AppSettings,
  Direction,
  MonthlyHistoryItem,
  TravelRecord,
  TravelSummary,
} from "../types";
import {
  currentMonth,
  fmtARS,
  fmtDate,
  fmtTime,
  fromDatetimeLocal,
  monthLabel,
  toDatetimeLocal,
} from "../lib/format";
import { notifyWorkDataChanged, onWorkDataChanged } from "../lib/refresh";

/** "Oct" a partir de 'YYYY-MM' (etiqueta corta del gráfico). */
function monthShort(ym: string): string {
  return monthLabel(ym).split(" ")[0].slice(0, 3).toLowerCase();
}

export default function TransportPage() {
  const toast = useToast();
  const [month, setMonth] = useState(currentMonth());
  const [summary, setSummary] = useState<TravelSummary | null>(null);
  const [travels, setTravels] = useState<TravelRecord[]>([]);
  const [history, setHistory] = useState<MonthlyHistoryItem[]>([]);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [hideVoided, setHideVoided] = useState(false);
  const [editing, setEditing] = useState<TravelRecord | null>(null);
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Dirección sugerida por la API (para el registro rápido); se cachea para
  // enviarla explícita y que el backend pueda detectar el doble toque (409).
  const [suggested, setSuggested] = useState<Direction>("IDA");
  const [pendingForce, setPendingForce] = useState<{ direction: Direction; label: string } | null>(null);
  const suggestedRef = useRef<Direction>("IDA");

  const load = useCallback(async () => {
    try {
      const [sum, list, hist, cfg, next] = await Promise.all([
        api.travelSummary(month),
        api.listTravels({ month }),
        api.travelHistory(6),
        api.getSettings(),
        api.nextDirection(),
      ]);
      setSummary(sum);
      setTravels(list.results);
      setHistory(hist);
      setSettings(cfg);
      suggestedRef.current = next.direction;
      setSuggested(next.direction);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar Viajes.");
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    load();
  }, [load]);

  // Se refresca cuando cambian datos de viajes en otras pantallas (Inicio).
  useEffect(() => onWorkDataChanged(load), [load]);

  // Importes: ocultos si hide_amounts, con posibilidad de revelar en pantalla.
  const hideAmounts = settings?.hide_amounts ?? false;
  const [revealed, setRevealed] = useState(false);
  const money = (value: string) =>
    hideAmounts && !revealed ? "•••" : fmtARS(value);

  const quickAdd = async (force = false) => {
    setBusy(true);
    try {
      await api.createTravel({ direction: suggestedRef.current }, force);
      setPendingForce(null);
      toast({ kind: "success", message: "Viaje registrado." });
      notifyWorkDataChanged();
      load();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409 && !force) {
        setPendingForce({ direction: suggestedRef.current, label: e.message });
      } else {
        toast({
          kind: "error",
          message: e instanceof ApiError ? e.message : "No se pudo registrar.",
        });
      }
    } finally {
      setBusy(false);
    }
  };

  const visibleTravels = hideVoided
    ? travels.filter((t) => t.status !== "VOIDED")
    : travels;

  const salaryPct = summary?.salary_percentage ?? null;
  const maxTotal = history.reduce(
    (max, h) => Math.max(max, parseFloat(h.total_value)),
    1
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Viajes</h1>
          <p className="text-sm text-muted">{monthLabel(month)}</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="month"
            className="input w-auto"
            value={month}
            onChange={(e) => setMonth(e.target.value || currentMonth())}
            aria-label="Mes"
          />
          {hideAmounts ? (
            <button
              className="rounded-lg p-2 text-muted hover:bg-surface-2"
              onClick={() => setRevealed((r) => !r)}
              aria-label={revealed ? "Ocultar importes" : "Mostrar importes"}
              title={revealed ? "Ocultar importes" : "Mostrar importes"}
            >
              {revealed ? <IconEyeOff className="h-5 w-5" /> : <IconEye className="h-5 w-5" />}
            </button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : error ? (
        <ErrorState message={error} onRetry={() => { setLoading(true); load(); }} />
      ) : (
        <>
          {/* ------------------------------------------------ Resumen (1) */}
          {summary ? (
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatCard
                title="Viajes de la empresa"
                value={`${summary.used_company}/${summary.limit}`}
                sub={`Te quedan ${summary.remaining_company}`}
                accent="accent"
              >
                <div className="mt-2">
                  <ProgressBar
                    value={summary.used_company}
                    max={summary.limit}
                    label="Cupo del mes"
                  />
                </div>
              </StatCard>
              <StatCard
                title="Valor de los viajes"
                value={money(summary.total_value)}
                sub={`${summary.total_count} viaje${summary.total_count === 1 ? "" : "s"}`}
                accent="neutral"
              />
              <StatCard
                title="Pagado por vos"
                value={money(summary.out_of_pocket_value)}
                sub={
                  summary.personal_count > 0
                    ? `${summary.personal_count} viaje${
                        summary.personal_count === 1 ? "" : "s"
                      } personal${summary.personal_count === 1 ? "" : "es"}`
                    : "sin viajes personales"
                }
                accent={summary.personal_count > 0 ? "warning" : "neutral"}
              />
              <StatCard
                title="% de tu sueldo"
                value={salaryPct !== null ? `${salaryPct} %` : "—"}
                sub={salaryPct !== null ? "sobre lo que pagás vos" : undefined}
                accent="neutral"
              >
                {salaryPct === null ? (
                  <Link to="/ajustes" className="mt-2 inline-block">
                    <Button variant="secondary" className="min-h-[44px]">
                      Cargalo en Ajustes
                    </Button>
                  </Link>
                ) : null}
              </StatCard>
            </div>
          ) : null}

          {/* ---------------------------------2. Historial (barras + tabla) */}
          <div className="card">
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">
                Últimos 6 meses
              </p>
              <span className="flex gap-3 text-xs text-muted">
                <span className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-accent" /> empresa
                </span>
                <span className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-error" /> personal
                </span>
              </span>
            </div>
            {history.length === 0 ? (
              <EmptyState title="Sin meses para comparar" />
            ) : (
              <>
                {/* Gráfico de barras apiladas: empresa (abajo) + personal (arriba) */}
                <div className="flex h-40 items-end gap-2">
                  {history.map((h) => {
                    const personal = parseFloat(h.out_of_pocket_value);
                    const total = parseFloat(h.total_value);
                    const company = Math.max(0, total - personal);
                    return (
                      <div key={h.month} className="h-full min-w-0 flex-1">
                        <div
                          className="mx-auto flex h-full w-full max-w-12 flex-col justify-end"
                          title={`${monthLabel(h.month)}: ${fmtARS(total)}`}
                        >
                          {personal > 0 ? (
                            <div
                              className="rounded-t bg-error"
                              style={{ height: `${(personal / maxTotal) * 100}%` }}
                            />
                          ) : null}
                          {company > 0 ? (
                            <div
                              className={`bg-accent ${personal > 0 ? "" : "rounded-t"}`}
                              style={{ height: `${(company / maxTotal) * 100}%` }}
                            />
                          ) : null}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="mt-1 flex gap-2">
                  {history.map((h) => (
                    <span key={h.month} className="flex-1 text-center text-xs text-muted">
                      {monthShort(h.month)}
                    </span>
                  ))}
                </div>

                {/* Tabla por mes */}
                <table className="mt-3 w-full table-fixed text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted">
                      <th className="w-[22%] pb-1 font-medium">Mes</th>
                      <th className="w-[20%] pb-1 text-right font-medium">Viajes</th>
                      <th className="w-[24%] pb-1 text-right font-medium">Total</th>
                      <th className="w-[24%] pb-1 text-right font-medium">Pagado</th>
                      <th className="w-[10%] pb-1 text-right font-medium">%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.month} className="border-t border-line">
                        <td className="py-1.5 pr-1 text-xs">{monthLabel(h.month)}</td>
                        <td className="py-1.5 text-right tabular-nums">
                          {h.ida_count}/{h.vuelta_count}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {money(h.total_value)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {money(h.out_of_pocket_value)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {h.salary_percentage !== null ? `${h.salary_percentage}` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>

          {/* ------------------------------------------- Registro rápido */}
          <div className="card flex flex-wrap items-center gap-2">
            <span className="mr-1 text-sm text-muted">
              Registro rápido (hoy · {suggested === "VUELTA" ? "vuelta" : "ida"} sugerida):
            </span>
            <Button onClick={() => quickAdd()} loading={busy} disabled={!!pendingForce}>
              <IconPlus className="h-4 w-4" />
              Registrar viaje
            </Button>
            <Button variant="ghost" onClick={() => setCreating(true)}>
              Otro viaje…
            </Button>
            <span className="text-xs text-muted">
              El tipo (empresa/personal) se calcula solo según el cupo del mes.
            </span>
          </div>

          {pendingForce ? (
            <div className="card border border-warning">
              <p className="text-sm text-warning-strong">{pendingForce.label}</p>
              <div className="mt-2 flex gap-2">
                <Button
                  variant="ghost"
                  onClick={() => setPendingForce(null)}
                  disabled={busy}
                >
                  Cancelar
                </Button>
                <Button onClick={() => quickAdd(true)} loading={busy}>
                  Registrar igual
                </Button>
              </div>
            </div>
          ) : null}

          {/* -----------------------------------3. Lista de viajes del mes */}
          <div className="card">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">
                Viajes de {monthLabel(month)}
              </p>
              <SegmentedControl
                value={hideVoided ? "activos" : "todos"}
                options={[
                  { value: "todos", label: "Todos" },
                  { value: "activos", label: "Ocultar anulados" },
                ]}
                onChange={(v) => setHideVoided(v === "activos")}
                ariaLabel="Filtro de anulados"
              />
            </div>
            {visibleTravels.length === 0 ? (
              <EmptyState
                title="Sin viajes en este mes"
                description={
                  hideVoided && travels.length > 0
                    ? "Hay viajes anulados: mostrá todos para verlos."
                    : undefined
                }
              />
            ) : (
              <ul className="divide-y divide-line">
                {visibleTravels.map((t) => (
                  <li key={t.id}>
                    <button
                      className="flex w-full items-center gap-3 py-3 text-left transition hover:bg-surface-2"
                      onClick={() => setEditing(t)}
                    >
                      <span className="w-28 shrink-0 text-sm tabular-nums">
                        <span className="block">{fmtDate(t.occurred_at)}</span>
                        <span className="block text-xs text-muted">
                          {fmtTime(t.occurred_at)}
                        </span>
                      </span>
                      <Badge variant="neutral">
                        {t.direction === "IDA" ? "Ida" : "Vuelta"}
                      </Badge>
                      <Badge variant={t.payment_type === "COMPANY" ? "accent" : "warning"}>
                        {t.payment_type === "COMPANY" ? "Empresa" : "Personal"}
                      </Badge>
                      {t.status === "VOIDED" ? (
                        <Badge variant="error">Anulado</Badge>
                      ) : null}
                      <span
                        className={`ml-auto font-medium tabular-nums ${
                          t.status === "VOIDED" ? "text-muted line-through" : ""
                        }`}
                      >
                        {money(t.amount)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </>
      )}

      {/* ------------------------------- Edición (BottomSheet por viaje) */}
      <TravelSheet
        travel={editing}
        onClose={() => setEditing(null)}
        onSaved={(msg) => {
          setEditing(null);
          toast({ kind: "success", message: msg });
          notifyWorkDataChanged();
          load();
        }}
        onError={(msg) => toast({ kind: "error", message: msg })}
      />

      <TravelModal
        open={creating}
        onClose={() => setCreating(false)}
        onSaved={(msg) => {
          setCreating(false);
          toast({ kind: "success", message: msg });
          notifyWorkDataChanged();
          load();
        }}
        onError={(msg) => toast({ kind: "error", message: msg })}
      />
    </div>
  );
}

/** BottomSheet de edición de un viaje: fecha, hora, dirección, importe y anular. */
function TravelSheet({
  travel,
  onClose,
  onSaved,
  onError,
}: {
  travel: TravelRecord | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [direction, setDirection] = useState<Direction>("IDA");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!travel) return;
    const local = toDatetimeLocal(travel.occurred_at); // 'YYYY-MM-DDTHH:mm'
    setDate(local.slice(0, 10));
    setTime(local.slice(11, 16));
    setDirection(travel.direction);
    setAmount(travel.amount);
    setError("");
    setBusy(false); // el componente no se desmonta: reinicia el estado
  }, [travel]);

  if (!travel) return null;

  const save = async () => {
    setBusy(true);
    setError("");
    try {
      await api.updateTravel(travel.id, {
        occurred_at: fromDatetimeLocal(`${date}T${time}`),
        direction,
        amount,
      });
      onSaved("Viaje actualizado.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  const toggleVoid = async () => {
    setBusy(true);
    setError("");
    try {
      const next = travel.status === "ACTIVE" ? "VOIDED" : "ACTIVE";
      await api.updateTravel(travel.id, { status: next });
      onSaved(next === "VOIDED" ? "Viaje anulado." : "Viaje restaurado.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo actualizar.");
      onError(e instanceof ApiError ? e.message : "No se pudo actualizar.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <BottomSheet open title="Editar viaje" onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="tv-date">
              Fecha
            </label>
            <input
              id="tv-date"
              type="date"
              className="input"
              value={date}
              max={toDatetimeLocal(new Date().toISOString()).slice(0, 10)}
              onChange={(e) => setDate(e.target.value)}
              disabled={busy}
            />
          </div>
          <div>
            <label className="label" htmlFor="tv-time">
              Hora
            </label>
            <input
              id="tv-time"
              type="time"
              className="input"
              value={time}
              onChange={(e) => setTime(e.target.value)}
              disabled={busy}
            />
          </div>
        </div>
        <div>
          <span className="label">Dirección</span>
          <SegmentedControl
            value={direction}
            options={[
              { value: "IDA", label: "Ida" },
              { value: "VUELTA", label: "Vuelta" },
            ]}
            onChange={setDirection}
            ariaLabel="Dirección del viaje"
            className="w-full"
          />
        </div>
        <div>
          <label className="label" htmlFor="tv-amount">
            Importe (ARS)
          </label>
          <input
            id="tv-amount"
            type="number"
            step="0.01"
            min="0"
            className="input"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            disabled={busy}
          />
        </div>
        {error ? <Notice kind="error" message={error} /> : null}
        <div className="flex flex-col gap-2">
          <Button onClick={save} loading={busy}>
            Guardar cambios
          </Button>
          <Button
            variant="ghost"
            onClick={toggleVoid}
            disabled={busy}
            title={
              travel.status === "ACTIVE"
                ? "Anula el viaje (no cuenta en ningún cálculo)"
                : "Vuelve a activar el viaje"
            }
          >
            {travel.status === "ACTIVE" ? "Anular viaje" : "Restaurar viaje"}
          </Button>
        </div>
      </div>
    </BottomSheet>
  );
}

/** Modal de alta (funcionalidad existente: "Otro viaje…"). */
function TravelModal({
  open,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [occurredAt, setOccurredAt] = useState(() =>
    toDatetimeLocal(new Date().toISOString())
  );
  const [direction, setDirection] = useState<Direction>("IDA");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError("");
    setOccurredAt(toDatetimeLocal(new Date().toISOString()));
    setAmount("");
    api
      .nextDirection()
      .then((r) => setDirection(r.direction))
      .catch(() => setDirection("IDA"));
  }, [open]);

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      await api.createTravel({
        occurred_at: fromDatetimeLocal(occurredAt),
        direction,
        ...(amount ? { amount } : {}),
      });
      onSaved("Viaje registrado.");
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "No se pudo guardar.";
      setError(msg);
      onError(msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} title="Nuevo viaje" onClose={onClose}>
      <div className="space-y-3">
        <div>
          <label className="label" htmlFor="tv-occurred">
            Fecha y hora
          </label>
          <input
            id="tv-occurred"
            type="datetime-local"
            className="input"
            value={occurredAt}
            max={toDatetimeLocal(new Date().toISOString())}
            onChange={(e) => setOccurredAt(e.target.value)}
          />
        </div>
        <div>
          <span className="label">Dirección</span>
          <SegmentedControl
            value={direction}
            options={[
              { value: "IDA", label: "Ida" },
              { value: "VUELTA", label: "Vuelta" },
            ]}
            onChange={setDirection}
            ariaLabel="Dirección del viaje"
            className="w-full"
          />
        </div>
        <div>
          <label className="label" htmlFor="tv-amount-new">
            Importe (ARS)
          </label>
          <input
            id="tv-amount-new"
            type="number"
            step="0.01"
            min="0"
            className="input"
            placeholder="Vacío = tarifa vigente"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </div>
        {error ? <Notice kind="error" message={error} /> : null}
        <Button className="w-full" onClick={submit} loading={busy}>
          Registrar viaje
        </Button>
      </div>
    </Modal>
  );
}

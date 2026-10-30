import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "../api";
import Badge from "../components/Badge";
import Button from "../components/Button";
import Card from "../components/Card";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import ProgressBar from "../components/ProgressBar";
import SegmentedControl from "../components/SegmentedControl";
import { SkeletonCard } from "../components/Skeleton";
import StatCard from "../components/StatCard";
import { useToast } from "../components/Toast";
import {
  fmtARS,
  fmtDateShort,
  fmtTime,
  longDate,
  minutesToHM,
  todayISO,
  weekdayShort,
} from "../lib/format";
import { notifyWorkDataChanged, onWorkDataChanged } from "../lib/refresh";
import type {
  AppSettings,
  Direction,
  TodayState,
  TravelSummary,
  WeekDay,
  WeekView,
} from "../types";

/** Reloj alineado al cambio de minuto (sin intervalos de sobra). */
function useClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    let timer: number;
    const schedule = () => {
      timer = window.setTimeout(() => {
        setNow(new Date());
        schedule();
      }, 60000 - (Date.now() % 60000));
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, []);
  return now;
}

/** Minutos transcurridos de la jornada en curso (en vivo). */
function elapsedOf(today: TodayState, now: Date): number {
  if (!today.start_at) return 0;
  return Math.max(0, Math.floor((now.getTime() - new Date(today.start_at).getTime()) / 60000));
}

const opposite = (d: Direction): Direction => (d === "IDA" ? "VUELTA" : "IDA");
const dirLabel = (d: Direction) => (d === "IDA" ? "Ida" : "Vuelta");

export default function DashboardPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const now = useClock();

  const [today, setToday] = useState<TodayState | null>(null);
  const [week, setWeek] = useState<WeekView | null>(null);
  const [summary, setSummary] = useState<TravelSummary | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [direction, setDirection] = useState<Direction>("IDA");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyShift, setBusyShift] = useState(false);
  const [tripBusy, setTripBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [t, w, s, nd, cfg] = await Promise.all([
        api.today(),
        api.week(),
        api.travelSummary(),
        api.nextDirection(),
        api.getSettings(),
      ]);
      setToday(t);
      setWeek(w);
      setSummary(s);
      setDirection(nd.direction);
      setSettings(cfg);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar el inicio.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Refresco cuando cambian datos de horas/viajes (cierre olvidado, etc.).
  useEffect(() => onWorkDataChanged(load), [load]);

  // ------------------------------------------------------------- Jornada
  const shiftState = today?.state ?? "NOT_STARTED";
  const planned = today?.planned_minutes ?? 0;
  const elapsed = today ? elapsedOf(today, now) : 0;
  const remaining = Math.max(0, planned - elapsed);

  const checkIn = async () => {
    setBusyShift(true);
    try {
      await api.checkIn();
      toast({ kind: "success", message: "Ingreso registrado." });
      notifyWorkDataChanged();
    } catch (e) {
      toast({ kind: "error", message: e instanceof ApiError ? e.message : "No se pudo registrar el ingreso." });
    } finally {
      setBusyShift(false);
    }
  };

  const checkOut = async () => {
    setBusyShift(true);
    try {
      const closed = await api.checkOut();
      toast({ kind: "success", message: `Egreso registrado: ${minutesToHM(closed.worked_minutes)}.` });
      notifyWorkDataChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        // La duración supera el máximo diario: pedir confirmación explícita.
        if (window.confirm(e.message)) {
          try {
            const closed = await api.checkOut({ confirm: true });
            toast({ kind: "success", message: `Egreso registrado: ${minutesToHM(closed.worked_minutes)}.` });
            notifyWorkDataChanged();
          } catch (e2) {
            toast({ kind: "error", message: e2 instanceof ApiError ? e2.message : "No se pudo registrar el egreso." });
          }
        }
      } else {
        toast({ kind: "error", message: e instanceof ApiError ? e.message : "No se pudo registrar el egreso." });
      }
    } finally {
      setBusyShift(false);
    }
  };

  // ------------------------------------------------------------- Viaje
  const registerTrip = async () => {
    if (tripBusy) return;
    setTripBusy(true); // bloqueo antidooble-tap de1 s
    try {
      const trip = await api.createTravel({ direction });
      const label = dirLabel(direction);
      toast({
        kind: "success",
        message: `${label} registrada.`,
        action: {
          label: "Deshacer",
          onClick: async () => {
            try {
              await api.updateTravel(trip.id, { status: "VOIDED" });
              notifyWorkDataChanged();
            } catch {
              toast({ kind: "error", message: "No se pudo anular el viaje." });
            }
          },
        },
      });
      setDirection(opposite(direction));
      notifyWorkDataChanged();
    } catch (e) {
      toast({ kind: "error", message: e instanceof ApiError ? e.message : "No se pudo registrar el viaje." });
    } finally {
      window.setTimeout(() => setTripBusy(false), 1000);
    }
  };

  // --------------------------------------------------- Cronograma semanal
  const rows = useMemo(() => {
    if (!week) return [];
    const todayHasSession =
      week.today.state !== "NOT_STARTED" && week.today.start_at !== null;
    const hasRecord = (d: WeekDay) =>
      d.status === "DONE" ||
      d.status === "PENDING_CONFIRMATION" ||
      (d.status === "TODAY" && todayHasSession);
    return week.days.filter((d) => d.weekday < 5 || hasRecord(d));
  }, [week]);

  /** ¿Hay alguna jornada registrada en la semana? (para el estado vacío) */
  const hasAnyRecord = useMemo(() => {
    if (!week) return false;
    return week.days.some(
      (d) =>
        d.status === "DONE" ||
        d.status === "PENDING_CONFIRMATION" ||
        (d.status === "TODAY" && week.today.start_at !== null)
    );
  }, [week]);

  const hideAmounts = settings?.hide_amounts ?? false;

  return (
    <div className="space-y-4">
      {/* ------------------------------------------------1. Cabecera reloj */}
      <div className="flex items-end justify-between gap-3">
        <div>
          <p className="text-4xl font-semibold leading-none tabular-nums">
            {fmtTime(now.toISOString())}
          </p>
          <p className="mt-1 text-sm text-muted" >
            <span className="capitalize">{longDate(todayISO())}</span>
            {" · "}
            {fmtDateShort(todayISO())}
          </p>
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
          {/* --------------------------------------------------2. Jornada */}
          {today ? (
            <Card>
              <p className="text-xs font-medium uppercase tracking-wide text-muted">
                Jornada de hoy
              </p>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                {/* Ingreso */}
                <div className="flex flex-col gap-2">
                  <Button
                    variant={shiftState === "NOT_STARTED" ? "primary" : "secondary"}
                    onClick={checkIn}
                    disabled={shiftState !== "NOT_STARTED" || busyShift}
                  >
                    Registrar ingreso
                  </Button>
                  {shiftState === "IN_PROGRESS" && today.start_at ? (
                    <Badge variant="accent">
                      Entraste {fmtTime(today.start_at)}
                      {today.end_at ? ` · Salís ${fmtTime(today.end_at)}` : ""}
                    </Badge>
                  ) : null}
                  {shiftState === "DONE" && today.start_at ? (
                    <Badge variant="neutral">
                      Entraste {fmtTime(today.start_at)}
                      {today.end_at ? ` · Saliste ${fmtTime(today.end_at)}` : ""}
                    </Badge>
                  ) : null}
                </div>
                {/* Egreso */}
                <div className="flex flex-col gap-2">
                  <Button
                    variant={shiftState === "IN_PROGRESS" ? "primary" : "secondary"}
                    onClick={checkOut}
                    disabled={shiftState !== "IN_PROGRESS" || busyShift}
                  >
                    Registrar egreso
                  </Button>
                  {shiftState === "IN_PROGRESS" ? (
                    <div className="space-y-1">
                      <Badge variant="warning">Faltan {minutesToHM(remaining)}</Badge>
                      <ProgressBar value={elapsed} max={planned} label="Jornada" />
                    </div>
                  ) : null}
                  {shiftState === "DONE" ? (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="success">
                        Jornada completa: {minutesToHM(today.worked_minutes)}
                      </Badge>
                      <Button
                        variant="ghost"
                        className="min-h-[36px] px-2"
                        onClick={() => navigate("/horas")}
                      >
                        Corregir
                      </Button>
                    </div>
                  ) : null}
                  {shiftState === "NOT_STARTED" && planned > 0 ? (
                    <div className="space-y-1">
                      <Badge variant="neutral">Faltan {minutesToHM(planned)}</Badge>
                      <ProgressBar value={0} max={planned} label="Jornada" />
                    </div>
                  ) : null}
                </div>
              </div>
            </Card>
          ) : null}

          {/* --------------------------------------------------4. Viaje */}
          <Card>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">
              Próximo viaje
            </p>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <SegmentedControl
                value={direction}
                options={[
                  { value: "IDA", label: "Ida" },
                  { value: "VUELTA", label: "Vuelta" },
                ]}
                onChange={setDirection}
                ariaLabel="Dirección del viaje"
              />
              <Button
                variant="secondary"
                onClick={registerTrip}
                disabled={tripBusy}
              >
                Registrar viaje
              </Button>
            </div>
          </Card>

          {/* ---------------------------------------5. Cronograma semanal */}
          {week ? (
            hasAnyRecord ? (
            <Card>
              <div className="mb-2 flex items-baseline justify-between">
                <p className="text-xs font-medium uppercase tracking-wide text-muted">
                  Cronograma de la semana
                </p>
                <span className="text-xs text-muted">
                  {fmtDateShort(week.week_start)} – {fmtDateShort(week.week_end)}
                </span>
              </div>
              <table className="w-full table-fixed text-sm">
                <thead>
                  <tr className="text-left text-xs text-muted">
                    <th className="w-[26%] pb-1 font-medium">Día</th>
                    <th className="w-[18%] pb-1 text-right font-medium">Ingreso</th>
                    <th className="w-[18%] pb-1 text-right font-medium">Egreso</th>
                    <th className="w-[19%] pb-1 text-right font-medium">Total</th>
                    <th className="w-[19%] pb-1 text-right font-medium">Acum.</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((d) => {
                    const isToday = d.date === todayISO();
                    const hasSession =
                      d.status === "DONE" ||
                      d.status === "PENDING_CONFIRMATION" ||
                      (d.status === "TODAY" && today?.start_at != null);
                    const liveMinutes =
                      isToday && d.status === "TODAY"
                        ? elapsed
                        : d.worked_minutes;
                    return (
                      <tr
                        key={d.date}
                        className={`border-t border-line ${isToday ? "bg-accent-soft/60" : ""}`}
                      >
                        <td className="py-1.5 pr-1">
                          <span className="font-medium">{weekdayShort(d.date)}</span>{" "}
                          <span className="text-xs text-muted">{fmtDateShort(d.date)}</span>
                          {d.status === "HOLIDAY" ? (
                            <Badge variant="warning" className="ml-1">Feriado</Badge>
                          ) : null}
                          {d.status === "PENDING_CONFIRMATION" ? (
                            <Badge variant="warning" className="ml-1">Confirmar</Badge>
                          ) : null}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {hasSession && d.start_at ? fmtTime(d.start_at) : "—"}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {hasSession ? (d.end_at ? fmtTime(d.end_at) : "…") : "—"}
                        </td>
                        <td className="py-1.5 text-right font-medium tabular-nums">
                          {hasSession ? minutesToHM(liveMinutes) : "—"}
                        </td>
                        <td className="py-1.5 text-right tabular-nums">
                          {hasSession
                            ? minutesToHM(
                                rows
                                  .slice(
                                    0,
                                    rows.findIndex((r) => r.date === d.date) + 1
                                  )
                                  .reduce(
                                    (acc, r) =>
                                      acc +
                                      (r.date === d.date
                                        ? liveMinutes
                                        : r.worked_minutes),
                                    0
                                  )
                              )
                            : "—"}
                        </td>
                      </tr>
                    );
                  })}
                  <tr className="border-t-2 border-line font-semibold">
                    <td className="py-1.5">Semana</td>
                    <td />
                    <td />
                    <td className="py-1.5 text-right tabular-nums">
                      {minutesToHM(week.worked_minutes)}
                    </td>
                    <td className="py-1.5 text-right font-normal text-muted tabular-nums">
                      de {minutesToHM(week.target_minutes)}
                    </td>
                  </tr>
                </tbody>
              </table>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge
                  variant={week.remaining_minutes === 0 ? "success" : "accent"}
                >
                  {week.remaining_minutes === 0
                    ? "Objetivo cubierto"
                    : `Faltan ${minutesToHM(week.remaining_minutes)}`}
                </Badge>
                {week.carry_over_minutes > 0 ? (
                  <span className="text-xs text-muted">
                    Incluye {minutesToHM(week.carry_over_minutes)} arrastrados de
                    semanas anteriores.
                  </span>
                ) : null}
              </div>
            </Card>
            ) : (
              <EmptyState
                title="Sin jornadas esta semana"
                description="Todavía no registraste ingresos en la semana. Cuando marques uno, va a aparecer acá con el acumulado."
              />
            )
          ) : null}

          {/* ------------------------------------------------6. Viajes */}
          {summary ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <StatCard
                title="Viajes de empresa"
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
                {settings && !hideAmounts ? (
                  <p className="mt-2 text-xs text-muted">
                    Boleto: {fmtARS(settings.current_fare)}
                  </p>
                ) : null}
                {summary.personal_count > 0 ? (
                  <div className="mt-2">
                    <Badge variant="warning">
                      {summary.personal_count} viaje
                      {summary.personal_count === 1 ? "" : "s"} personal
                      {summary.personal_count === 1 ? "" : "es"}
                      {!hideAmounts
                        ? ` · ${fmtARS(summary.out_of_pocket_value)}`
                        : ""}
                    </Badge>
                  </div>
                ) : null}
              </StatCard>
              <StatCard
                title="Gastado este mes"
                value={hideAmounts ? "•••" : fmtARS(summary.total_value)}
                sub={`${summary.total_count} viajes`}
                accent="neutral"
              />
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

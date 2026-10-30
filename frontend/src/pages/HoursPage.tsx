import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { notifyWorkDataChanged, onWorkDataChanged } from "../lib/refresh";
import Badge from "../components/Badge";
import BottomSheet from "../components/BottomSheet";
import Button from "../components/Button";
import Card from "../components/Card";
import EmptyState from "../components/EmptyState";
import ErrorState from "../components/ErrorState";
import Notice from "../components/Notice";
import ProgressRing from "../components/ProgressRing";
import { SkeletonCard } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import {
  IconChevronLeft,
  IconChevronRight,
  IconLock,
  IconPlay,
  IconStop,
} from "../components/icons";
import type { MonthlySummary, TodayState, WeekDay, WeekView, WorkSession } from "../types";
import {
  addDays,
  currentMonth,
  fmtDateShort,
  fmtTime,
  fromDatetimeLocal,
  minutesToClock,
  minutesToHM,
  mondayOf,
  monthLabel,
  todayISO,
  todayWeekdayIndex,
  weekdayLong,
  weekdayShort,
} from "../lib/format";

/** 'YYYY-MM' ± n meses. */
function shiftMonth(ym: string, delta: number): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** "9:00-14:00 · 5 h" a partir del inicio y la duración planificados. */
function rangeLabel(start: string | null, minutes: number | null): string {
  if (!start || !minutes) return "—";
  const [h, m] = start.split(":").map(Number);
  const total = (h * 60 + m + minutes) % (24 * 60);
  return `${start.slice(0, 5)}-${pad2(Math.floor(total / 60))}:${pad2(total % 60)} · ${minutesToHM(minutes)}`;
}

/** Minutos transcurridos (en vivo) de la jornada abierta. */
function liveElapsed(startAt: string, nowMs: number): number {
  return Math.max(0, Math.floor((nowMs - new Date(startAt).getTime()) / 60000));
}

/** Chip de estado de un día de la vista semanal. */
function StatusChip({ day }: { day: WeekDay }) {
  switch (day.status) {
    case "DONE":
      return <Badge variant="success">Hecho {minutesToClock(day.worked_minutes)}</Badge>;
    case "TODAY":
      return <Badge variant="accent">Hoy</Badge>;
    case "PLANNED":
      return <Badge variant="neutral">Planificado</Badge>;
    case "HOLIDAY":
      return <Badge variant="warning">Feriado</Badge>;
    case "OFF":
      return <Badge variant="neutral">Libre</Badge>;
    case "MISSED":
      return <Badge variant="error">Perdido</Badge>;
    case "PENDING_CONFIRMATION":
      return <Badge variant="warning">Confirmar</Badge>;
    default:
      return null;
  }
}

/** Días que muestra la lista: lun-vie + sáb/dom solo si tienen registros. */
function hasRecord(day: WeekDay, todayHasSession: boolean): boolean {
  return (
    day.status === "DONE" ||
    day.status === "PENDING_CONFIRMATION" ||
    (day.status === "TODAY" && todayHasSession)
  );
}

export default function HoursPage() {
  const toast = useToast();
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [today, setToday] = useState<TodayState | null>(null);
  const [week, setWeek] = useState<WeekView | null>(null);
  const [nextWeek, setNextWeek] = useState<WeekView | null>(null);
  const [todaySession, setTodaySession] = useState<WorkSession | null>(null);
  const [month, setMonth] = useState<MonthlySummary | null>(null);
  const [monthOffset, setMonthOffset] = useState(0);
  const [sessions, setSessions] = useState<WorkSession[]>([]);
  const [filterMonth, setFilterMonth] = useState(currentMonth());
  const [editingDay, setEditingDay] = useState<WeekDay | null>(null);
  const [monthSheetOpen, setMonthSheetOpen] = useState(false);
  const [entryTime, setEntryTime] = useState("");
  const [exitTime, setExitTime] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const monthParam = useMemo(
    () => shiftMonth(currentMonth(), monthOffset),
    [monthOffset]
  );

  const load = useCallback(async () => {
    try {
      // Desde el sábado se muestra también la semana siguiente.
      const showNext = todayWeekdayIndex() >= 5;
      const [t, w, list, m, ts, nw] = await Promise.all([
        api.today(),
        api.week(),
        api.listSessions({ month: filterMonth }),
        api.hoursMonthlySummary(monthParam),
        api.listSessions({ date: todayISO() }),
        showNext ? api.week(addDays(mondayOf(todayISO()), 7)) : Promise.resolve(null),
      ]);
      setToday(t);
      setWeek(w);
      setSessions(list.results);
      setMonth(m);
      setTodaySession(ts.results[0] ?? null);
      setNextWeek(nw);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo cargar Horas.");
    } finally {
      setLoading(false);
    }
  }, [filterMonth, monthParam]);

  useEffect(() => {
    load();
  }, [load]);

  // Se refresca cuando cambian datos de horas en otras pantallas.
  useEffect(() => onWorkDataChanged(load), [load]);

  // Reloj en vivo (minuto a minuto) para restantes y transcurrido.
  useEffect(() => {
    let timer: number;
    const schedule = () => {
      timer = window.setTimeout(() => {
        setNowMs(Date.now());
        schedule();
      }, 60000 - (Date.now() % 60000));
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, []);

  // Precarga de los selectores de hora (entrada real o inicio del plan).
  const todayRow = useMemo(
    () => week?.days.find((d) => d.date === (today?.date ?? todayISO())) ?? null,
    [week, today]
  );
  useEffect(() => {
    if (!today) return;
    setEntryTime(
      today.start_at ? fmtTime(today.start_at) : (todayRow?.planned_start ?? "").slice(0, 5)
    );
    setExitTime(today.end_at ? fmtTime(today.end_at) : "");
  }, [today, todayRow]);

  const state = today?.state ?? "NOT_STARTED";
  const plannedToday = today?.planned_minutes ?? 0;
  const startAtToday = state === "IN_PROGRESS" ? today?.start_at ?? null : null;
  const elapsedToday = startAtToday
    ? liveElapsed(startAtToday, nowMs)
    : (today?.worked_minutes ?? 0);
  const remainingToday = Math.max(0, plannedToday - elapsedToday);

  // Trabajado semanal en vivo (la semana incluye el tiempo de hoy).
  const workedLive = week
    ? week.worked_minutes -
      (today?.worked_minutes ?? 0) +
      (startAtToday ? elapsedToday : (today?.worked_minutes ?? 0))
    : 0;
  const target = week?.target_minutes ?? 0;
  const pct = target > 0 ? Math.round(Math.min(1, workedLive / target) * 100) : 0;

  // --------------------------------------------------------- Acciones
  const registerEntry = async () => {
    if (!entryTime) return;
    setBusy(true);
    try {
      await api.checkIn({
        start_at: fromDatetimeLocal(`${todayISO()}T${entryTime}`),
      });
      toast({ kind: "success", message: "Ingreso registrado." });
      notifyWorkDataChanged();
    } catch (e) {
      toast({
        kind: "error",
        message: e instanceof ApiError ? e.message : "No se pudo registrar el ingreso.",
      });
    } finally {
      setBusy(false);
    }
  };

  const registerExit = async () => {
    if (!exitTime) return;
    setBusy(true);
    try {
      const closed = await api.checkOut({
        end_at: fromDatetimeLocal(`${todayISO()}T${exitTime}`),
      });
      toast({ kind: "success", message: `Egreso registrado: ${minutesToHM(closed.worked_minutes)}.` });
      notifyWorkDataChanged();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) {
        if (window.confirm(e.message)) {
          try {
            const closed = await api.checkOut({
              end_at: fromDatetimeLocal(`${todayISO()}T${exitTime}`),
              confirm: true,
            });
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
      setBusy(false);
    }
  };

  /** Corrección de la jornada de hoy (entrada o salida ya registradas). */
  const patchToday = async (field: "start_at" | "end_at", time: string) => {
    if (!todaySession || !time) return;
    const iso = fromDatetimeLocal(`${todayISO()}T${time}`);
    const payload: { start_at?: string; end_at?: string | null } =
      field === "start_at" ? { start_at: iso } : { end_at: iso };
    try {
      await api.updateSession(todaySession.id, payload);
      toast({ kind: "success", message: "Jornada corregida." });
      notifyWorkDataChanged();
    } catch (e) {
      toast({ kind: "error", message: e instanceof ApiError ? e.message : "No se pudo corregir." });
    }
  };

  const resetWeek = async () => {
    if (!week) return;
    if (!window.confirm("¿Volver toda la semana a automático? Se eliminan las excepciones manuales.")) return;
    try {
      const result = await api.resetPlans(week.week_start);
      toast({
        kind: "success",
        message:
          result.deleted > 0
            ? `Semana restablecida: ${result.deleted} excepciones eliminadas.`
            : "La semana ya estaba automática.",
      });
      notifyWorkDataChanged();
    } catch (e) {
      toast({ kind: "error", message: e instanceof ApiError ? e.message : "No se pudo restablecer." });
    }
  };

  // ------------------------------------------- Avisos de la semana
  const unscheduled = week?.unscheduled_minutes ?? 0;
  const holidayList = useMemo(() => {
    const list: { day: WeekDay; week: WeekView }[] = [];
    if (week) for (const d of week.days) if (d.is_holiday) list.push({ day: d, week });
    if (nextWeek) for (const d of nextWeek.days) if (d.is_holiday) list.push({ day: d, week: nextWeek });
    return list;
  }, [week, nextWeek]);
  const holidayText =
    holidayList.length > 0
      ? `${holidayList
          .map(({ day }) => `${weekdayShort(day.date)} ${parseInt(day.date.slice(8), 10)}`)
          .join(" y ")}: feriado${holidayList.some(({ day }) => day.holiday_name) ? ` (${holidayList.map(({ day }) => day.holiday_name).filter(Boolean).join(", ")})` : ""}`
      : null;

  // Filas de la lista vertical (semana actual + siguiente desde el sábado).
  const rows = useMemo(() => {
    const todayHasSession = todaySession !== null;
    const collect = (w: WeekView | null) =>
      w ? w.days.filter((d) => d.weekday < 5 || hasRecord(d, todayHasSession)) : [];
    return [...collect(week), ...collect(nextWeek)];
  }, [week, nextWeek, todaySession]);

  return (
    <div className="space-y-4">
      <div className="flex items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Horas</h1>
          <p className="text-sm text-muted">
            {week
              ? `${fmtDateShort(week.week_start)} – ${fmtDateShort(week.week_end)}`
              : "Cargando…"}
          </p>
        </div>
        <Button
          variant="secondary"
          className="min-h-[44px]"
          onClick={() => setMonthSheetOpen(true)}
          disabled={!month}
        >
          Resumen mensual
        </Button>
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
          {/* -------------------------------------------1. Jornada actual */}
          <Card>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">
              Jornada actual
            </p>
            {state === "NOT_STARTED" ? (
              <p className="mt-2 text-sm">
                Sin jornada hoy
                {todayRow?.planned_start && todayRow?.planned_minutes ? (
                  <span className="text-muted">
                    {" "}· plan {rangeLabel(todayRow.planned_start, todayRow.planned_minutes).split(" · ")[0]}
                  </span>
                ) : (
                  <span className="text-muted"> · sin plan para hoy</span>
                )}
              </p>
            ) : null}
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {/* Ingreso */}
              <div>
                <label className="label" htmlFor="shift-entry">
                  Ingreso
                </label>
                <div className="flex gap-2">
                  <input
                    id="shift-entry"
                    type="time"
                    className="input"
                    value={entryTime}
                    onChange={(e) => setEntryTime(e.target.value)}
                    disabled={busy}
                  />
                  {state === "NOT_STARTED" ? (
                    <Button onClick={registerEntry} loading={busy} disabled={!entryTime}>
                      <IconPlay className="h-4 w-4" />
                      Registrar
                    </Button>
                  ) : (
                    <Button
                      variant="ghost"
                      onClick={() => patchToday("start_at", entryTime)}
                      disabled={!todaySession || !entryTime}
                    >
                      Corregir
                    </Button>
                  )}
                </div>
              </div>
              {/* Egreso */}
              <div>
                <label className="label" htmlFor="shift-exit">
                  Egreso
                </label>
                <div className="flex gap-2">
                  <input
                    id="shift-exit"
                    type="time"
                    className="input"
                    value={exitTime}
                    onChange={(e) => setExitTime(e.target.value)}
                    disabled={state === "NOT_STARTED" || busy}
                  />
                  {state === "IN_PROGRESS" ? (
                    <Button onClick={registerExit} loading={busy} disabled={!exitTime}>
                      <IconStop className="h-4 w-4" />
                      Registrar
                    </Button>
                  ) : state === "DONE" ? (
                    <Button
                      variant="ghost"
                      onClick={() => patchToday("end_at", exitTime)}
                      disabled={!todaySession || !exitTime}
                    >
                      Corregir
                    </Button>
                  ) : null}
                </div>
              </div>
            </div>
            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <div className="flex gap-2">
                <dt className="text-muted">Salida prevista</dt>
                <dd className="font-medium tabular-nums">
                  {today?.end_at ? fmtTime(today.end_at) : "—"}
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-muted">Falta</dt>
                <dd className="font-medium tabular-nums">
                  {state === "DONE"
                    ? `completa: ${minutesToHM(today?.worked_minutes ?? 0)}`
                    : minutesToHM(remainingToday)}
                </dd>
              </div>
            </dl>
          </Card>

          {/* ---------------------------------2. Objetivo semanal (anillo) */}
          <Card>
            <div className="flex flex-wrap items-center gap-5">
              <ProgressRing
                value={workedLive}
                max={target}
                size={120}
                thickness={10}
                label="Objetivo semanal"
                center={
                  <div className="leading-tight">
                    <p className="text-sm font-semibold tabular-nums">
                      {minutesToHM(workedLive)}
                    </p>
                    <p className="text-xs text-muted tabular-nums">
                      de {minutesToHM(target)}
                    </p>
                  </div>
                }
              />
              <div className="space-y-1 text-sm">
                <p className="text-2xl font-semibold tabular-nums">{pct}%</p>
                <p className="flex gap-2">
                  <span className="text-muted">Trabajadas</span>
                  <span className="font-medium tabular-nums">{minutesToHM(workedLive)}</span>
                </p>
                <p className="flex gap-2">
                  <span className="text-muted">Restantes</span>
                  <span className="font-medium tabular-nums">
                    {minutesToHM(week?.remaining_minutes ?? 0)}
                  </span>
                </p>
              </div>
            </div>
            {week?.projected_end ? (
              <p className="mt-3 text-sm text-muted">
                Completás el{" "}
                <span className="font-medium text-fg">
                  {weekdayLong(week.projected_end.date).toLowerCase()} {week.projected_end.time}
                </span>
              </p>
            ) : (
              <p className="mt-3 text-sm text-muted">Sin proyección de cierre.</p>
            )}

            {unscheduled > 0 ? (
              <div className="mt-3 rounded-xl bg-error-soft px-3 py-2 text-sm text-error-strong">
                Quedan <strong className="tabular-nums">{minutesToHM(unscheduled)}</strong>{" "}
                sin programar: no quedan días hábiles esta semana (feriados, días libres
                o no disponibles).
              </div>
            ) : null}
            {holidayText ? (
              <div className="mt-3 rounded-xl bg-warning-soft px-3 py-2 text-sm text-warning-strong">
                {holidayText}
              </div>
            ) : null}
          </Card>

          {/* ------------------------------3. Planificación (lista) */}
          <Card>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">
                Planificación semanal
              </p>
              <Button variant="ghost" className="min-h-[44px]" onClick={resetWeek}>
                Restablecer semana
              </Button>
            </div>
            {rows.length === 0 ? (
              <EmptyState title="Sin días para mostrar" />
            ) : (
              <ul className="divide-y divide-line">
                {rows.map((d) => (
                  <li key={d.date}>
                    <button
                      className="flex w-full items-center gap-3 py-3 text-left transition hover:bg-surface-2"
                      onClick={() => setEditingDay(d)}
                    >
                      <span className="w-20 shrink-0">
                        <span className="block text-sm font-medium">
                          {weekdayShort(d.date)}
                        </span>
                        <span className="block text-xs text-muted">
                          {fmtDateShort(d.date)}
                        </span>
                      </span>
                      <span className="min-w-0 flex-1 text-sm tabular-nums">
                        {rangeLabel(d.planned_start, d.planned_minutes)}
                      </span>
                      {d.is_locked ? (
                        <IconLock className="h-4 w-4 shrink-0 text-muted" />
                      ) : null}
                      <StatusChip day={d} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {/* ---------------------------------4. Resumen mensual + histórico */}
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">
                Jornadas anteriores
              </p>
              <input
                type="month"
                className="input w-auto"
                value={filterMonth}
                onChange={(e) => setFilterMonth(e.target.value || currentMonth())}
                aria-label="Mes del historial"
              />
            </div>
            {sessions.length === 0 ? (
              <EmptyState title="Sin jornadas en este mes" />
            ) : (
              <ul className="divide-y divide-line">
                {sessions.map((s) => (
                  <SessionRow
                    key={`${s.id}-${s.updated_at}`}
                    session={s}
                    onSaved={() => {
                      toast({ kind: "success", message: "Jornada corregida." });
                      notifyWorkDataChanged();
                    }}
                    onError={(msg) => toast({ kind: "error", message: msg })}
                  />
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      {/* ----------------------------------------- Editor de un día */}
      <DayEditorSheet
        day={editingDay}
        onClose={() => setEditingDay(null)}
        onSaved={(msg) => {
          setEditingDay(null);
          toast({ kind: "success", message: msg });
          notifyWorkDataChanged();
        }}
        onError={(msg) => toast({ kind: "error", message: msg })}
      />

      {/* ------------------------------------------ Resumen mensual */}
      <BottomSheet
        open={monthSheetOpen}
        title="Resumen mensual"
        onClose={() => setMonthSheetOpen(false)}
      >
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <button
              className="rounded-lg p-2 text-muted hover:bg-surface-2"
              onClick={() => setMonthOffset((o) => o - 1)}
              aria-label="Mes anterior"
            >
              <IconChevronLeft className="h-5 w-5" />
            </button>
            <p className="text-sm font-semibold">{monthLabel(monthParam)}</p>
            <button
              className="rounded-lg p-2 text-muted hover:bg-surface-2 disabled:opacity-40"
              onClick={() => setMonthOffset((o) => Math.min(0, o + 1))}
              disabled={monthOffset >= 0}
              aria-label="Mes siguiente"
            >
              <IconChevronRight className="h-5 w-5" />
            </button>
          </div>
          {month ? (
            <>
              <ul className="divide-y divide-line text-sm">
                {month.weeks.map((w) => (
                  <li key={w.week_start} className="flex items-center justify-between gap-3 py-2">
                    <span className="text-muted">
                      {fmtDateShort(w.week_start)} – {fmtDateShort(w.week_end)}
                    </span>
                    <span className="tabular-nums">
                      <span className="font-medium">{minutesToHM(w.worked_minutes)}</span>
                      <span className="text-muted"> / {minutesToHM(w.target_minutes)}</span>
                    </span>
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between rounded-xl bg-surface-2 px-3 py-2 text-sm font-semibold">
                <span>Total {monthLabel(monthParam)}</span>
                <span className="tabular-nums">
                  {minutesToHM(month.total_worked_minutes)} / {minutesToHM(month.total_target_minutes)}
                </span>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted">Sin datos de ese mes.</p>
          )}
        </div>
      </BottomSheet>
    </div>
  );
}

/** Fila editable de "Jornadas anteriores": hora de entrada y salida. */
function SessionRow({
  session,
  onSaved,
  onError,
}: {
  session: WorkSession;
  onSaved: () => void;
  onError: (msg: string) => void;
}) {
  const [start, setStart] = useState(() => fmtTime(session.start_at));
  const [end, setEnd] = useState(() => (session.end_at ? fmtTime(session.end_at) : ""));
  const [busy, setBusy] = useState(false);

  const patch = async (field: "start_at" | "end_at", iso: string | null) => {
    setBusy(true);
    const payload: { start_at?: string; end_at?: string | null } =
      field === "start_at" ? { start_at: iso ?? "" } : { end_at: iso };
    try {
      await api.updateSession(session.id, payload);
      onSaved();
    } catch (e) {
      onError(e instanceof ApiError ? e.message : "No se pudo corregir la jornada.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="flex flex-wrap items-center gap-2 py-2 text-sm">
      <span className="w-14 shrink-0 text-muted">{fmtDateShort(session.work_date)}</span>
      <input
        type="time"
        className="input w-24 py-1.5"
        aria-label={`Entrada del ${fmtDateShort(session.work_date)}`}
        value={start}
        disabled={busy}
        onChange={(e) => setStart(e.target.value)}
        onBlur={() => {
          const original = fmtTime(session.start_at);
          if (start && start !== original) {
            patch("start_at", fromDatetimeLocal(`${session.work_date}T${start}`));
          }
        }}
      />
      <input
        type="time"
        className="input w-24 py-1.5"
        aria-label={`Salida del ${fmtDateShort(session.work_date)}`}
        value={end}
        disabled={busy}
        onChange={(e) => setEnd(e.target.value)}
        onBlur={() => {
          const original = session.end_at ? fmtTime(session.end_at) : "";
          if (end !== original) {
            patch("end_at", end ? fromDatetimeLocal(`${session.work_date}T${end}`) : null);
          }
        }}
      />
      <span className="ml-auto font-medium tabular-nums">
        {minutesToHM(
          session.status === "IN_PROGRESS" ? session.elapsed_minutes : session.worked_minutes
        )}
      </span>
    </li>
  );
}

/** BottomSheet de edición de un día (excepción manual del plan). */
function DayEditorSheet({
  day,
  onClose,
  onSaved,
  onError,
}: {
  day: WeekDay | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [start, setStart] = useState("");
  const [minutes, setMinutes] = useState("");
  const [locked, setLocked] = useState(false);
  const [available, setAvailable] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!day) return;
    // Todo precargado desde el plan que devuelve la API (nada hardcodeado).
    setStart(day.planned_start ?? "");
    setMinutes(day.planned_minutes != null ? String(day.planned_minutes) : "");
    setLocked(day.is_locked);
    setAvailable(day.status !== "OFF");
    setError("");
  }, [day]);

  if (!day) return null;

  const save = async () => {
    const mins = available ? parseInt(minutes, 10) : 0;
    if (available && !start) {
      setError("Ingresá la hora de inicio.");
      return;
    }
    if (available && (isNaN(mins) || mins <= 0 || mins > 1440)) {
      setError("La duración debe estar entre 1 y 1440 minutos.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.savePlan(day.date, {
        planned_start: start,
        planned_minutes: mins,
        is_available: available,
        is_locked: locked,
      });
      onSaved(day.is_manual ? "Día actualizado." : "Excepción creada sobre el plan automático.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    setError("");
    try {
      await api.deletePlan(day.date);
      onSaved("Día vuelto a automático.");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo eliminar.");
      onError(e instanceof ApiError ? e.message : "No se pudo eliminar.");
      setBusy(false);
    }
  };

  return (
    <BottomSheet open title={`${weekdayLong(day.date)} ${fmtDateShort(day.date)}`} onClose={onClose}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="day-start">
              Hora de inicio
            </label>
            <input
              id="day-start"
              type="time"
              className="input"
              value={start}
              onChange={(e) => setStart(e.target.value)}
              disabled={!available || busy}
            />
          </div>
          <div>
            <label className="label" htmlFor="day-minutes">
              Duración (min)
            </label>
            <input
              id="day-minutes"
              type="number"
              min="1"
              max="1440"
              className="input"
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
              disabled={!available || busy}
            />
          </div>
        </div>
        <label className="flex min-h-[44px] items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={locked}
            onChange={(e) => setLocked(e.target.checked)}
            disabled={busy}
          />
          Bloquear (no se puede eliminar sin desbloquear)
        </label>
        <label className="flex min-h-[44px] items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="h-4 w-4"
            checked={!available}
            onChange={(e) => setAvailable(!e.target.checked)}
            disabled={busy}
          />
          Marcar como no disponible
        </label>
        {error ? <Notice kind="error" message={error} /> : null}
        <div className="flex flex-col gap-2">
          <Button onClick={save} loading={busy}>
            Guardar
          </Button>
          {day.is_manual ? (
            <Button
              variant="ghost"
              onClick={remove}
              disabled={busy || day.is_locked}
              title={day.is_locked ? "Desbloqueá el día primero" : undefined}
            >
              Volver a automático
            </Button>
          ) : null}
        </div>
      </div>
    </BottomSheet>
  );
}

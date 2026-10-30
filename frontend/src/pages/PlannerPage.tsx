import { useCallback, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { onWorkDataChanged } from "../lib/refresh";
import Modal from "../components/Modal";
import Notice from "../components/Notice";
import ProgressBar from "../components/ProgressBar";
import {
  IconCalendar,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconEdit,
  IconLock,
  IconTrash,
} from "../components/icons";
import type {
  AppSettings,
  WeekDay,
  WeekdayTemplate,
  WeekView,
} from "../types";
import {
  addDays,
  fmtDate,
  fmtTime,
  minutesToHM,
  mondayOf,
  todayISO,
  weekdayIndexOf,
  weekdayLong,
  weekdayNameFromIndex,
  weekdayShort,
} from "../lib/format";

type Mode = "auto" | "manual";

export default function PlannerPage() {
  const [offset, setOffset] = useState(0);
  const [mode, setMode] = useState<Mode>("auto");
  const [view, setView] = useState<WeekView | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; message: string } | null>(null);
  const [editing, setEditing] = useState<WeekDay | null>(null);
  const [busy, setBusy] = useState(false);

  const weekStart = useMemo(
    () => addDays(mondayOf(todayISO()), offset * 7),
    [offset]
  );

  const load = useCallback(async () => {
    try {
      const [weekView, cfg] = await Promise.all([
        api.week(weekStart),
        api.getSettings(),
      ]);
      setView(weekView);
      setSettings(cfg);
    } catch (e) {
      setNotice({
        kind: "error",
        message: e instanceof ApiError ? e.message : "No se pudo cargar la semana.",
      });
    }
  }, [weekStart]);

  useEffect(() => {
    load();
  }, [load]);

  // Se refresca cuando cambian datos de horas (cierre olvidado, correcciones).
  useEffect(() => onWorkDataChanged(load), [load]);

  const guard = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
      await load();
    } catch (e) {
      setNotice({
        kind: "error",
        message: e instanceof ApiError ? e.message : "No se pudo completar la acción.",
      });
    } finally {
      setBusy(false);
    }
  };

  /** Bloquea/desbloquea la excepción manual de ese día (upsert por fecha). */
  const toggleLock = (day: WeekDay) =>
    guard(async () => {
      await api.savePlan(day.date, { is_locked: !day.is_locked });
      setNotice({
        kind: "success",
        message: day.is_locked ? "Jornada desbloqueada." : "Jornada bloqueada.",
      });
    });

  /** Marca/desmarca el día como no disponible (excepción por fecha). */
  const toggleAvailable = (day: WeekDay) =>
    guard(async () => {
      if (day.status === "OFF" && day.is_manual) {
        // Ya era no disponible: se elimina la excepción y vuelve a automático.
        await api.deletePlan(day.date);
        setNotice({ kind: "success", message: "Día habilitado (vuelve a automático)." });
        return;
      }
      if (day.status === "OFF") {
        // Día OFF de plantilla: se anula con una excepción manual no disponible.
        await api.savePlan(day.date, { is_available: false, planned_minutes: 0 });
        setNotice({ kind: "success", message: "Día marcado como no disponible." });
        return;
      }
      const ok = window.confirm(
        `Al marcar ${fmtDate(day.date)} como no disponible se quitan sus minutos del plan. ¿Continuar?`
      );
      if (!ok) return;
      await api.savePlan(day.date, { is_available: false, planned_minutes: 0 });
      setNotice({ kind: "success", message: "Día marcado como no disponible." });
    });

  const removeManual = (day: WeekDay) =>
    guard(async () => {
      const ok = window.confirm(
        "¿Eliminar la excepción manual de este día? Vuelve al plan automático."
      );
      if (!ok) return;
      await api.deletePlan(day.date);
      setNotice({ kind: "success", message: "Día vuelto a automático." });
    });

  const resetWeek = () =>
    guard(async () => {
      const ok = window.confirm(
        "¿Volver toda la semana a automático? Se eliminan las excepciones manuales."
      );
      if (!ok) return;
      const result = await api.resetPlans(weekStart);
      setNotice({
        kind: "success",
        message:
          result.deleted > 0
            ? `Semana limpia: ${result.deleted} excepciones eliminadas.`
            : "La semana ya estaba 100 % automática.",
      });
    });

  const weeklyTarget = view?.target_minutes ?? settings?.weekly_target_minutes ?? 0;
  /** Plantilla del día: aporta la hora y duración por defecto al editar. */
  const templateOf = (isoDate: string | null | undefined) =>
    isoDate
      ? settings?.weekday_templates.find(
          (t) => t.weekday === weekdayIndexOf(isoDate)
        ) ?? null
      : null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Planificador semanal</h1>
          <p className="text-sm text-slate-500">
            {view ? `${fmtDate(view.week_start)} – ${fmtDate(view.week_end)}` : "Cargando…"}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button
            className="btn-ghost"
            onClick={() => setOffset((o) => o - 1)}
            aria-label="Semana anterior"
          >
            <IconChevronLeft className="h-4 w-4" />
          </button>
          <button className="btn-ghost" onClick={() => setOffset(0)} disabled={offset === 0}>
            Hoy
          </button>
          <button
            className="btn-ghost"
            onClick={() => setOffset((o) => o + 1)}
            aria-label="Semana siguiente"
          >
            <IconChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      {notice ? (
        <Notice
          kind={notice.kind}
          message={notice.message}
          onClose={() => setNotice(null)}
        />
      ) : null}

      {/* ---------------------------------------------------------- Balance */}
      {view ? (
        <div className="card">
          <div className="mb-2 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <p className="text-xs text-slate-500">Objetivo</p>
              <p className="font-semibold">{minutesToHM(view.target_minutes)}</p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Trabajado</p>
              <p className="font-semibold text-brand-600 dark:text-brand-100">
                {minutesToHM(view.worked_minutes)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Restante (con plan)</p>
              <p className="font-semibold text-amber-600 dark:text-amber-400">
                {minutesToHM(view.remaining_minutes)}
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Sin programar</p>
              <p
                className={`font-semibold ${
                  view.unscheduled_minutes > 0
                    ? "text-rose-600 dark:text-rose-400"
                    : "text-emerald-600 dark:text-emerald-400"
                }`}
              >
                {minutesToHM(view.unscheduled_minutes)}
              </p>
            </div>
          </div>
          <ProgressBar
            value={view.worked_minutes}
            max={view.target_minutes + view.carry_over_minutes}
            label="Avance de la semana"
          />
          <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
            {view.carry_over_minutes > 0
              ? `Incluye ${minutesToHM(view.carry_over_minutes)} arrastrados de semanas anteriores · `
              : ""}
            {view.projected_end
              ? `Terminás el ${fmtDate(view.projected_end.date)} a las ${view.projected_end.time}`
              : "Sin jornadas ni plan para proyectar"}
          </p>
        </div>
      ) : null}

      {/* --------------------------------------------------- Selector de modo */}
      <div className="flex gap-1 rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900 sm:w-fit">
        <button
          className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition ${
            mode === "auto"
              ? "bg-brand-600 text-white"
              : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          }`}
          onClick={() => setMode("auto")}
        >
          Modo automático
        </button>
        <button
          className={`flex-1 rounded-md px-4 py-2 text-sm font-medium transition ${
            mode === "manual"
              ? "bg-brand-600 text-white"
              : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
          }`}
          onClick={() => setMode("manual")}
        >
          Modo manual
        </button>
      </div>

      {mode === "auto" ? (
        <div className="card space-y-3">
          <div className="flex items-start gap-3">
            <IconCalendar className="mt-0.5 h-5 w-5 shrink-0 text-brand-600" />
            <div className="text-sm text-slate-600 dark:text-slate-300">
              El plan se calcula solo con cada registro o corrección: reparte{" "}
              {minutesToHM(weeklyTarget)} priorizando los días preferidos (
              {settings
                ? settings.weekday_templates
                    .filter((t) => t.kind === "PREFERRED")
                    .map((t) => weekdayNameFromIndex(t.weekday))
                    .join(", ") || "sin días preferidos"
                : "…"}
              ), sin tocar feriados, días no disponibles ni excepciones manuales.
              Nada se guarda: al corregir una jornada el plan se autocorrige.
            </div>
          </div>
          {view && view.unscheduled_minutes > 0 ? (
            <div className="rounded-lg bg-rose-50 p-3 text-sm text-rose-700 dark:bg-rose-950/40 dark:text-rose-300">
              Quedaron <strong>{minutesToHM(view.unscheduled_minutes)}</strong> sin
              programar: no hay más días hábiles esta semana. Podés marcar un día como
              disponible o corregir jornadas.
            </div>
          ) : null}
          {view && view.needs_checkout_confirmation ? (
            <div className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-300">
              Hay una jornada pendiente de confirmación (
              {fmtDate(view.needs_checkout_confirmation.work_date)}): sus minutos cuentan
              solo hasta la salida prevista hasta que la cierres desde Horas o el Dashboard.
            </div>
          ) : null}
        </div>
      ) : (
        <div className="card flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-600 dark:text-slate-300">
            En modo manual cargás excepciones por día (horario, duración, bloqueo o no
            disponible). Se respetan sobre el plan automático y se pueden revertir.
          </p>
          <button className="btn-ghost" onClick={resetWeek} disabled={busy}>
            Volver semana a automático
          </button>
        </div>
      )}

      {/* ------------------------------------------------------ Calendario */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
        {view?.days.map((day) => (
          <DayCard
            key={day.date}
            day={day}
            mode={mode}
            busy={busy}
            onEdit={() => setEditing(day)}
            onToggleLock={toggleLock}
            onToggleAvailable={toggleAvailable}
            onRemoveManual={removeManual}
          />
        ))}
      </div>

      <PlanModal
        day={editing}
        open={!!editing}
        template={templateOf(editing?.date)}
        onClose={() => setEditing(null)}
        onSaved={(msg) => {
          setEditing(null);
          setNotice({ kind: "success", message: msg });
          load();
        }}
        onDelete={async (day) => {
          setEditing(null);
          await removeManual(day);
        }}
      />
    </div>
  );
}

/** Etiqueta corta del estado del día. */
function statusLabel(day: WeekDay): string {
  switch (day.status) {
    case "HOLIDAY":
      return day.holiday_name ? `Feriado · ${day.holiday_name}` : "Feriado";
    case "OFF":
      return day.is_manual ? "No disponible" : "Día libre";
    case "MISSED":
      return "Sin jornada";
    case "PENDING_CONFIRMATION":
      return "Sin confirmar";
    case "DONE":
      return "Completada";
    case "TODAY":
      return "Hoy";
    default:
      return day.is_manual ? "Manual" : "Planificado";
  }
}

function DayCard({
  day,
  mode,
  busy,
  onEdit,
  onToggleLock,
  onToggleAvailable,
  onRemoveManual,
}: {
  day: WeekDay;
  mode: Mode;
  busy: boolean;
  onEdit: () => void;
  onToggleLock: (day: WeekDay) => void;
  onToggleAvailable: (day: WeekDay) => void;
  onRemoveManual: (day: WeekDay) => void;
}) {
  const isToday = day.status === "TODAY" || (day.date === todayISO());
  const isPast = day.date < todayISO();
  const planned = day.planned_minutes !== null && day.planned_minutes > 0;
  const diff = day.diff_minutes;

  return (
    <div
      className={`card flex flex-col gap-2 ${
        isToday ? "ring-2 ring-brand-500" : ""
      } ${isPast && day.status === "MISSED" ? "opacity-80" : ""}`}
    >
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm font-semibold">{weekdayShort(day.date)}</p>
          <p className="text-xs text-slate-500">{fmtDate(day.date)}</p>
        </div>
        {isToday ? (
          <span className="badge bg-brand-50 text-brand-700 dark:bg-slate-800 dark:text-brand-100">
            Hoy
          </span>
        ) : null}
      </div>

      {day.status === "HOLIDAY" || day.status === "OFF" ? (
        <div className="rounded-lg bg-slate-100 px-2 py-2 text-xs text-slate-500 dark:bg-slate-800 dark:text-slate-400">
          {statusLabel(day)}
        </div>
      ) : planned ? (
        <div className="rounded-lg bg-brand-50 px-2 py-2 text-xs dark:bg-slate-800">
          <p className="font-semibold text-brand-700 dark:text-brand-100">
            {day.planned_start} – {fmtTime(day.end_at)}
          </p>
          <p className="text-slate-500 dark:text-slate-400">
            {minutesToHM(day.planned_minutes ?? 0)}
            {day.status === "PENDING_CONFIRMATION" ? (
              <span className="ml-1 text-amber-600 dark:text-amber-400">· sin cerrar</span>
            ) : null}
          </p>
        </div>
      ) : (
        <div className="rounded-lg px-2 py-2 text-xs text-slate-400">
          {statusLabel(day)}
        </div>
      )}

      {day.worked_minutes > 0 || day.status === "DONE" || isToday ? (
        <div className="rounded-lg bg-emerald-50 px-2 py-2 text-xs dark:bg-emerald-950/60">
          <p className="font-medium text-emerald-700 dark:text-emerald-300">
            Real: {minutesToHM(day.worked_minutes)}
          </p>
          {planned && day.status !== "TODAY" ? (
            <p
              className={`font-medium ${
                diff >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-amber-600 dark:text-amber-400"
              }`}
            >
              ({diff >= 0 ? "+" : "−"}
              {Math.abs(diff)} min vs plan)
            </p>
          ) : null}
        </div>
      ) : null}

      {mode === "manual" && !isPast ? (
        <div className="mt-auto flex flex-wrap gap-1 pt-1">
          <button
            className="btn-ghost !px-2 !py-1 text-xs"
            onClick={onEdit}
            disabled={busy}
            title="Excepción manual del día"
          >
            <IconEdit className="h-3.5 w-3.5" />
          </button>
          <button
            className="btn-ghost !px-2 !py-1 text-xs"
            onClick={() => onToggleLock(day)}
            disabled={busy || !day.is_manual}
            title={
              !day.is_manual
                ? "Primero cargá una excepción manual"
                : "Bloquear/desbloquear"
            }
          >
            <IconLock className="h-3.5 w-3.5" />
          </button>
          <button
            className="btn-ghost !px-2 !py-1 text-xs"
            onClick={() => onToggleAvailable(day)}
            disabled={busy}
            title={day.status === "OFF" ? "Habilitar día" : "Marcar no disponible"}
          >
            {day.status === "OFF" ? (
              <IconCheck className="h-3.5 w-3.5" />
            ) : (
              <IconTrash className="h-3.5 w-3.5" />
            )}
          </button>
          {day.is_manual ? (
            <button
              className="btn-ghost !px-2 !py-1 text-xs"
              onClick={() => onRemoveManual(day)}
              disabled={busy}
              title="Volver a automático"
            >
              <IconTrash className="h-3.5 w-3.5 text-rose-500" />
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PlanModal({
  day,
  open,
  template,
  onClose,
  onSaved,
  onDelete,
}: {
  day: WeekDay | null;
  open: boolean;
  /** Plantilla del día: aporta la hora y duración por defecto. */
  template: WeekdayTemplate | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onDelete?: (day: WeekDay) => void | Promise<void>;
}) {
  const [start, setStart] = useState("");
  const [minutes, setMinutes] = useState("");
  const [locked, setLocked] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || !day) return;
    setError("");
    setStart(day.planned_start ?? template?.start_time.slice(0, 5) ?? "09:00");
    setMinutes(
      String(
        day.planned_minutes ??
          template?.resolved_minutes ??
          300
      )
    );
    setLocked(day.is_manual);
  }, [open, day, template]);

  const submit = async () => {
    if (!day) return;
    const mins = parseInt(minutes, 10);
    if (isNaN(mins) || mins <= 0 || mins > 1440) {
      setError("La duración debe estar entre 1 y 1440 minutos.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.savePlan(day.date, {
        planned_start: start,
        planned_minutes: mins,
        is_available: true,
        is_locked: locked,
      });
      onSaved(
        day.is_manual
          ? "Excepción manual actualizada."
          : "Excepción manual creada sobre el plan automático."
      );
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} title="Excepción manual del día" onClose={onClose}>
      <div className="space-y-3">
        <div className="rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
          {day ? `${weekdayLong(day.date)} ${fmtDate(day.date)}` : ""}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="plan-start">
              Entrada prevista
            </label>
            <input
              id="plan-start"
              type="time"
              className="input"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div>
            <label className="label" htmlFor="plan-minutes">
              Duración (min)
            </label>
            <input
              id="plan-minutes"
              type="number"
              min="1"
              max="1440"
              className="input"
              value={minutes}
              onChange={(e) => setMinutes(e.target.value)}
            />
          </div>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={locked}
            onChange={(e) => setLocked(e.target.checked)}
            className="h-4 w-4 rounded border-slate-300"
          />
          Bloquear (no se puede eliminar sin desbloquear)
        </label>
        <p className="text-xs text-slate-500">
          Esta excepción reemplaza al plan automático de ese día.
        </p>
        {error ? <Notice kind="error" message={error} /> : null}
        <div className="flex gap-2">
          <button className="btn-primary flex-1" onClick={submit} disabled={busy}>
            Guardar
          </button>
          {day?.is_manual && onDelete && !locked ? (
            <button
              className="btn-danger"
              onClick={() => onDelete(day)}
              disabled={busy}
              title="Eliminar excepción (vuelve a automático)"
            >
              <IconTrash className="h-4 w-4" />
            </button>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

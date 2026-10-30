import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api";
import Button from "../components/Button";
import ErrorState from "../components/ErrorState";
import Modal from "../components/Modal";
import SegmentedControl from "../components/SegmentedControl";
import { SkeletonCard } from "../components/Skeleton";
import Badge from "../components/Badge";
import Notice from "../components/Notice";
import { useToast } from "../components/Toast";
import { IconDownload, IconEdit, IconPlus, IconTrash } from "../components/icons";
import { applyTheme, getTheme, type ThemePreference } from "../lib/theme";
import {
  fmtDate,
  minutesToHM,
  todayISO,
  weekdayNameFromIndex,
} from "../lib/format";
import type {
  AppSettings,
  Holiday,
  HolidayKind,
  Paginated,
  SettingsPatch,
  WeekdayKind,
  WeekdayTemplate,
} from "../types";

const KIND_LABEL: Record<WeekdayKind, string> = {
  PREFERRED: "Preferido",
  RESERVE: "Reserva",
  OFF: "Libre",
};

const HOLIDAY_KIND_LABEL: Record<HolidayKind, string> = {
  NATIONAL: "Nacional",
  BRIDGE: "Puente",
  PERSONAL: "Personal",
};

/** hours string → minutos enteros (null si es inválido). */
function toMinutes(hours: string): number | null {
  const value = Math.round(parseFloat(hours) * 60);
  return isNaN(value) || value <= 0 ? null : value;
}

/** Duración compacta: "5 h" si es exacta, si no "4 h 30 min". */
function durationShort(minutes: number): string {
  if (minutes <= 0) return "0 min";
  return minutes % 60 === 0 ? `${minutes / 60} h` : minutesToHM(minutes);
}

/** Recorre todas las páginas de un listado paginado. */
async function collectAll<T>(
  page: (pageNum: number) => Promise<Paginated<T>>
): Promise<T[]> {
  const all: T[] = [];
  let pageNum = 1;
  for (;;) {
    const res = await page(pageNum);
    all.push(...res.results);
    if (!res.next) break;
    pageNum += 1;
  }
  return all;
}

/** Descarga un CSV (separador ';', BOM para Excel). */
function downloadCsv(filename: string, rows: (string | number)[][]) {
  const csv = rows
    .map((row) =>
      row
        .map((cell) => {
          const s = String(cell ?? "");
          return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
        })
        .join(";")
    )
    .join("\n");
  const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function SettingsPage() {
  const toast = useToast();

  // ---------------------------------------------------------- Apariencia
  const [theme, setTheme] = useState<ThemePreference>(() => getTheme());
  const changeTheme = (pref: ThemePreference) => {
    setTheme(pref);
    applyTheme(pref);
  };

  // --------------------------------------------------------- Estado base
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{
    kind: "success" | "error";
    message: string;
  } | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  // ------------------------------------------------------------- Horas
  const [weeklyHours, setWeeklyHours] = useState("");
  const [applyFromWeekly, setApplyFromWeekly] = useState<"this_week" | "next_week">(
    "this_week"
  );
  const [maxDailyHours, setMaxDailyHours] = useState("");
  const [minBlock, setMinBlock] = useState("");
  const [forgottenMinutes, setForgottenMinutes] = useState("");
  const [carryOver, setCarryOver] = useState(false);
  const [templates, setTemplates] = useState<WeekdayTemplate[]>([]);

  // ------------------------------------------------------------- Viajes
  const [tripLimit, setTripLimit] = useState("");
  const [applyFromTrips, setApplyFromTrips] = useState<
    "this_month" | "next_month"
  >("this_month");
  const [fare, setFare] = useState("");
  const [salary, setSalary] = useState("");
  const [hideAmounts, setHideAmounts] = useState(false);

  // ----------------------------------------------------------- Feriados
  const currentYear = parseInt(todayISO().slice(0, 4), 10);
  const [holidayYear, setHolidayYear] = useState(currentYear);
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [holidayBusy, setHolidayBusy] = useState(false);
  const [editingHoliday, setEditingHoliday] = useState<Holiday | "new" | null>(
    null
  );

  const applyConfig = (cfg: AppSettings) => {
    setSettings(cfg);
    setWeeklyHours(String(cfg.weekly_target_minutes / 60));
    setMaxDailyHours(String(cfg.max_daily_minutes / 60));
    setMinBlock(String(cfg.min_block_minutes));
    setForgottenMinutes(String(cfg.forgotten_checkout_threshold_minutes));
    setTemplates(cfg.weekday_templates);
    setTripLimit(String(cfg.monthly_trip_limit));
    setFare(cfg.current_fare);
    setSalary(cfg.monthly_salary ?? "");
    setCarryOver(cfg.carry_over_deficit);
    setHideAmounts(cfg.hide_amounts);
  };

  const load = useCallback(async () => {
    try {
      applyConfig(await api.getSettings());
      setError("");
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "No se pudo cargar la configuración."
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHolidays = useCallback(async () => {
    try {
      const list = await api.listHolidays(holidayYear);
      setHolidays(list.results);
    } catch (e) {
      setNotice({
        kind: "error",
        message:
          e instanceof ApiError ? e.message : "No se pudieron cargar los feriados.",
      });
    }
  }, [holidayYear]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    loadHolidays();
  }, [loadHolidays]);

  const updateTemplate = (weekday: number, patch: Partial<WeekdayTemplate>) =>
    setTemplates((prev) =>
      prev.map((t) => (t.weekday === weekday ? { ...t, ...patch } : t))
    );

  // ------------------------- Duración diaria resultante (en vivo) -----
  const preferredCount = useMemo(
    () => templates.filter((t) => t.kind === "PREFERRED").length,
    [templates]
  );
  const weeklyMinutes = toMinutes(weeklyHours) ?? 0;
  const derivedDaily =
    preferredCount > 0 ? Math.floor(weeklyMinutes / preferredCount) : 0;

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    const weekly = toMinutes(weeklyHours);
    const maxDaily = toMinutes(maxDailyHours);
    const block = parseInt(minBlock, 10);
    const trips = parseInt(tripLimit, 10);
    const forgotten = parseInt(forgottenMinutes, 10);
    if (!weekly) errs.weekly = "Ingresá un objetivo mayor a cero.";
    if (!maxDaily) errs.maxDaily = "Ingresá un máximo diario mayor a cero.";
    if (isNaN(block) || block <= 0)
      errs.minBlock = "El bloque mínimo debe ser al menos 1 minuto.";
    if (isNaN(trips) || trips <= 0)
      errs.tripLimit = "Debe haber al menos 1 viaje por mes.";
    if (isNaN(forgotten) || forgotten < 0)
      errs.forgotten = "Ingresá los minutos (0 o más).";
    if (weekly && maxDaily && preferredCount > 0 && derivedDaily > maxDaily) {
      errs.maxDaily = `No alcanza el máximo diario: se necesitan ${durationShort(
        derivedDaily
      )} por día en ${preferredCount} días (máximo ${durationShort(maxDaily)}).`;
    }
    setFieldErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const save = async () => {
    if (!settings || !validate()) return;
    setBusy(true);
    try {
      const base: SettingsPatch = {
        max_daily_minutes: toMinutes(maxDailyHours) ?? undefined,
        min_block_minutes: parseInt(minBlock, 10),
        carry_over_deficit: carryOver,
        forgotten_checkout_threshold_minutes: parseInt(forgottenMinutes, 10),
        hide_amounts: hideAmounts,
        current_fare: fare || "0",
        monthly_salary: salary ? salary : null,
        weekday_templates: templates.map((t) => ({
          weekday: t.weekday,
          kind: t.kind,
          start_time: t.start_time,
          default_minutes: t.default_minutes,
        })),
      };
      const weekly = toMinutes(weeklyHours) ?? 0;
      const trips = parseInt(tripLimit, 10);
      let updated = await api.updateSettings(base);
      if (weekly !== settings.weekly_target_minutes) {
        updated = await api.updateSettings({
          weekly_target_minutes: weekly,
          apply_from: applyFromWeekly,
        });
      }
      if (trips !== settings.monthly_trip_limit) {
        updated = await api.updateSettings({
          monthly_trip_limit: trips,
          apply_from: applyFromTrips,
        });
      }
      applyConfig(updated);
      setFieldErrors({});
      setNotice(null);
      toast({ kind: "success", message: "Guardado" });
    } catch (e) {
      const msg =
        e instanceof ApiError ? e.message : "No se pudo guardar.";
      // 422 del backend (p. ej. el objetivo no entra en el máximo diario).
      if (e instanceof ApiError && e.status === 422) {
        setFieldErrors((prev) => ({ ...prev, maxDaily: msg }));
      }
      setNotice({ kind: "error", message: msg });
    } finally {
      setBusy(false);
    }
  };

  // --------------------------------------------------------- Exportación
  const exportTravels = async () => {
    try {
      const all = await collectAll((page) =>
        api.listTravels({ page: String(page) })
      );
      downloadCsv(`viajes-${todayISO()}.csv`, [
        ["fecha", "hora", "direccion", "importe", "tipo", "estado"],
        ...all.map((t) => [
          fmtDate(t.occurred_at),
          t.occurred_at.slice(11, 16),
          t.direction === "IDA" ? "Ida" : "Vuelta",
          t.amount,
          t.payment_type === "COMPANY" ? "Empresa" : "Personal",
          t.status === "ACTIVE" ? "Activo" : "Anulado",
        ]),
      ]);
      toast({ kind: "success", message: "Viajes exportados." });
    } catch (e) {
      toast({
        kind: "error",
        message: e instanceof ApiError ? e.message : "No se pudieron exportar los viajes.",
      });
    }
  };

  const exportSessions = async () => {
    try {
      const all = await collectAll((page) => api.listSessions({ page: String(page) }));
      downloadCsv(`jornadas-${todayISO()}.csv`, [
        ["fecha", "entrada", "salida", "minutos", "estado"],
        ...all.map((s) => [
          fmtDate(s.work_date),
          s.start_at.slice(11, 16),
          s.end_at ? s.end_at.slice(11, 16) : "",
          s.worked_minutes,
          s.status === "IN_PROGRESS"
            ? "En curso"
            : s.status === "PENDING"
            ? "Pendiente"
            : "Completada",
        ]),
      ]);
      toast({ kind: "success", message: "Jornadas exportadas." });
    } catch (e) {
      toast({
        kind: "error",
        message: e instanceof ApiError ? e.message : "No se pudieron exportar las jornadas.",
      });
    }
  };

  if (loading) {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }
  if (error && !settings) return <ErrorState message={error} onRetry={load} />;
  if (!settings) return null;

  return (
    <div className="max-w-2xl space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Ajustes</h1>
        <p className="text-sm text-muted">
          Apariencia, horas, viajes, feriados y datos.
        </p>
      </div>

      {notice ? (
        <Notice
          kind={notice.kind}
          message={notice.message}
          onClose={() => setNotice(null)}
        />
      ) : null}

      {/* ---------------------------------------------------1. Apariencia */}
      <section className="card space-y-3">
        <h2 className="text-sm font-semibold">Apariencia</h2>
        <SegmentedControl
          value={theme}
          options={[
            { value: "light", label: "Claro" },
            { value: "dark", label: "Oscuro" },
            { value: "system", label: "Sistema" },
          ]}
          onChange={changeTheme}
          ariaLabel="Tema de la interfaz"
        />
        <p className="text-xs text-muted">
          «Sistema» sigue la preferencia del dispositivo; se guarda en este
          navegador.
        </p>
      </section>

      {/* --------------------------------------------------------2. Horas */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold">Horas</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="weekly">
              Objetivo semanal (horas)
            </label>
            <input
              id="weekly"
              type="number"
              step="0.5"
              min="0.5"
              className="input"
              value={weeklyHours}
              onChange={(e) => setWeeklyHours(e.target.value)}
              aria-invalid={!!fieldErrors.weekly}
            />
            {fieldErrors.weekly ? (
              <p className="mt-1 text-xs text-error-strong">{fieldErrors.weekly}</p>
            ) : (
              <p className="mt-1 text-xs text-muted">
                {settings.weekly_target_effective_from
                  ? `Vigente desde el ${settings.weekly_target_effective_from}.`
                  : "Sin valor cargado."}
              </p>
            )}
          </div>
          <div>
            <label className="label" htmlFor="apply-weekly">
              Aplicar desde
            </label>
            <select
              id="apply-weekly"
              className="input"
              value={applyFromWeekly}
              onChange={(e) =>
                setApplyFromWeekly(e.target.value as "this_week" | "next_week")
              }
            >
              <option value="this_week">Esta semana</option>
              <option value="next_week">La próxima semana</option>
            </select>
            <p className="mt-1 text-xs text-muted">
              Se guarda como valor nuevo; las semanas anteriores no cambian.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="max-daily">
              Máximo por día (horas)
            </label>
            <input
              id="max-daily"
              type="number"
              step="0.5"
              min="0.5"
              className="input"
              value={maxDailyHours}
              onChange={(e) => setMaxDailyHours(e.target.value)}
              aria-invalid={!!fieldErrors.maxDaily}
            />
            {fieldErrors.maxDaily ? (
              <p className="mt-1 text-xs text-error-strong">{fieldErrors.maxDaily}</p>
            ) : null}
          </div>
          <div>
            <label className="label" htmlFor="min-block">
              Bloque mínimo (minutos)
            </label>
            <input
              id="min-block"
              type="number"
              min="1"
              className="input"
              value={minBlock}
              onChange={(e) => setMinBlock(e.target.value)}
              aria-invalid={!!fieldErrors.minBlock}
            />
            {fieldErrors.minBlock ? (
              <p className="mt-1 text-xs text-error-strong">{fieldErrors.minBlock}</p>
            ) : null}
          </div>
        </div>

        <label
          className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm"
          htmlFor="carry-over"
        >
          <input
            id="carry-over"
            type="checkbox"
            checked={carryOver}
            onChange={(e) => setCarryOver(e.target.checked)}
            className="h-4 w-4"
          />
          Arrastrar horas pendientes de semanas anteriores
        </label>

        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="forgotten">Preguntar la salida si pasaron</label>
          <input
            id="forgotten"
            type="number"
            min="0"
            className="input w-24"
            value={forgottenMinutes}
            onChange={(e) => setForgottenMinutes(e.target.value)}
            aria-invalid={!!fieldErrors.forgotten}
          />
          <span className="text-muted">minutos de lo planificado</span>
          {fieldErrors.forgotten ? (
            <span className="w-full text-xs text-error-strong">
              {fieldErrors.forgotten}
            </span>
          ) : null}
        </div>

        {/* Plantilla semanal */}
        <div className="space-y-2 border-t border-line pt-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">Plantilla semanal</h3>
            <p className="text-sm text-muted">
              {preferredCount > 0 && derivedDaily > 0 ? (
                <>
                  <span className="font-medium text-fg">
                    {durationShort(derivedDaily)}
                  </span>{" "}
                  por día en {preferredCount} día{preferredCount === 1 ? "" : "s"}
                </>
              ) : (
                "Sin días preferidos"
              )}
            </p>
          </div>
          <p className="text-xs text-muted">
            Duración vacía = automática (objetivo semanal / días preferidos).
            Los días libres nunca se planifican.
          </p>
          <div className="space-y-2">
            {templates.map((t) => (
              <div
                key={t.weekday}
                className="grid grid-cols-2 items-end gap-2 rounded-xl border border-line p-2 sm:grid-cols-4"
              >
                <div>
                  <p className="text-sm font-medium">
                    {weekdayNameFromIndex(t.weekday)}
                  </p>
                  <p className="text-xs text-muted">
                    {t.resolved_minutes !== null
                      ? `Duración: ${durationShort(t.resolved_minutes)}`
                      : "Sin jornada"}
                  </p>
                </div>
                <div>
                  <label className="label" htmlFor={`kind-${t.weekday}`}>
                    Tipo
                  </label>
                  <select
                    id={`kind-${t.weekday}`}
                    className="input"
                    value={t.kind}
                    onChange={(e) =>
                      updateTemplate(t.weekday, {
                        kind: e.target.value as WeekdayKind,
                      })
                    }
                  >
                    {(
                      ["PREFERRED", "RESERVE", "OFF"] as WeekdayKind[]
                    ).map((kind) => (
                      <option key={kind} value={kind}>
                        {KIND_LABEL[kind]}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor={`start-${t.weekday}`}>
                    Inicio
                  </label>
                  <input
                    id={`start-${t.weekday}`}
                    type="time"
                    className="input"
                    value={t.start_time.slice(0, 5)}
                    onChange={(e) =>
                      updateTemplate(t.weekday, {
                        start_time: `${e.target.value}:00`,
                      })
                    }
                    disabled={t.kind === "OFF"}
                  />
                </div>
                <div>
                  <label className="label" htmlFor={`minutes-${t.weekday}`}>
                    Duración (min)
                  </label>
                  <input
                    id={`minutes-${t.weekday}`}
                    type="number"
                    min="1"
                    className="input"
                    placeholder={
                      t.resolved_minutes !== null
                        ? `${t.resolved_minutes} (auto)`
                        : "—"
                    }
                    value={t.default_minutes ?? ""}
                    onChange={(e) =>
                      updateTemplate(t.weekday, {
                        default_minutes: e.target.value
                          ? parseInt(e.target.value, 10)
                          : null,
                      })
                    }
                    disabled={t.kind === "OFF"}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------3. Viajes */}
      <section className="card space-y-4">
        <h2 className="text-sm font-semibold">Viajes</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="fare">
              Precio del boleto (ARS)
            </label>
            <input
              id="fare"
              type="number"
              step="0.01"
              min="0"
              className="input"
              value={fare}
              onChange={(e) => setFare(e.target.value)}
            />
            <p className="mt-1 text-xs text-muted">
              Solo aplica a viajes nuevos: los ya registrados conservan su
              importe.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="limit">
              Viajes mensuales de la empresa
            </label>
            <input
              id="limit"
              type="number"
              min="1"
              className="input"
              value={tripLimit}
              onChange={(e) => setTripLimit(e.target.value)}
              aria-invalid={!!fieldErrors.tripLimit}
            />
            <select
              className="input mt-2"
              aria-label="Aplicar desde"
              value={applyFromTrips}
              onChange={(e) =>
                setApplyFromTrips(e.target.value as "this_month" | "next_month")
              }
            >
              <option value="this_month">Este mes</option>
              <option value="next_month">El próximo mes</option>
            </select>
            <p className="mt-1 text-xs text-muted">
              {settings.monthly_trip_limit_effective_from
                ? `Vigente desde el ${settings.monthly_trip_limit_effective_from}.`
                : "Sin valor cargado."}
            </p>
            {fieldErrors.tripLimit ? (
              <p className="mt-1 text-xs text-error-strong">{fieldErrors.tripLimit}</p>
            ) : null}
          </div>
          <div>
            <label className="label" htmlFor="salary">
              Sueldo mensual (ARS, opcional)
            </label>
            <input
              id="salary"
              type="number"
              step="0.01"
              min="0"
              className="input"
              value={salary}
              onChange={(e) => setSalary(e.target.value)}
            />
          </div>
        </div>
        <label
          className="flex min-h-[44px] cursor-pointer items-center gap-2 text-sm"
          htmlFor="hide-amounts"
        >
          <input
            id="hide-amounts"
            type="checkbox"
            checked={hideAmounts}
            onChange={(e) => setHideAmounts(e.target.checked)}
            className="h-4 w-4"
          />
          Ocultar montos
        </label>
      </section>

      {/* --------------------------------------------4. Feriados del año */}
      <section className="card space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Feriados y días no laborables</h2>
          <input
            type="number"
            className="input w-28"
            value={holidayYear}
            min={currentYear - 5}
            max={currentYear + 5}
            onChange={(e) =>
              setHolidayYear(parseInt(e.target.value, 10) || currentYear)
            }
            aria-label="Año"
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            className="min-h-[44px]"
            onClick={() => setEditingHoliday("new")}
          >
            <IconPlus className="h-4 w-4" />
            Agregar
          </Button>
          <Button
            variant="ghost"
            className="min-h-[44px]"
            loading={holidayBusy}
            onClick={async () => {
              setHolidayBusy(true);
              try {
                const result = await api.importHolidays(holidayYear);
                toast({
                  kind: "success",
                  message: `${result.year}: ${result.count} feriados guardados.`,
                });
                await loadHolidays();
              } catch (e) {
                toast({
                  kind: "error",
                  message:
                    e instanceof ApiError
                      ? e.message
                      : "No se pudieron importar los feriados.",
                });
              } finally {
                setHolidayBusy(false);
              }
            }}
          >
            Importar feriados del año
          </Button>
        </div>
        {holidays.length === 0 ? (
          <p className="text-sm text-muted">
            Sin feriados cargados para {holidayYear}.
          </p>
        ) : (
          <ul className="divide-y divide-line">
            {holidays.map((h) => (
              <li key={h.id} className="flex items-center gap-3 py-2.5 text-sm">
                <span className="w-20 shrink-0 tabular-nums">{fmtDate(h.date)}</span>
                <span className="min-w-0 flex-1 truncate">{h.name}</span>
                <Badge
                  variant={
                    h.kind === "PERSONAL"
                      ? "accent"
                      : h.kind === "BRIDGE"
                      ? "warning"
                      : "neutral"
                  }
                >
                  {HOLIDAY_KIND_LABEL[h.kind]}
                </Badge>
                <button
                  className="rounded-lg p-2 text-muted hover:bg-surface-2"
                  onClick={() => setEditingHoliday(h)}
                  aria-label={`Editar ${h.name}`}
                >
                  <IconEdit className="h-4 w-4" />
                </button>
                <button
                  className="rounded-lg p-2 text-error-strong hover:bg-error-soft"
                  onClick={async () => {
                    if (!window.confirm(`¿Eliminar «${h.name}»?`)) return;
                    try {
                      await api.deleteHoliday(h.id);
                      toast({ kind: "success", message: "Feriado eliminado." });
                      await loadHolidays();
                    } catch (e) {
                      toast({
                        kind: "error",
                        message:
                          e instanceof ApiError
                            ? e.message
                            : "No se pudo eliminar.",
                      });
                    }
                  }}
                  aria-label={`Eliminar ${h.name}`}
                >
                  <IconTrash className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* -------------------------------------------------------5. Datos */}
      <section className="card space-y-3">
        <h2 className="text-sm font-semibold">Datos</h2>
        <p className="text-xs text-muted">
          Exporta todo el historial en CSV (separador «;», listo para Excel).
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            variant="secondary"
            className="min-h-[44px]"
            onClick={exportTravels}
          >
            <IconDownload className="h-4 w-4" />
            Exportar viajes
          </Button>
          <Button
            variant="secondary"
            className="min-h-[44px]"
            onClick={exportSessions}
          >
            <IconDownload className="h-4 w-4" />
            Exportar jornadas
          </Button>
        </div>
        <dl className="space-y-1 border-t border-line pt-3 text-sm">
          <div className="flex justify-between">
            <dt className="text-muted">Zona horaria</dt>
            <dd className="font-medium">{settings.timezone}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted">Formato</dt>
            <dd className="font-medium">DD/MM · 24 h · ARS</dd>
          </div>
        </dl>
        <Link to="/" className="text-sm text-accent-strong">
          Volver al inicio
        </Link>
      </section>

      <div className="flex items-center gap-3">
        <Button onClick={save} loading={busy}>
          Guardar
        </Button>
        <p className="text-xs text-muted">
          Objetivos y cupo se guardan con vigencia (no cambian el pasado).
        </p>
      </div>

      <HolidayModal
        open={editingHoliday !== null}
        holiday={editingHoliday === "new" ? null : editingHoliday}
        onClose={() => setEditingHoliday(null)}
        onSaved={(msg) => {
          setEditingHoliday(null);
          toast({ kind: "success", message: msg });
          loadHolidays();
        }}
        onError={(msg) => toast({ kind: "error", message: msg })}
      />
    </div>
  );
}

/** Alta/edición de un feriado (Modal del sistema). */
function HolidayModal({
  open,
  holiday,
  onClose,
  onSaved,
  onError,
}: {
  open: boolean;
  holiday: Holiday | null;
  onClose: () => void;
  onSaved: (msg: string) => void;
  onError: (msg: string) => void;
}) {
  const [date, setDate] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<HolidayKind>("NATIONAL");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setDate(holiday?.date ?? "");
    setName(holiday?.name ?? "");
    setKind(holiday?.kind ?? "NATIONAL");
    setError("");
  }, [open, holiday]);

  const submit = async () => {
    if (!date || !name.trim()) {
      setError("Ingresá la fecha y el nombre.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (holiday) {
        await api.updateHoliday(holiday.id, { date, name: name.trim(), kind });
        onSaved("Feriado actualizado.");
      } else {
        await api.createHoliday({ date, name: name.trim(), kind });
        onSaved("Feriado agregado.");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "No se pudo guardar.");
      onError(e instanceof ApiError ? e.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal open={open} title={holiday ? "Editar feriado" : "Nuevo feriado"} onClose={onClose}>
      <div className="space-y-3">
        <div>
          <label className="label" htmlFor="hol-date">
            Fecha
          </label>
          <input
            id="hol-date"
            type="date"
            className="input"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </div>
        <div>
          <label className="label" htmlFor="hol-name">
            Nombre
          </label>
          <input
            id="hol-name"
            type="text"
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Ej: Feriado puente"
          />
        </div>
        <div>
          <label className="label" htmlFor="hol-kind">
            Tipo
          </label>
          <select
            id="hol-kind"
            className="input"
            value={kind}
            onChange={(e) => setKind(e.target.value as HolidayKind)}
          >
            <option value="NATIONAL">Nacional</option>
            <option value="BRIDGE">Puente</option>
            <option value="PERSONAL">Personal</option>
          </select>
        </div>
        {error ? <Notice kind="error" message={error} /> : null}
        <Button className="w-full" onClick={submit} loading={busy}>
          Guardar
        </Button>
      </div>
    </Modal>
  );
}

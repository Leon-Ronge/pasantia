// Formateo según la especificación: fechas DD/MM/AAAA, hora 24 h,
// moneda ARS y zona horaria America/Argentina/Cordoba.

export const TZ = "America/Argentina/Cordoba";

/** Moneda pesos argentinos: $ 1.234,56 */
export function fmtARS(value: string | number): string {
  const n = typeof value === "string" ? parseFloat(value) : value;
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: "ARS",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(isNaN(n) ? 0 : n);
}

/** Fecha ISO → DD/MM/AAAA (siempre en la zona horaria configurada). */
export function fmtDate(iso: string): string {
  if (!iso) return "";
  const date = iso.length === 10 ? parseLocalDate(iso) : new Date(iso);
  return new Intl.DateTimeFormat("es-AR", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

/** Fecha ISO → DD/MM (zona Córdoba), sin año: para la cabecera. */
export function fmtDateShort(iso: string): string {
  if (!iso) return "";
  const date = iso.length === 10 ? parseLocalDate(iso) : new Date(iso);
  return new Intl.DateTimeFormat("es-AR", {
    timeZone: TZ,
    day: "2-digit",
    month: "2-digit",
  }).format(date);
}

/** Fecha ISO con hora → HH:MM (24 h, zona Córdoba). */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return new Intl.DateTimeFormat("es-AR", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

/** 'YYYY-MM-DD' (fecha civil) → Date anclado al mediodía en Córdoba. */
export function parseLocalDate(isoDate: string): Date {
  return new Date(`${isoDate}T12:00:00-03:00`);
}

/** Hoy (YYYY-MM-DD) según la zona horaria configurada. */
export function todayISO(): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** 'YYYY-MM' del mes en curso (Córdoba). */
export function currentMonth(): string {
  return todayISO().slice(0, 7);
}

/** Minutos → «5 h 04 min», «3 h 20 min» o «45 min». */
export function minutesToHM(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  const h = Math.floor(m / 60);
  const rest = m % 60;
  if (h === 0) return `${rest} min`;
  return `${h} h ${String(rest).padStart(2, "0")} min`;
}

/** Minutos → «HH:MM» (duración larga tipo 12:30). */
export function minutesToClock(minutes: number): string {
  const m = Math.max(0, Math.round(minutes));
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return `${h}:${String(rest).padStart(2, "0")}`;
}

/** Lunes de la semana que contiene la fecha dada. */
export function mondayOf(isoDate: string): string {
  const d = parseLocalDate(isoDate);
  const day = d.getUTCDay(); // en mediodía UTC-3 sigue siendo ese día
  const offsetToMonday = (day + 6) % 7;
  const monday = new Date(d.getTime() - offsetToMonday * 86400000);
  return toISODate(monday);
}

/** Date → 'YYYY-MM-DD' (componentes de la fecha tal cual, sin conversión). */
export function toISODate(d: Date): string {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Suma días calendario a una fecha 'YYYY-MM-DD'. */
export function addDays(isoDate: string, days: number): string {
  const d = parseLocalDate(isoDate);
  return toISODate(new Date(d.getTime() + days * 86400000));
}

/** Suma minutos a un instante ISO; devuelve Date. */
export function addMinutes(iso: string, minutes: number): Date {
  return new Date(new Date(iso).getTime() + minutes * 60000);
}

/** Días de la semana para un lunes dado (7 fechas). */
export function weekDays(monday: string): string[] {
  return Array.from({ length: 7 }, (_, i) => addDays(monday, i));
}

const WEEKDAY_LONG = [
  "Lunes",
  "Martes",
  "Miércoles",
  "Jueves",
  "Viernes",
  "Sábado",
  "Domingo",
];
const WEEKDAY_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const MONTH_LONG = [
  "Enero",
  "Febrero",
  "Marzo",
  "Abril",
  "Mayo",
  "Junio",
  "Julio",
  "Agosto",
  "Septiembre",
  "Octubre",
  "Noviembre",
  "Diciembre",
];

/** Índice 0..6 (0 = lunes) de una fecha 'YYYY-MM-DD'. */
export function weekdayIndexOf(isoDate: string): number {
  const d = parseLocalDate(isoDate);
  return (d.getUTCDay() + 6) % 7;
}

/** Índice 0..6 (0 = lunes) del día de hoy (zona Córdoba). */
export function todayWeekdayIndex(): number {
  return weekdayIndexOf(todayISO());
}

/** 'YYYY-MM-DD' → nombre completo del día (Lunes, Martes…). */
export function weekdayLong(isoDate: string): string {
  const d = parseLocalDate(isoDate);
  const idx = (d.getUTCDay() + 6) % 7;
  return WEEKDAY_LONG[idx];
}

/** Índice 0..6 (0 = lunes) → nombre completo del día. */
export function weekdayNameFromIndex(index: number): string {
  return WEEKDAY_LONG[((index % 7) + 7) % 7];
}

/** Índice 0..6 (0 = lunes) → día corto (Lun, Mar…). */
export function weekdayShortFromIndex(index: number): string {
  return WEEKDAY_SHORT[((index % 7) + 7) % 7];
}

/** 'YYYY-MM-DD' → día corto (Lun, Mar…). */
export function weekdayShort(isoDate: string): string {
  const d = parseLocalDate(isoDate);
  const idx = (d.getUTCDay() + 6) % 7;
  return WEEKDAY_SHORT[idx];
}

/** 'YYYY-MM' → «Octubre 2026». */
export function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  const idx = parseInt(m, 10) - 1;
  if (isNaN(idx) || idx < 0 || idx > 11) return ym;
  return `${MONTH_LONG[idx]} ${y}`;
}

/** 'YYYY-MM-DD' → «lunes 26/10». */
export function longDate(isoDate: string): string {
  return `${weekdayLong(isoDate).toLowerCase()} ${fmtDate(isoDate)}`;
}

/** Date actual → 'YYYY-MM-DDTHH:mm' para input datetime-local. */
export function toDatetimeLocal(iso: string): string {
  const date = new Date(iso);
  const dateStr = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
  const timeStr = new Intl.DateTimeFormat("en-GB", {
    timeZone: TZ,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
  return `${dateStr}T${timeStr}`;
}

/**
 * 'YYYY-MM-DDTHH:mm' (escrito por el usuario como hora local de Córdoba)
 * → ISO con offset -03:00 para enviarlo al backend.
 */
export function fromDatetimeLocal(value: string): string {
  return `${value}:00-03:00`;
}

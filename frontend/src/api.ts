// Cliente HTTP para la API REST del backend.
// En desarrollo usa el proxy de Vite; en producción, nginx (ver README).

import type {
  AppSettings,
  DashboardData,
  Direction,
  Holiday,
  HolidayKind,
  MonthComparison,
  MonthlyHistoryItem,
  MonthlySummary,
  Paginated,
  SettingsPatch,
  TodayState,
  TravelRecord,
  TravelSummary,
  WeekView,
  WorkPlan,
  WorkSession,
} from "./types";

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(message: string, status: number, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/** Convierte las respuestas de error de DRF en un mensaje legible. */
function extractMessage(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const obj = body as Record<string, unknown>;
    if (typeof obj.detail === "string") return obj.detail;
    const parts: string[] = [];
    for (const [key, value] of Object.entries(obj)) {
      if (key === "non_field_errors" && Array.isArray(value)) {
        parts.push(...value.map(String));
      } else if (Array.isArray(value)) {
        parts.push(`${key}: ${value.map(String).join(" ")}`);
      } else if (typeof value === "string") {
        parts.push(value);
      }
    }
    if (parts.length) return parts.join(" · ");
  }
  return `Error ${status}`;
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(extractMessage(body, res.status), res.status, body);
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

const json = (data: unknown): string => JSON.stringify(data);

export const api = {
  // ---------------------------------------------------------------- Dashboard
  dashboard: () => request<DashboardData>("/api/dashboard/"),

  // --------------------------------------------------------------- Ajustes
  getSettings: () => request<AppSettings>("/api/settings/"),
  updateSettings: (patch: SettingsPatch) =>
    request<AppSettings>("/api/settings/", {
      method: "PATCH",
      body: json(patch),
    }),

  // ------------------------------------------------------------- Feriados
  listHolidays: (year: number) =>
    request<Paginated<Holiday>>(
      `/api/holidays/?${new URLSearchParams({ page_size: "100", year: String(year) })}`
    ),
  createHoliday: (data: { date: string; name: string; kind: HolidayKind }) =>
    request<Holiday>("/api/holidays/", { method: "POST", body: json(data) }),
  updateHoliday: (
    id: number,
    patch: Partial<Pick<Holiday, "date" | "name" | "kind">>
  ) =>
    request<Holiday>(`/api/holidays/${id}/`, {
      method: "PATCH",
      body: json(patch),
    }),
  deleteHoliday: (id: number) =>
    request<void>(`/api/holidays/${id}/`, { method: "DELETE" }),
  /** Importa el año desde la API pública (respeta los PERSONAL). */
  importHolidays: (year: number) =>
    request<{ year: number; count: number }>("/api/holidays/import/", {
      method: "POST",
      body: json({ year }),
    }),

  // ------------------------------------------------------------- Transporte
  listTravels: (params: Record<string, string> = {}) =>
    request<Paginated<TravelRecord>>(
      `/api/travels/?${new URLSearchParams({ page_size: "100", ...params })}`
    ),
  /**
   * Alta de viaje. Todos los campos son opcionales (defaults del backend:
   * ahora, tarifa vigente y dirección sugerida). Si `force` es true se
   * salta la validación de doble toque (409).
   */
  createTravel: (
    data: {
      occurred_at?: string;
      amount?: string;
      direction?: Direction;
    } = {},
    force = false
  ) =>
    request<TravelRecord>(
      `/api/travels/${force ? "?force=true" : ""}`,
      { method: "POST", body: json(data) }
    ),
  updateTravel: (id: number, patch: Partial<TravelRecord>) =>
    request<TravelRecord>(`/api/travels/${id}/`, {
      method: "PATCH",
      body: json(patch),
    }),
  /** Dirección sugerida para el próximo viaje (IDA | VUELTA). */
  nextDirection: () =>
    request<{ direction: Direction }>("/api/travels/next-direction/"),
  travelSummary: (month?: string) =>
    request<TravelSummary>(
      `/api/travels/summary/${month ? `?month=${month}` : ""}`
    ),
  /** Historial mensual: idas/vueltas, company/personal, importes y cupo. */
  travelHistory: (months = 6) =>
    request<MonthlyHistoryItem[]>(
      `/api/travels/monthly-history/?months=${months}`
    ),
  travelComparison: (months = 6) =>
    request<MonthComparison[]>(`/api/travels/monthly-comparison/?months=${months}`),

  // ------------------------------------------------------------------ Horas
  /** Estado de hoy: entrada, salida prevista, restantes y confirmaciones. */
  today: () => request<TodayState>("/api/today/"),
  currentSession: () =>
    request<{ session: WorkSession | null }>("/api/work-sessions/current/"),
  /** Abrir jornada (hora del servidor por defecto; start_at opcional). */
  checkIn: (data: { start_at?: string; notes?: string } = {}) =>
    request<WorkSession>("/api/work-sessions/check-in/", {
      method: "POST",
      body: json(data),
    }),
  /** Cerrar la jornada abierta (end_at opcional: ahora del servidor). */
  checkOut: (data: { end_at?: string; confirm?: boolean } = {}) =>
    request<WorkSession>("/api/work-sessions/check-out/", {
      method: "POST",
      body: json(data),
    }),
  /** Cerrar una jornada específica (la de la confirmación olvidada). */
  checkOutById: (
    id: number,
    data: { end_at?: string; confirm?: boolean } = {}
  ) =>
    request<WorkSession>(`/api/work-sessions/${id}/check-out/`, {
      method: "POST",
      body: json(data),
    }),
  /** «Sigo trabajando»: posterga la salida prevista 30 minutos. */
  snooze: (id: number) =>
    request<WorkSession>(`/api/work-sessions/${id}/snooze/`, {
      method: "POST",
      body: json({}),
    }),
  listSessions: (params: Record<string, string> = {}) =>
    request<Paginated<WorkSession>>(
      `/api/work-sessions/?${new URLSearchParams({ page_size: "100", ...params })}`
    ),
  /** Corrección manual de una jornada. */
  updateSession: (
    id: number,
    patch: { start_at?: string; end_at?: string | null; notes?: string }
  ) =>
    request<WorkSession>(`/api/work-sessions/${id}/`, {
      method: "PATCH",
      body: json(patch),
    }),
  /** Vista semanal unificada (horas + plan). date: cualquier día de la semana. */
  week: (date?: string) =>
    request<WeekView>(`/api/week/${date ? `?date=${date}` : ""}`),
  /** Horas por semana y total del mes. */
  hoursMonthlySummary: (month?: string) =>
    request<MonthlySummary>(
      `/api/hours/monthly-summary/${month ? `?month=${month}` : ""}`
    ),

  // ------------------------------------------------------------ Planificador
  /** Excepciones manuales de la semana (?week_start=YYYY-MM-DD). */
  listPlans: (weekStart?: string) =>
    request<Paginated<WorkPlan>>(
      `/api/work-plans/${
        weekStart
          ? `?${new URLSearchParams({ page_size: "100", week_start: weekStart })}`
          : ""
      }`
    ),
  /**
   * Upsert por FECHA: crea o edita la excepción manual de ese día
   * (horario manual, bloqueo, día no disponible).
   */
  savePlan: (
    workDate: string,
    patch: Partial<
      Pick<WorkPlan, "planned_start" | "planned_minutes" | "is_locked" | "is_available" | "notes">
    >
  ) =>
    request<WorkPlan>(`/api/work-plans/${workDate}/`, {
      method: "PATCH",
      body: json(patch),
    }),
  /** Vuelve a automático el día (elimina la excepción manual). */
  deletePlan: (workDate: string) =>
    request<void>(`/api/work-plans/${workDate}/`, { method: "DELETE" }),
  /** Limpia todas las excepciones manuales de la semana. */
  resetPlans: (weekStart?: string) =>
    request<{ week_start: string; deleted: number }>(
      `/api/work-plans/reset/${weekStart ? `?week=${weekStart}` : ""}`,
      { method: "POST", body: json({}) }
    ),
};

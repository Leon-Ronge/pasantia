// Tipos compartidos entre el frontend y la API (Django REST Framework).

export type PaymentType = "COMPANY" | "PERSONAL";
export type TravelStatus = "ACTIVE" | "VOIDED";
export type Direction = "IDA" | "VUELTA";
export type SessionStatus = "PENDING" | "IN_PROGRESS" | "COMPLETED";

/** Tipos de feriado (tabla Holiday). */
export type HolidayKind = "NATIONAL" | "BRIDGE" | "PERSONAL";

export interface Holiday {
  id: number;
  date: string; // YYYY-MM-DD
  name: string;
  kind: HolidayKind;
  created_at: string;
  updated_at: string;
}

export interface TravelRecord {
  id: number;
  occurred_at: string; // ISO con offset (zona Córdoba)
  direction: Direction;
  amount: string; // decimal exacto como string
  payment_type: PaymentType; // DERIVADO por mes calendario (solo lectura)
  status: TravelStatus;
  created_at: string;
  updated_at: string;
}

export interface TravelSummary {
  month: string;
  used_company: number;
  remaining_company: number; // nunca negativo
  limit: number; // cupo vigente de ese mes
  personal_count: number;
  total_count: number;
  total_value: string;
  company_value: string;
  out_of_pocket_value: string;
  salary_percentage: number | null; // null si no hay sueldo cargado
}

export interface MonthlyHistoryItem {
  month: string; // YYYY-MM
  ida_count: number;
  vuelta_count: number;
  company_count: number;
  personal_count: number;
  total_value: string;
  out_of_pocket_value: string;
  salary_percentage: number | null;
  limit: number; // cupo vigente de ese mes
}

export interface MonthComparison {
  month: string;
  month_label: string;
  company_count: number;
  company_amount: string;
  personal_count: number;
  personal_amount: string;
}

export interface WorkSession {
  id: number;
  work_date: string;
  start_at: string; // ISO con offset
  end_at: string | null;
  snoozed_until: string | null; // «Sigo trabajando» (+30 min)
  worked_minutes: number;
  elapsed_minutes: number;
  notes: string;
  status: SessionStatus;
  created_at: string;
  updated_at: string;
}

export interface WorkPlan {
  id: number;
  work_date: string;
  planned_start: string; // HH:MM:SS
  planned_minutes: number;
  is_locked: boolean;
  is_available: boolean;
  notes: string;
  created_at: string;
  updated_at: string;
}

/** Confirmación de cierre olvidado (jornada abierta que pide atención). */
export interface CheckoutConfirmation {
  scope: "PREVIOUS_DAY" | "TODAY";
  session_id: number;
  work_date: string;
  started_at: string;
  planned_end: string; // salida prevista
  suggested_end: string; // cierre sugerido
}

/** Estados posibles de un día en la vista semanal. */
export type DayStatus =
  | "DONE"
  | "TODAY"
  | "PLANNED"
  | "HOLIDAY"
  | "OFF"
  | "MISSED"
  | "PENDING_CONFIRMATION";

/** Estado de hoy para /api/today/. */
export interface TodayState {
  date: string;
  state: "NOT_STARTED" | "IN_PROGRESS" | "DONE";
  start_at: string | null; // entrada REAL (null si no empezó)
  end_at: string | null; // salida prevista
  worked_minutes: number;
  planned_minutes: number | null;
  remaining_minutes: number;
  needs_checkout_confirmation: CheckoutConfirmation | null;
}

/** Día de la vista semanal: real + plan (automático o manual). */
export interface WeekDay {
  date: string;
  weekday: number; // 0 = lunes
  status: DayStatus;
  is_holiday: boolean;
  holiday_name: string | null;
  start_at: string | null; // entrada real o inicio del plan
  end_at: string | null; // salida real o prevista
  worked_minutes: number;
  planned_start: string | null; // "HH:MM"
  planned_minutes: number | null;
  diff_minutes: number; // trabajado − plan
  needs_checkout_confirmation: CheckoutConfirmation | null;
  is_manual: boolean; // excepción manual del usuario
  is_locked: boolean; // excepción manual bloqueada
}

/** Vista semanal unificada: horas + planificador en un solo cálculo. */
export interface WeekView {
  week_start: string;
  week_end: string;
  target_minutes: number;
  carry_over_minutes: number;
  worked_minutes: number;
  remaining_minutes: number;
  blocked_minutes: number; // minutos de días manuales reservados
  unscheduled_minutes: number; // lo que no pudo distribuirse
  needs_checkout_confirmation: CheckoutConfirmation | null;
  projected_end: { date: string; time: string } | null;
  days: WeekDay[];
  today: TodayState;
}

/** Semana dentro del resumen mensual. */
export interface MonthWeek {
  week_start: string;
  week_end: string;
  worked_minutes: number;
  target_minutes: number;
}

/** GET /api/hours/monthly-summary/: horas por semana y total del mes. */
export interface MonthlySummary {
  month: string; // YYYY-MM
  weeks: MonthWeek[];
  total_worked_minutes: number;
  total_target_minutes: number;
}

export type ApplyFrom =
  | "this_week"
  | "next_week"
  | "this_month"
  | "next_month";

export type WeekdayKind = "PREFERRED" | "RESERVE" | "OFF";

export interface WeekdayTemplate {
  weekday: number; // 0 = lunes
  kind: WeekdayKind;
  start_time: string; // HH:MM:SS
  default_minutes: number | null; // null = derivado del objetivo semanal
  resolved_minutes: number | null; // calculado por el backend (null en días OFF)
}

export interface AppSettings {
  id: number;
  max_daily_minutes: number;
  min_block_minutes: number;
  carry_over_deficit: boolean;
  forgotten_checkout_threshold_minutes: number;
  current_fare: string;
  monthly_salary: string | null;
  hide_amounts: boolean;
  timezone: string;
  updated_at: string;
  // Valores con vigencia (SettingValue): el vigente hoy.
  weekly_target_minutes: number;
  weekly_target_effective_from: string | null;
  monthly_trip_limit: number;
  monthly_trip_limit_effective_from: string | null;
  weekday_templates: WeekdayTemplate[];
}

export type WeekdayTemplatePatch = Partial<
  Pick<WeekdayTemplate, "weekday" | "kind" | "start_time" | "default_minutes">
>;

export type SettingsPatch = Partial<{
  max_daily_minutes: number;
  min_block_minutes: number;
  carry_over_deficit: boolean;
  forgotten_checkout_threshold_minutes: number;
  current_fare: string;
  monthly_salary: string | null;
  hide_amounts: boolean;
  timezone: string;
  weekly_target_minutes: number;
  monthly_trip_limit: number;
  weekday_templates: WeekdayTemplatePatch[];
  apply_from: ApplyFrom;
}>;

export interface NextShift {
  date: string;
  planned_start: string; // HH:MM
  planned_minutes: number;
  source: "plan" | "sugerido";
}

export interface DashboardData {
  week_start: string;
  weekly_target_minutes: number;
  worked_minutes: number;
  remaining_minutes: number;
  weekly_delta: number;
  opening_deficit_minutes: number;
  accumulated_deficit_minutes: number;
  closing_deficit_minutes: number;
  deficit_kind: "projected" | "definitive";
  progress_ratio: number;
  open_session: WorkSession | null;
  next_shift: NextShift | null;
  transport: TravelSummary;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

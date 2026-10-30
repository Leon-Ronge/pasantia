# API REST

Base URL: `http://<host>:<puerto>/api/`

## General

- **Sin autenticación**: no hay usuarios, sesiones ni tokens dentro de la
  aplicación; todos los endpoints responden con permisos abiertos. El acceso
  se protege fuera de la app (Tailscale o Basic Auth con Caddy, ver README
  «Proteger el acceso»).
- **Formato**: `Content-Type: application/json` en peticiones y respuestas.
- **Fechas**: `YYYY-MM-DD`.
- **Fecha y hora**: ISO 8601 con offset, p. ej. `2026-10-28T09:15:00-03:00`
  (zona `America/Argentina/Cordoba`).
- **Dinero**: siempre **string decimal** (`"820.00"`), nunca float.
- **Minutos**: enteros. Todas las duraciones y balances se calculan en minutos.
- **Paginación**: los listados devuelven
  `{count, next, previous, results}` con `page` y `page_size` (máx. 100).
- **Errores**: `400` con `{campo: ["mensaje"]}` o `{"detail": "mensaje"}`.

---

## Configuración y Dashboard

### `GET /api/settings/`

Configuración combinada: singleton + valores con vigencia (los vigentes
hoy) + plantillas de los 7 días.

```json
{
  "id": 1,
  "max_daily_minutes": 420,
  "min_block_minutes": 60,
  "carry_over_deficit": false,
  "forgotten_checkout_threshold_minutes": 60,
  "current_fare": "820.00",
  "monthly_salary": null,
  "hide_amounts": false,
  "timezone": "America/Argentina/Cordoba",
  "updated_at": "2026-10-27T22:10:00-03:00",
  "weekly_target_minutes": 1200,
  "weekly_target_effective_from": "2000-01-01",
  "monthly_trip_limit": 20,
  "monthly_trip_limit_effective_from": "2000-01-01",
  "weekday_templates": [
    {"weekday": 0, "kind": "PREFERRED", "start_time": "09:00:00",
     "default_minutes": null, "resolved_minutes": 300}
  ]
}
```

- `weekly_target_minutes` / `monthly_trip_limit`: valor **vigente hoy**. El
  valor vigente de una fecha es la fila de `SettingValue` con el mayor
  `effective_from` ≤ esa fecha.
- `weekday_templates`: 7 filas (`weekday`: `0 = lunes … 6 = domingo`).
  `kind`: `PREFERRED` (prioriza el planificador), `RESERVE` (de relleno) u
  `OFF` (nunca se planifica). `default_minutes: null` significa «objetivo
  semanal vigente / cantidad de días PREFERRED»; el backend lo expone
  resuelto en `resolved_minutes` (`null` en días OFF).

### `PATCH /api/settings/`

Actualiza parcialmente el singleton, los valores con vigencia y las
plantillas.

```json
{
  "weekly_target_minutes": 2400,
  "apply_from": "next_week",
  "max_daily_minutes": 600,
  "weekday_templates": [{"weekday": 4, "kind": "PREFERRED"}]
}
```

- **Valores con vigencia**: si cambia `weekly_target_minutes` o
  `monthly_trip_limit`, se crea una fila **nueva** en `SettingValue` con la
  fecha indicada en `apply_from`; el historial no se toca. Si el valor es
  igual al vigente, no se crea ninguna fila.
  - `apply_from` para el objetivo semanal: `this_week` (lunes de esta
    semana, default) o `next_week`.
  - `apply_from` para el cupo de viajes: `this_month` (día 1, default) o
    `next_month`.
- **Plantillas**: `weekday_templates` acepta filas parciales identificadas
  por `weekday` (p. ej. `[{"weekday": 0, "kind": "OFF"}]`).
- **Validación de factibilidad**: se verifica
  `max_daily_minutes × (días PREFERRED + RESERVE) >= objetivo semanal`. Si
  no se cumple, responde **`422`** sin persistir nada:

```json
{"detail": "Con 40 h por semana necesitás subir el máximo diario o sumar días (hoy: 420 min × 5 días = 2100 min)."}
```

`max_daily_minutes` nunca se modifica automáticamente.

### `GET|POST|PATCH|DELETE /api/holidays/`

CRUD de feriados (todos editables y eliminables). Filtro: `?year=YYYY`.

```json
{"date": "2026-12-08", "name": "Inmaculada Concepción de María", "kind": "NATIONAL"}
```

- `kind`: `NATIONAL`, `BRIDGE` o `PERSONAL`.
- Carga masiva por consola: `python manage.py import_holidays <año>` (fuente
  configurable con `HOLIDAYS_API_URL`, con `{year}` como placeholder). Se
  pueden enviar `year`/`month`/`day` en lugar de `date`.

### `GET /api/dashboard/`

Agregado del Dashboard: semana actual, déficit, próxima jornada y resumen de
transporte del mes en curso.

```json
{
  "week_start": "2026-10-26",
  "weekly_target_minutes": 1200,
  "worked_minutes": 600,
  "remaining_minutes": 600,
  "weekly_delta": -600,
  "opening_deficit_minutes": 180,
  "accumulated_deficit_minutes": 180,
  "closing_deficit_minutes": 780,
  "deficit_kind": "projected",
  "progress_ratio": 0.5,
  "open_session": null,
  "next_shift": {"date": "2026-10-29", "planned_start": "09:00", "planned_minutes": 300, "source": "plan"},
  "transport": { "… resumen mensual …" }
}
```

- `deficit_kind`: `projected` (semana abierta) o `definitive` (semana cerrada).
- `open_session`: jornada abierta o `null`.
- `next_shift.source`: `plan` (jornada planificada existente) o `sugerido`
  (propuesta del planificador, sin persistir).

---

## Transporte

`TravelRecord` guarda `occurred_at` (datetime en zona Córdoba), `direction`
(`IDA` | `VUELTA`), `amount` (Decimal copiado de la tarifa vigente al crear)
y `status` (`ACTIVE` | `VOIDED`). **`payment_type` no se guarda**: se deriva
por mes calendario (ver más abajo) y se expone como campo de solo lectura.

### `POST /api/travels/`

Registra un viaje. Todos los campos son opcionales:

```json
{"occurred_at": "2026-10-28T08:15:00-03:00", "direction": "IDA", "amount": "820.00"}
```

- `occurred_at`: default = ahora. No puede ser futuro (zona Córdoba).
- `direction`: default = la sugerida por `/api/travels/next-direction/`.
- `amount`: default = tarifa vigente (`Settings.current_fare`). Error `400`
  si la tarifa es 0 y no se envía importe.
- **Doble toque**: si ya hay un viaje `ACTIVE` de la **misma dirección**
  registrado en los últimos 60 segundos, responde `409`. Se salta la
  validación con `?force=true`.

### `GET /api/travels/`

Historial paginado. Filtros: `?month=YYYY-MM`, `?payment_type=COMPANY|PERSONAL`
(sobre el tipo **derivado**), `?status=ACTIVE|VOIDED`, `?page=`, `?page_size=`.

### `PATCH /api/travels/{id}/`

Edita momento, dirección o importe. Para anular/restaurar:

```json
{"status": "VOIDED"}
```

Los registros anulados conservan su historial y **no computan** en ningún
cálculo ni consumen cupo. `DELETE` no está permitido (`405`).

### `GET /api/travels/next-direction/`

```json
{"direction": "VUELTA"}
```

Si el último viaje `ACTIVE` es de hoy, devuelve la dirección opuesta; si es
de un día anterior o no hay viajes, devuelve `IDA`.

### `GET /api/travels/summary/?month=YYYY-MM`

```json
{
  "month": "2026-10",
  "used_company": 12,
  "remaining_company": 8,
  "limit": 20,
  "personal_count": 4,
  "total_count": 16,
  "total_value": "13120.00",
  "company_value": "9840.00",
  "out_of_pocket_value": "3280.00",
  "salary_percentage": 1.09
}
```

- `payment_type` derivado: dentro del mes (zona Córdoba), los viajes
  `ACTIVE` ordenados por `(occurred_at, id)`; los primeros `limit` son
  `COMPANY` y el resto `PERSONAL`, donde `limit` es el cupo vigente para el
  día 1 de ese mes. Anular un viaje o cargar uno con fecha anterior
  recalcula todo solo; cambiar el cupo no altera meses pasados.
- `remaining_company = max(0, limit − used_company)` (nunca negativo).
- `salary_percentage = out_of_pocket_value / monthly_salary × 100`, o
  `null` si no hay sueldo cargado.

### `GET /api/travels/monthly-history/?months=6`

Serie mensual (por defecto los últimos 6 meses con viajes):

```json
[
  {
    "month": "2026-09",
    "ida_count": 11,
    "vuelta_count": 6,
    "company_count": 15,
    "personal_count": 2,
    "total_value": "11900.00",
    "out_of_pocket_value": "1400.00",
    "salary_percentage": 0.47,
    "limit": 20
  }
]
```

`limit` es el cupo vigente de ese mes (respeta la vigencia histórica).

### `GET /api/travels/monthly-comparison/?months=6`

Serie mensual en la forma clásica (para la comparación de gastos):

```json
[
  {"month": "2026-09", "month_label": "9 Sep 2026", "company_count": 15,
   "company_amount": "10500.00", "personal_count": 2, "personal_amount": "1400.00"}
]
```

---

## Control de horas (jornadas)

**Un solo servicio de cálculo**: la vista de horas y el planificador salen
del mismo cálculo (`GET /api/week/`). El plan automático **no se guarda**: se
calcula al vuelo y se autocorrige con cada registro o corrección. WorkPlan es
solo una excepción manual por fecha.

### `GET /api/today/`

Estado de hoy: entrada, salida prevista, minutos restantes y confirmación de
cierre olvidado (si la hay).

```json
{
  "date": "2026-11-06",
  "state": "IN_PROGRESS",
  "start_at": "2026-11-06T09:00:00-03:00",
  "end_at": "2026-11-06T14:00:00-03:00",
  "worked_minutes": 60,
  "planned_minutes": 300,
  "remaining_minutes": 240,
  "needs_checkout_confirmation": null
}
```

- `state`: `NOT_STARTED`, `IN_PROGRESS` o `DONE`.
- `start_at`: entrada **real** (`null` si todavía no empezó). `end_at`:
  salida real si la jornada está cerrada, prevista si está en curso.
- `planned_minutes`: duración planificada de hoy (automática o manual).
- `needs_checkout_confirmation`: `null` o un objeto:
  `{"scope": "TODAY" | "PREVIOUS_DAY", "session_id": 1, "work_date":
  "2026-11-05", "started_at": "…", "planned_end": "…", "suggested_end": "…"}`.

### `GET /api/week/?date=YYYY-MM-DD`

Vista semanal unificada (horas + plan). `date` puede ser cualquier día de la
semana; default: semana actual.

```json
{
  "week_start": "2026-11-02", "week_end": "2026-11-08",
  "target_minutes": 1200, "carry_over_minutes": 0,
  "worked_minutes": 600, "remaining_minutes": 600,
  "blocked_minutes": 0, "unscheduled_minutes": 300,
  "needs_checkout_confirmation": null,
  "projected_end": {"date": "2026-11-07", "time": "14:00"},
  "days": [
    {
      "date": "2026-11-06", "weekday": 4,
      "status": "TODAY", "is_holiday": false, "holiday_name": null,
      "start_at": "…", "end_at": "…", "worked_minutes": 60,
      "planned_start": "09:00", "planned_minutes": 300,
      "diff_minutes": -240, "needs_checkout_confirmation": null,
      "is_manual": false, "is_locked": false
    }
  ],
  "today": { "…bloque idéntico al de /api/today/…" }
}
```

- `status` del día: `DONE` (cerrada), `TODAY` (hoy, con o sin jornada en
  curso), `PLANNED`, `HOLIDAY`, `OFF`, `MISSED` (pasado sin jornada; no se
  replanifica) o `PENDING_CONFIRMATION` (jornada olvidada de cerrar).
- **Algoritmo**: `remaining = max(0, objetivo vigente + carry_over −
  trabajado − minutos de días manuales futuros)`. Los feriados **no**
  reducen el objetivo. Candidatos: desde hoy (inclusive si hoy no tiene
  jornada) hasta domingo, excluyendo feriados, OFF, no disponibles y días
  manuales. Se asignan primero los días `PREFERRED` en orden cronológico,
  luego `RESERVE`, se estiran hasta `max_daily_minutes`, y un resto menor
  que `min_block_minutes` se absorbe en un día ya planificado. Lo que no
  entra queda en `unscheduled_minutes`.
- `projected_end`: último momento en que se termina el trabajo de la semana.
- `carry_over_minutes`: solo > 0 si `Settings.carry_over_deficit` está activo.

### `POST /api/work-sessions/check-in/`

```json
{"start_at": "2026-11-06T09:15:00-03:00", "notes": ""}
```

Abre la jornada de hoy (`start_at` opcional: default = ahora del servidor).

- `409` con `code`:
  - `PENDING_CONFIRMATION`: hay una jornada que olvidaron cerrar; hay que
    confirmar el cierre antes de abrir otra.
  - `OPEN_SESSION_EXISTS`: ya hay una jornada en curso.
- `400`: entrada futura, de otro día o día que ya tiene jornada.

### `POST /api/work-sessions/check-out/`

```json
{"end_at": "2026-11-06T14:05:00-03:00", "confirm": false}
```

Cierra la jornada abierta (`end_at` opcional: default = ahora).

- `409` `NO_OPEN_SESSION`: no hay jornada abierta.
- `400`: salida anterior o igual a la entrada, futura (tolerancia 300 s) o
  de otro día local.
- `422` `{"detail": "…", "code": "DURATION_EXCEEDS_MAX"}`: la duración
  supera `max_daily_minutes`; repetir con `"confirm": true` la guarda igual.

### `POST /api/work-sessions/{id}/check-out/`

Igual que la anterior pero sobre una jornada específica (p. ej. la de la
confirmación olvidada, cerrándola con `suggested_end`).

### `POST /api/work-sessions/{id}/snooze/`

«Sigo trabajando»: posterga la salida prevista 30 minutos
(`snoozed_until`). Solo aplica a jornadas de **hoy**; una del día anterior
responde `409` `SNOOZE_NOT_ALLOWED`.

### `GET /api/work-sessions/current/`

```json
{"session": { "…WorkSession… o null }}
```

### `GET /api/work-sessions/`

Historial paginado. Filtros: `?month=YYYY-MM`, `?week_start=YYYY-MM-DD`,
`?date=YYYY-MM-DD`, `?status=IN_PROGRESS|COMPLETED`. `POST` a la lista →
`405` (las jornadas solo se abren con check-in).

### `PATCH /api/work-sessions/{id}/`

Corrección manual de `start_at`, `end_at` o `notes`, **sin** las
restricciones del check-out (permite corregir jornadas históricas). Única
validación: salida > entrada. `end_at: null` reabre la jornada.

### `GET /api/hours/monthly-summary/?month=YYYY-MM`

```json
{
  "month": "2026-11",
  "weeks": [
    {"week_start": "2026-11-02", "week_end": "2026-11-08",
     "worked_minutes": 540, "target_minutes": 1200}
  ],
  "total_worked_minutes": 540,
  "total_target_minutes": 1200
}
```

Incluye las semanas con jornadas en el mes y la semana en curso (aunque
todavía no haya jornadas).

---

## Planificador semanal

El plan es **automático y no persistente**: sale de `GET /api/week/`. En la
base solo viven las **excepciones manuales** (`WorkPlan`, una fila por
fecha), que el motor respeta y descuenta del restante (`blocked_minutes`).

### `GET /api/work-plans/?week_start=YYYY-MM-DD`

Excepciones manuales de la semana (paginado).

### `PATCH /api/work-plans/{fecha}/` — upsert por fecha

```json
{"planned_start": "13:00", "planned_minutes": 240, "is_locked": false,
 "is_available": true, "notes": ""}
```

Crea la excepción del día si no existe (`201`) o la edita (`200`). La fecha
va en la URL (`YYYY-MM-DD`), no en el body.

- `is_available: false`: marca el día como no disponible (`planned_minutes`
  debe ser 0).
- `is_locked`: protege la fila; un día bloqueado no se puede eliminar.

### `DELETE /api/work-plans/{fecha}/`

Elimina la excepción: el día vuelve al plan automático. `404` si no existe;
`400` si está bloqueada.

### `POST /api/work-plans/reset/?week=YYYY-MM-DD`

Limpia todas las excepciones manuales de la semana (también acepta `week` en
el body). Responde `{"week_start": "…", "deleted": 2}`.

`POST` a `GET|POST /api/work-plans/` (crear por JSON crudo) → `405`.

---

## Notas de seguridad

- No hay usuarios: todos los endpoints son abiertos y no hay propiedad de
  registros que validar. La protección del acceso se hace **fuera** de la
  app (Tailscale o Basic Auth con Caddy delante de Docker Compose; ver
  README, «Proteger el acceso»).
- Si se expone en red local, `CORS_ALLOWED_ORIGINS` limita los orígenes del
  navegador; conviene agregar TLS delante de la app.

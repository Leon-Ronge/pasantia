# Pasantía y Gastos de Transporte

Aplicación web personal para controlar **gastos en colectivo** (cupo mensual
de viajes que incluye la empresa) y **horas de pasantía** (objetivo semanal
configurable), con planificador semanal automático/manual y seguimiento del
déficit de horas acumulado.

- **Frontend:** React + TypeScript + Vite + Tailwind CSS
- **Backend:** Python + Django + Django REST Framework
- **Base de datos:** PostgreSQL
- **Despliegue:** Docker Compose (o ejecución local en desarrollo)

---

## Decisiones de diseño importantes

1. **Sin autenticación dentro de la app.** No hay usuarios, sesiones ni
   tokens: no existen `django.contrib.auth`, `django.contrib.sessions` ni
   `django.contrib.admin`, DRF corre con `UNAUTHENTICATED_USER = None` y
   todos los endpoints son abiertos. **La protección del acceso se hace
   fuera de la app** (ver sección «Proteger el acceso»): Tailscale
   (recomendado) o Basic Auth con Caddy delante de Docker Compose.
2. **Todo el dinero en decimal exacto** (`DecimalField` / strings en la API),
   nunca `float`. Si cambia la tarifa, los viajes históricos conservan su
   importe.
3. **Los viajes se anulan, no se eliminan** (`status=VOIDED`); los anulados
   no computan en ningún cálculo pero siguen en el historial. Cada viaje
   guarda momento (`occurred_at`, zona Córdoba) y dirección (`IDA`/`VUELTA`);
   el tipo (cubierto/personal) **no se guarda**: se deriva por mes calendario
   según el cupo vigente (los primeros N viajes activos del mes son COMPANY),
   de modo que anular un viaje o cargar uno con fecha anterior recalcula todo
   solo.
4. **El saldo de viajes se calcula en lectura** (viajes COMPANY activos del
   mes vs. cupo vigente): no hace falta ninguna tarea programada para
   «renovarlo».
5. **Horas y planificador salen de UN solo cálculo**: la vista semanal
   (`GET /api/week/`) calcula en la misma función las horas trabajadas, el
   plan de la semana y la detección de jornadas olvidadas de cerrar. Nada
   de eso se persiste derivado: corregir una jornada recalcula todo al
   vuelo (especificación §6: no guardar datos derivados en varios lugares).
6. **Modelo por semana**: la semana se cierra con su propio objetivo
   vigente (`closing = max(0, opening − (worked − objetivo))`); si
   `carry_over_deficit` está activo, el déficit de la semana anterior suma
   al objetivo actual. Los feriados nunca reducen el objetivo.
7. **Planificador determinista con reglas explícitas** (sin IA): reparte
   lo que falta priorizando los días PREFERRED (luego RESERVE) en orden
   cronológico, estirando hasta el máximo diario; respeta días OFF,
   feriados, no disponibles y excepciones manuales; nunca duplica días con
   jornada y explica en `unscheduled_minutes` lo que no pudo distribuir.
   El plan **no se guarda**: es al vuelo y se autocorrige.
8. **Jornada olvidada de cerrar**: si una jornada sigue abierta pasado su
   salida prevista (+ umbral configurable) o pertenece a un día anterior,
   la API la marca `PENDING_CONFIRMATION`, cuenta sus minutos solo hasta
   esa salida prevista, bloquea abrir otra jornada (409) y ofrece cerrarla
   con la salida sugerida o «Sigo trabajando» (+30 min, solo hoy).
9. **Días pasados sin jornada quedan `MISSED`**: no se replanifican ni se
   inventan registros; el déficit de la semana es el que dice la fórmula.
10. **Zona horaria** `America/Argentina/Cordoba` (UTC−3 sin horario de verano),
    fechas `DD/MM/AAAA`, hora 24 h y moneda ARS.
11. **Objetivo semanal y cupo mensual con vigencia** (`SettingValue`): cada
    cambio crea una fila nueva con su `effective_from`; el valor vigente de
    una fecha es el de mayor `effective_from` ≤ esa fecha. Los balances
    históricos nunca cambian por un cambio posterior.
12. **Plantillas de días** (`WeekdayTemplate`, 7 filas): PREFERRED / RESERVE /
    OFF, hora de entrada y duración opcional. Con duración vacía, el
    planificador propone `objetivo semanal / días PREFERRED` (minutos
    enteros); los días OFF nunca se planifican.
13. **Feriados editables** (`Holiday` + `/api/holidays/` + `manage.py
    import_holidays <año>`): la carga masiva viene de una API pública de
    feriados argentinos (fuente configurable) y todo se puede corregir o
    borrar a mano.

---

## Requisitos previos

Para **desarrollo local**:

- Python 3.11 o superior (probado con 3.14)
- Node.js 20 o superior (probado con 22) y npm
- PostgreSQL 14 o superior *(opcional: se puede desarrollar con SQLite usando
  `DB_ENGINE=sqlite3`)*

Para **Docker Compose**:

- Docker Desktop (o Docker Engine) con Compose v2

---

## Estructura del proyecto

```
.
├── backend/                  # Django + DRF
│   ├── config/               # settings, urls, wsgi/asgi
│   ├── core/                 # Settings, SettingValue (vigencia),
│   │   │                     # WeekdayTemplate, Holiday y Dashboard
│   │   └── management/       # bootstrap_settings, import_holidays
│   ├── transport/            # TravelRecord, resúmenes y comparación
│   ├── work/                 # WorkSession, WorkPlan (excepciones por fecha)
│   │   └── services/         # engine (motor puro), state (loader), sessions
│   ├── tests (por app)       # 111 pruebas de negocio
│   ├── Dockerfile
│   ├── entrypoint.sh         # migrate + bootstrap + gunicorn
│   └── requirements.txt
├── frontend/                 # React + TypeScript + Vite + Tailwind
│   ├── src/
│   │   ├── pages/            # Dashboard, Transporte, Horas, Planificador, Ajustes
│   │   ├── components/       # Layout, Modal, StatCard, ProgressBar…
│   │   ├── lib/format.ts     # fechas/horas/ARS en zona Córdoba
│   │   ├── api.ts            # cliente HTTP tipado
│   │   └── types.ts          # tipos compartidos con la API
│   ├── Dockerfile
│   └── nginx.conf            # SPA + proxy /api
├── deploy/Caddyfile          # reverse proxy con Basic Auth (perfil "auth")
├── docs/API.md               # documentación completa de la API
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## Instalación paso a paso (desarrollo local)

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt     # Linux/macOS: python3 -m pip ...
copy .env.example .env                                         # Linux/macOS: cp .env.example .env
```

Editá `.env`. Para empezar sin PostgreSQL:

```env
DB_ENGINE=sqlite3
```

(o dejá `DB_ENGINE=postgresql` y completá `DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT`).

### 2. Base de datos y datos iniciales

```powershell
python manage.py migrate
python manage.py bootstrap_settings   # singleton + valores con vigencia + plantillas de días
```

Opcional, para cargar los feriados argentinos de un año:

```powershell
python manage.py import_holidays 2026
```

### 3. Frontend

```powershell
cd ../frontend
npm install
```

### 4. Ejecución en desarrollo

Terminal 1 (API en `http://127.0.0.1:8000`):

```powershell
cd backend
.\.venv\Scripts\python manage.py runserver
```

Terminal 2 (app en `http://localhost:5173`):

```powershell
cd frontend
npm run dev
```

Abrí **http://localhost:5173**: cae directo en el Dashboard.
Vite proxyea `/api` a Django, así que no hace falta configurar CORS en
desarrollo.

---

## Ejecución con Docker Compose

```powershell
copy .env.example .env     # Linux/macOS: cp .env.example .env
# Editá .env: DB_PASSWORD, DJANGO_SECRET_KEY (y puertos si hacen falta)
docker compose up --build
```

Al terminar:

| Servicio  | URL |
|-----------|-----|
| Aplicación (nginx + frontend + API) | http://localhost:8080 |
| API directa (interna) | `http://backend:8000` |
| PostgreSQL | `localhost:5433` (configurable con `POSTGRES_PORT`) |

- **Desde el celular**: `http://<IP-del-PC>:8080` (misma red Wi-Fi). Ej.:
  `ipconfig` → IPv4 → `http://192.168.0.10:8080`. La app es responsive.
- Útiles: `docker compose logs -f backend`, `docker compose down`
  (los datos persisten en el volumen `pgdata`), `docker compose down -v`
  (**borra los datos**).

> Si ya tenés un PostgreSQL local en el puerto 5432, `docker-compose.yml`
> usa el 5433 por defecto para evitar el choque (configurable en `.env`).

---

## Proteger el acceso

La app **no tiene usuarios ni login**: todos los endpoints son abiertos. Si
se va a usar fuera de una red doméstica de confianza, el acceso se protege
**fuera** de la aplicación. Dos opciones:

### Opción A — Tailscale (recomendada)

Exponer la app solo en una red privada de Tailscale, sin abrir puertos en
el router ni exponer credenciales:

1. Instalar Tailscale en el servidor y en los dispositivos
   (<https://tailscale.com>), y entrar a la misma cuenta/red.
2. En el servidor: `tailscale up` y anotar la IP de la red (100.x.y.z).
3. En el `.env`: `WEB_PORT=8080` y, si se quiere, dejar de publicar el
   puerto en el router (el tráfico va por Tailscale).
4. Abrir `http://100.x.y.z:8080` desde cualquier dispositivo de la red
   Tailscale.

Ventajas: sin contraseñas que rotar, tráfico cifrado, y la app nunca queda
visible en Internet. Es la opción recomendada para uso personal.

### Opción B — Basic Auth con Caddy delante de Docker Compose

Un contenedor de Caddy actúa de reverse proxy con Basic Auth y pide
usuario/contraseña antes de llegar a la app:

1. Generar el **hash** de la contraseña (nunca va en claro en `.env`):

   ```powershell
   docker run --rm caddy:2-alpine caddy hash-password --plaintext 'tu-contraseña'
   ```

2. Completar `.env`:

   ```env
   AUTH_PORT=8443
   CADDY_BASIC_AUTH_USER=admin
   CADDY_BASIC_AUTH_HASH=$2a$14$...   # salida del paso anterior
   ```

3. Levantar con el perfil `auth`:

   ```powershell
   docker compose --profile auth up -d
   ```

4. Abrir **http://localhost:8443** (o `http://<IP-del-PC>:8443`): Caddy pide
   usuario y contraseña y recién entonces proxyea a la app.

Notas:

- El puerto 8080 queda sirviendo la app directamente (sin contraseña): es
  útil en la red local. Si solo se quiere acceso con contraseña, no abrir
  8080 en el router/firewall y usar únicamente `AUTH_PORT`.
- La configuración de Caddy vive en `deploy/Caddyfile`; el Caddyfile usa
  `{env.*}`/`{$VAR}`, así que ningún dato sensible está versionado.
- Para agregar HTTPS con dominio propio, alcanza con cambiar el sitio del
  `Caddyfile` a `https://midominio.com { ... }` (Caddy obtiene el
  certificado solo).

---

## Migraciones de base de datos

```powershell
python manage.py makemigrations     # solo al cambiar modelos
python manage.py migrate
python manage.py showmigrations     # estado
```

En Docker el `entrypoint` ejecuta `migrate` automáticamente al arrancar.

---

## Pruebas automatizadas

```powershell
cd backend
$env:DB_ENGINE="sqlite3"            # PowerShell; Linux/macOS: export DB_ENGINE=sqlite3
.\.venv\Scripts\python manage.py test
```

**111 pruebas** que cubren los criterios de la especificación §9:

- **Transporte**: derivación COMPANY/PERSONAL por mes calendario (los
  primeros N viajes activos), reinicio del cupo en mes nuevo, anular libera
  el cupo, importes históricos intactos al cambiar la tarifa, cambio de cupo
  20 → 15 desde el mes siguiente sin alterar meses anteriores, dirección
  sugerida (`next-direction`: mismo día / día anterior / sin viajes), anti
  doble toque (409 salvo `?force=true`), saldo nunca negativo, porcentaje
  sobre el sueldo (null sin sueldo), `occurred_at` no futuro, `DELETE`
  prohibido y anulación por PATCH.
- **Motor puro (horas + planificador, sin BD)**: 4×5 h sin restricciones;
  lun 8:55–13:55 / mar 9:00–14:05 / mié 8:54–13:48 / jue sin ir → el
  viernes planifica 9:00–14:01; feriados lun+mar → mié 420 / jue 420 /
  vie 360; 40 h en 5 días preferidos (5×480); día no disponible saltado;
  día manual respetado y descontado; cero duplicados; minutos sin
  programar; carry-over on/off; 59 min de atraso no pide confirmación y 61
  sí; jornada del día anterior pide siempre y su tiempo cuenta solo hasta
  la salida prevista; «Sigo trabajando» difiere el aviso.
- **API de horas (reloj congelado)**: `/api/today/`, `/api/week/` y
  `/api/hours/monthly-summary/`; check-in/check-out flujo completo con
  hora del servidor; doble toque 409; salida ≤ entrada / futura / de otro
  día rechazadas; duración sobre el máximo diario → 422
  `DURATION_EXCEEDS_MAX` aceptando `confirm=true`; cierre de jornada
  olvidada con `suggested_end`; snooze hoy OK / ayer 409; `POST` a la
  lista de jornadas y de planes → 405; upsert/borrado/reset de planes por
  fecha; corrección manual por PATCH.
- **Configuración**: valores por defecto (máx. diario 420, bloque mínimo 60,
  etc.), validaciones, singleton, plantillas de días.
- **Vigencia de valores**: cambiar 20 h → 40 h desde la próxima semana no
  afecta semanas pasadas; el cupo de viajes aplicado a este/próximo mes solo
  cambia desde su fecha; validación 422 cuando 40 h no entran en el máximo
  diario de 420.
- **Feriados**: CRUD completo por API y `import_holidays` (tipos mapeados,
  idempotente, respeta los PERSONAL).
- **Sin autenticación**: todos los endpoints responden sin credenciales;
  `django.contrib.auth/sessions/admin` no están instalados; DRF sin clases
  de autenticación.

---

## Documentación de la API

Ver **[docs/API.md](docs/API.md)**: endpoints, parámetros, ejemplos de
request/response, códigos de error y el modelo de cálculo de déficit.

Resumen de endpoints:

```
GET|PATCH  /api/settings/            # singleton + valores con vigencia + plantillas
GET        /api/dashboard/
GET|POST|PATCH|DELETE  /api/holidays/
GET        /api/travels/             POST /api/travels/  PATCH /api/travels/{id}/
GET        /api/travels/summary/     GET  /api/travels/next-direction/
GET        /api/travels/monthly-history/   GET  /api/travels/monthly-comparison/
GET        /api/today/               GET  /api/week/?date=
GET        /api/hours/monthly-summary/?month=
GET        /api/work-sessions/       GET  /api/work-sessions/current/
POST       /api/work-sessions/check-in/    POST /api/work-sessions/check-out/
POST       /api/work-sessions/{id}/check-out/   POST /api/work-sessions/{id}/snooze/
PATCH      /api/work-sessions/{id}/        # corrección manual
GET        /api/work-plans/          PATCH|DELETE /api/work-plans/{fecha}/
POST       /api/work-plans/reset/    # el plan automático no se guarda: es al vuelo
```

---

## Variables de entorno

### Raíz del proyecto (`.env` → Docker Compose)

| Variable | Descripción | Ejemplo |
|----------|-------------|---------|
| `DB_NAME` | Base de datos PostgreSQL | `pasantia` |
| `DB_USER` | Usuario de PostgreSQL | `pasantia` |
| `DB_PASSWORD` | Contraseña (**obligatoria**) | `…` |
| `POSTGRES_PORT` | Puerto del contenedor PG en el host | `5433` |
| `WEB_PORT` | Puerto de la app web | `8080` |
| `DJANGO_SECRET_KEY` | Clave secreta (**obligatoria**) | `…` |
| `DJANGO_DEBUG` | `false` en producción | `false` |
| `DJANGO_ALLOWED_HOSTS` | Hosts permitidos por Django | `localhost,127.0.0.1,backend` |
| `CORS_ALLOWED_ORIGINS` | Orígenes CORS habilitados | `http://localhost:8080` |
| `AUTH_PORT` | Puerto del proxy con Basic Auth (perfil `auth`) | `8443` |
| `CADDY_BASIC_AUTH_USER` | Usuario del Basic Auth | `admin` |
| `CADDY_BASIC_AUTH_HASH` | Hash bcrypt de la contraseña (con `caddy hash-password`) | `$2a$14$…` |
| `HOLIDAYS_API_URL` | Fuente de `import_holidays` (`{year}` = año) | `https://api.argentinadatos.com/v1/feriados/{year}` |

### `backend/.env` (desarrollo local)

| Variable | Descripción |
|----------|-------------|
| `DB_ENGINE` | `postgresql` (default) o `sqlite3` |
| `SQLITE_PATH` | Ruta del SQLite (si se usa) |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | Conexión PostgreSQL |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | Django |
| `CORS_ALLOWED_ORIGINS` | Orígenes del frontend (Vite: `http://localhost:5173`) |

Ningún archivo `.env` está versionado (`.gitignore`); `.env.example` no
contiene credenciales reales.

---

## Instrucciones de despliegue

1. Servidor con Docker y Compose v2; abrir solo el puerto de la app (8080)
   y, opcionalmente, el de PostgreSQL (5433) en firewall/seguridad del
   proveedor.
2. `git clone` → `cp .env.example .env` → valores fuertes para
   `DB_PASSWORD` y `DJANGO_SECRET_KEY`
   (`openssl rand -hex 32` o `python -c "import secrets;print(secrets.token_hex(32))"`).
3. `DJANGO_DEBUG=false` y `DJANGO_ALLOWED_HOSTS` con el dominio real.
4. Proteger el acceso según la sección homónima: Tailscale (recomendado) o
   Basic Auth con Caddy (`docker compose --profile auth up -d`).
5. `docker compose up -d --build`.
6. Actualizaciones: `git pull && docker compose up -d --build` (las
   migraciones corren solas en el arranque).

---

## Respaldo y restauración de PostgreSQL

### Respaldo (host, con el stack levantado)

```powershell
docker compose exec -T db pg_dump -U pasantia -d pasantia --clean --if-exists > backup_2026-10-28.sql
```

### Restauración

```powershell
Get-Content backup_2026-10-28.sql -Raw | docker compose exec -T db psql -U pasantia -d pasantia
```

### Respaldo del volumen completo (alternativa)

```powershell
docker run --rm -v pasantia_pgdata:/data -v ${PWD}:/backup alpine tar czf /backup/pgdata.tar.gz -C /data .
```

### Restaurar volumen

```powershell
docker compose down
docker run --rm -v pasantia_pgdata:/data -v ${PWD}:/backup alpine tar xzf /backup/pgdata.tar.gz -C /data
docker compose up -d
```

Recomendación: los valores por defecto (Settings, valores con vigencia y
plantillas) se regeneran con `bootstrap_settings`; lo importante de respaldar
es la base PostgreSQL.

---

## Solución de problemas

| Sintoma | Solución |
|---------|----------|
| «No se pudo conectar con el servidor» en el Dashboard | Levantá el backend (`runserver`) o revisá `docker compose logs backend` |
| Error `400` «Configure la tarifa vigente» al registrar viajes | Andá a **Ajustes** y cargá la tarifa del colectivo |
| Puerto 5433/8080 ocupados | Cambialos en `.env` (`POSTGRES_PORT`, `WEB_PORT`) |
| Pruebas fallan al usar PostgreSQL local | Usá `DB_ENGINE=sqlite3` para el entorno de pruebas |
| El celular no conecta | Usá la IP IPv4 del PC, revisá firewall y que ambos estén en la misma red |
| `Docker Desktop` no arranca | Esperá a que el engine levante y reintentá `docker compose up --build` |

---

## Criterio de aceptación

- [x] Al abrir la URL se muestra directamente el Dashboard (sin usuarios ni
      login dentro de la app; el acceso se protege afuera, ver «Proteger el
      acceso»).
- [x] Registrar viajes (dirección sugerida ida/vuelta, tipo derivado según
      el cupo del mes), filtrar, editar y anular (409 anti doble toque).
- [x] Controlar gastos: resumen mensual, ahorro y comparación entre meses.
- [x] Marcar entrada y salida; ver horas trabajadas, salida prevista y
      restantes en vivo.
- [x] Consultar déficit semanal y acumulado (proyectado vs. definitivo).
- [x] Generar el plan semanal automáticamente y modificarlo manualmente
      (hora, duración, bloqueo, días no disponibles) sin perder información.
- [x] Objetivo semanal y cupo de viajes con vigencia: los cambios no
      reescriben el historial.
- [x] Plantillas de días (PREFERRED/RESERVE/OFF, hora y duración) y feriados
      editables con carga masiva por año.
- [x] Datos persistidos en PostgreSQL, accesibles desde PC y celular.

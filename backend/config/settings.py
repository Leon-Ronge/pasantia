"""Configuración del proyecto «Pasantía y Gastos de Transporte».

Decisiones documentadas (ver README):
- Sin autenticación de ningún tipo: no hay usuarios, sesiones ni tokens.
  La API se sirve con permisos abiertos y sin clases de autenticación en
  Django REST Framework (``UNAUTHENTICATED_USER = None``); el acceso se
  protege fuera de la app (Tailscale o Basic Auth con Caddy, ver README).
- La base de datos por defecto es PostgreSQL. Para desarrollo sin Docker
  (y para correr las pruebas) se puede forzar SQLite con DB_ENGINE=sqlite3.
- Todas las fechas se almacenan en UTC (USE_TZ=True) y se presentan en
  America/Argentina/Cordoba.
"""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga el archivo .env del backend (si existe). No falla si no está.
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-change-me-in-production")
DEBUG = os.getenv("DJANGO_DEBUG", "true").strip().lower() in ("1", "true", "yes")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
# Despliegue en Render: el dominio del servicio (p. ej. xxx.onrender.com).
if ".onrender.com" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".onrender.com")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    # Terceros
    "rest_framework",
    "corsheaders",
    # Apps propias
    "core",
    "transport",
    "work",
]

MIDDLEWARE = [
    # Basic Auth (solo si BASIC_AUTH_USER/PASS están definidos: en
    # desarrollo local queda abierto, igual que hasta ahora).
    "config.middleware.BasicAuthMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Sirve el build del frontend (FRONTEND_DIST) con caché y compresión.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
# Por defecto: PostgreSQL (producción / Docker Compose).
# DB_ENGINE=sqlite3 permite usar SQLite local para desarrollo sin Docker.
DB_ENGINE = os.getenv("DB_ENGINE", "postgresql").strip().lower()


def _database_from_url(url: str) -> dict:
    """DATABASE_URL (Neon / Postgres) → configuración de Django.

    Acepta postgres:// o postgresql://, con sslmode en la query string.
    Si no viene sslmode y el host no es local, se fuerza sslmode=require
    (Neon y la mayoría de los servicios gestionados lo exigen).
    """
    from urllib.parse import parse_qsl, unquote, urlparse

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    options = {}
    if query.get("sslmode"):
        options["sslmode"] = query["sslmode"]
    elif parsed.hostname not in (None, "localhost", "127.0.0.1"):
        options["sslmode"] = "require"
    config = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": (parsed.path or "/pasantia").lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
    }
    if options:
        config["OPTIONS"] = options
    return config


if os.getenv("DATABASE_URL"):
    # Producción (Render + Neon): todo desde la URL de conexión.
    _database_url = os.getenv("DATABASE_URL", "")
    # Falla temprano y con mensaje accionable si llega la URL equivocada
    # (p. ej. el link del panel de Neon en vez del connection string).
    if not _database_url.startswith(("postgres://", "postgresql://")):
        raise ImproperlyConfigured(
            "DATABASE_URL inválida: se espera una cadena de conexión de "
            "Postgres (empieza con postgresql://…), por ejemplo la "
            "'pooled connection string' de Neon: "
            "postgresql://usuario:clave@ep-xxxx.neon.tech/neondb?sslmode=require. "
            "NO uses el link del panel (console.neon.tech). "
            f"Recibida: {_database_url[:60]}"
        )
    DATABASES = {"default": _database_from_url(_database_url)}
elif DB_ENGINE in ("sqlite", "sqlite3"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.getenv("SQLITE_PATH", str(BASE_DIR / "db.sqlite3")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "pasantia"),
            "USER": os.getenv("DB_USER", "pasantia"),
            "PASSWORD": os.getenv("DB_PASSWORD", "pasantia"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

# Sin AUTH_PASSWORD_VALIDATORS: la app no tiene usuarios ni contraseñas.

# ---------------------------------------------------------------------------
# Internacionalación / zona horaria
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Cordoba"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------------
# Frontend (SPA) servido por el mismo proceso
# ---------------------------------------------------------------------------
# En producción (Docker de un solo servicio) el build de Vite queda en
# FRONTEND_DIST y whitenoise lo sirve junto con la API (mismo origen).
FRONTEND_DIST = Path(
    os.getenv("FRONTEND_DIST", str(BASE_DIR.parent / "frontend" / "dist"))
).resolve()
WHITENOISE_ROOT = FRONTEND_DIST
WHITENOISE_INDEX_FILE = True
WHITENOISE_AUTOREFRESH = DEBUG

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
# Sin autenticación (decisión de diseño: no hay usuarios, sesiones ni
# tokens; ver README). DEFAULT_AUTHENTICATION_CLASSES vacío y
# UNAUTHENTICATED_USER = None evitan siquiera importar django.contrib.auth
# (que no está en INSTALLED_APPS). El acceso se protege fuera de la app.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.DefaultPagination",
    "PAGE_SIZE": 20,
    "DATETIME_FORMAT": "%Y-%m-%dT%H:%M:%S%z",
    "DATE_INPUT_FORMATS": ["%Y-%m-%d"],
}

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# Solo se habilitan los orígenes configurados explícitamente.
_cors = os.getenv(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
)
CORS_ALLOWED_ORIGINS = [o.strip() for o in _cors.split(",") if o.strip()]
CORS_ALLOW_ALL_ORIGINS = os.getenv("CORS_ALLOW_ALL_ORIGINS", "false").strip().lower() in (
    "1",
    "true",
    "yes",
)

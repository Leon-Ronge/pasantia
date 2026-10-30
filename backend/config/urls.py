"""URLs raíz de la API (sin admin: no hay usuarios).

Sirve también el frontend (SPA) cuando el build existe en FRONTEND_DIST:
los archivos reales (assets) los resuelve whitenoise antes del enrutado y
cualquier otra ruta GET que no sea /api/ o /health/ responde con
index.html para que el router del cliente funcione.
"""
from pathlib import Path

from django.http import FileResponse, Http404, JsonResponse
from django.urls import include, path, re_path

from config.settings import FRONTEND_DIST


def health(request):
    """GET /health/: sonda de vida para Render (sin base de datos)."""
    return JsonResponse({"status": "ok"})


def spa(request, _path=None):
    """index.html de la SPA para cualquier ruta de pantalla."""
    if request.path.startswith(("/api/", "/health/")):
        raise Http404
    index = Path(FRONTEND_DIST) / "index.html"
    if not index.is_file():
        raise Http404("Frontend no compilado.")
    return FileResponse(open(index, "rb"), content_type="text/html")


urlpatterns = [
    path("health/", health, name="health"),
    path("api/", include("core.urls")),
    path("api/", include("transport.urls")),
    path("api/", include("work.urls")),
    # SPA: todo lo demás (excepto archivos que whitenoise ya resolvió).
    re_path(r"^(?!.*/\.).*$", spa),
]

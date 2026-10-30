"""Middleware de la aplicación.

Basic Auth opcional: si las variables de entorno BASIC_AUTH_USER y
BASIC_AUTH_PASS están definidas (despliegue público), TODAS las peticiones
(API y frontend) exigen esas credenciales. En desarrollo local no se
definen y el middleware no hace nada (la app queda abierta, como siempre).
"""
import hmac
import os
from base64 import b64decode

from django.http import HttpResponse


class BasicAuthMiddleware:
    """Basic Auth global vía Authorization: Basic (RFC 7617)."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.user = os.getenv("BASIC_AUTH_USER", "").strip()
        self.password = os.getenv("BASIC_AUTH_PASS", "").strip()

    def __call__(self, request):
        # La sonda de vida de Render no envía credenciales: /health/ queda
        # exenta (no expone datos).
        if request.path == "/health/":
            return self.get_response(request)
        if self.user and self.password and not self._authorized(request):
            response = HttpResponse("Autenticación requerida.", status=401)
            response["WWW-Authenticate"] = 'Basic realm="Pasantía"'
            return response
        return self.get_response(request)

    def _authorized(self, request) -> bool:
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = b64decode(header[6:], validate=True).decode("utf-8")
        except Exception:
            return False
        user, _, password = decoded.partition(":")
        return hmac.compare_digest(user, self.user) and hmac.compare_digest(
            password, self.password
        )

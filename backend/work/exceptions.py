"""Excepciones de la API de `work`.

DRF deja pasar el ``detail`` como dict, así que las respuestas llevan
``{"detail": ..., "code": ...}`` y el frontend puede ramificar por `code`.
"""
from rest_framework.exceptions import APIException


class Conflict(APIException):
    """409: estado incompatible (doble jornada, cierre olvidado, etc.)."""

    status_code = 409


class NeedsConfirmation(APIException):
    """422: la operación requiere confirmación explícita del usuario."""

    status_code = 422
    default_code = "NEEDS_CONFIRMATION"

    def __init__(self, detail: str, code: str | None = None):
        super().__init__({"detail": detail, "code": code or self.default_code})

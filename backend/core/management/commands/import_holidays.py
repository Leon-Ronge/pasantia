"""Importa feriados argentinos desde una API pública configurable.

Uso:
    python manage.py import_holidays 2026
    python manage.py import_holidays 2026 --source "https://ejemplo.com/{year}"

La fuente por defecto es la API pública de ArgentinaDatos
(https://api.argentinadatos.com/v1/feriados/{year}) y se puede cambiar con
la variable de entorno HOLIDAYS_API_URL o con --source (el placeholder
{year} se reemplaza por el año pedido).

Los feriados existentes se actualizan; los que están marcados como
PERSONAL se respetan y no se tocan.
"""
import json
import os
import urllib.request

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from core.models import Holiday

DEFAULT_SOURCE = "https://api.argentinadatos.com/v1/feriados/{year}"

#: Tipos de la API de origen → tipos del modelo.
KIND_MAP = {
    "inamovible": Holiday.Kind.NATIONAL,
    "trasladable": Holiday.Kind.NATIONAL,
    "puente": Holiday.Kind.BRIDGE,
}


class Command(BaseCommand):
    help = "Importa los feriados argentinos de un año desde una API pública."

    def add_arguments(self, parser):
        parser.add_argument("year", type=int, help="Año a importar (p. ej. 2026).")
        parser.add_argument(
            "--source",
            default=os.getenv("HOLIDAYS_API_URL", DEFAULT_SOURCE),
            help="URL de la fuente; {year} se reemplaza por el año.",
        )

    def handle(self, *args, **options):
        year = options["year"]
        url = options["source"].format(year=year)
        request = urllib.request.Request(
            url,
            headers={
                # Algunas APIs públicas rechazan el User-Agent por defecto
                # de urllib (403); con uno propio responden normalmente.
                "User-Agent": "miapp-import-holidays/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except Exception as exc:  # noqa: BLE001 - se informa como CommandError
            raise CommandError(f"No se pudo consultar la fuente {url}: {exc}") from exc

        if not isinstance(payload, list):
            raise CommandError(f"La fuente {url} devolvió una lista inesperada.")

        created = updated = skipped = 0
        for item in payload:
            try:
                day = date.fromisoformat(item["fecha"])
                name = str(item["nombre"]).strip()
            except (KeyError, TypeError, ValueError):
                self.stderr.write(f"Registro inválido ignorado: {item!r}")
                continue
            kind = KIND_MAP.get(str(item.get("tipo", "")).lower(), Holiday.Kind.NATIONAL)

            existing = Holiday.objects.filter(date=day, name=name).first()
            if existing and existing.kind == Holiday.Kind.PERSONAL:
                skipped += 1
                continue
            _obj, was_created = Holiday.objects.update_or_create(
                date=day, name=name, defaults={"kind": kind}
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Feriados de {year}: {created} creados, {updated} actualizados, "
                f"{skipped} personales respetados."
            )
        )

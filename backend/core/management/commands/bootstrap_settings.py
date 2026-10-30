from django.core.management.base import BaseCommand

from core.models import SettingValue, Settings, WeekdayTemplate


class Command(BaseCommand):
    help = (
        "Crea (si no existen) el registro singleton de Settings, los valores "
        "iniciales con vigencia (SettingValue) y las 7 plantillas de días."
    )

    def handle(self, *args, **options):
        settings, created = Settings.objects.get_or_create(pk=Settings.SINGLETON_PK)
        if created:
            self.stdout.write(self.style.SUCCESS("Settings creados con valores por defecto."))
        else:
            self.stdout.write("Settings ya existentes; no se modificó nada.")

        SettingValue.seed_initial()
        self.stdout.write("Valores con vigencia asegurados (1200 min / 20 viajes).")

        WeekdayTemplate.seed_initial()
        self.stdout.write("Plantillas de días aseguradas (lun-jue PREFERRED, vie RESERVE, sáb-dom OFF).")

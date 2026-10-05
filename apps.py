import os
import sys
from django.apps import AppConfig
class CabinetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cabinet"
    verbose_name = "Тайм-трекер"
    def ready(self):
        if "runserver" in sys.argv and (os.environ.get("RUN_MAIN") == "true" or "--noreload" in sys.argv):
            from .services import get_tracker
            get_tracker()

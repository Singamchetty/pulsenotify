from django.apps import AppConfig


class PulseConfig(AppConfig):
    name = 'pulse'

    def ready(self):
        from . import signals  # noqa: F401

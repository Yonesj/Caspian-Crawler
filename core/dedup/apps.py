from django.apps import AppConfig


class DedupConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.dedup'
    label = 'dedup'
    verbose_name = 'Deduplication'

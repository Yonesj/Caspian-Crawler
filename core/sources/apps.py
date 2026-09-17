from django.apps import AppConfig


class SourcesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.sources'
    label = 'sources'
    verbose_name = 'Crawl sources'

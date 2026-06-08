from django.apps import AppConfig


class CategoriasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.categorias"
    verbose_name = "Categorias"

    def ready(self):
        from django.contrib.auth import get_user_model
        from django.db.models.signals import post_save

        from . import signals

        post_save.connect(
            signals.criar_categorias_predefinidas,
            sender=get_user_model(),
            dispatch_uid="categorias_seed_predefinidas",
        )

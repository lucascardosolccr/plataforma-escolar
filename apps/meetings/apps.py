"""Reuniões e atendimentos: agenda, pauta, participantes, registro e encaminhamentos."""

from django.apps import AppConfig


class MeetingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.meetings"
    verbose_name = "Reuniões e atendimentos"

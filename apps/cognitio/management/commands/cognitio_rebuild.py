"""Refaz o repositório de evidências por habilidade a partir dos registros existentes."""

from django.core.management.base import BaseCommand

from apps.cognitio.evidence import rebuild_school
from apps.core.models import School


class Command(BaseCommand):
    help = "Recalcula as evidências por habilidade de todas as turmas (idempotente)."

    def handle(self, *args, **options):
        for school in School.objects.all():
            changed, removed = rebuild_school(school)
            self.stdout.write(f"{school}: {changed} evidências criadas ou atualizadas, {removed} removidas.")

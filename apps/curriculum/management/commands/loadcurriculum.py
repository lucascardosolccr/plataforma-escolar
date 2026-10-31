"""Recarrega o catálogo da BNCC e as referências normativas (idempotente)."""

from django.core.management.base import BaseCommand

from apps.curriculum.loader import load_bncc, load_references
from apps.curriculum.models import CurriculumItem, NormativeReference


class Command(BaseCommand):
    help = "Recarrega a BNCC (Ensino Fundamental) e as referências normativas, sem apagar nada."

    def handle(self, *args, **options):
        created, updated = load_bncc(CurriculumItem)
        refs = load_references(NormativeReference)
        self.stdout.write(f"BNCC: {created} itens novos, {updated} conferidos. Referências: {refs}.")

"""Recarrega o catálogo da BNCC, a PNED, a matriz analítica e as referências (idempotente)."""

from django.core.management.base import BaseCommand

from apps.curriculum.loader import load_bncc, load_computing, load_digital_and_dimensions, load_references
from apps.curriculum.models import (CurriculumCorrespondence, CurriculumItem, CurriculumItemVersion, ItemDimension,
                                    NormativeReference, SkillDimension)


class Command(BaseCommand):
    help = "Recarrega BNCC (EF), Computação (complemento à BNCC), PNED, matriz analítica e referências normativas, sem apagar nada."

    def handle(self, *args, **options):
        created, updated = load_bncc(CurriculumItem, CurriculumItemVersion)
        co_created, co_updated, co_links = load_computing(CurriculumItem, CurriculumItemVersion,
                                                          CurriculumCorrespondence)
        dims, links, corr = load_digital_and_dimensions(CurriculumItem, SkillDimension, ItemDimension,
                                                        CurriculumCorrespondence)
        refs = load_references(NormativeReference)
        self.stdout.write(f"BNCC: {created} novos, {updated} conferidos. Computação: {co_created} novos, {co_updated} conferidos. Dimensões: {dims} "
                          f"({links} ligações sugeridas). PNED: {corr} correspondências sugeridas. Referências: {refs}.")

"""Registra a fonte e o ano de referência das progressões propostas automaticamente (Prompt 16), para que
nenhuma relação do grafo fique sem fonte declarada. Só preenche campos vazios."""

from django.db import migrations

SOURCE = ("BNCC (MEC, 2018): mesma unidade temática no ano seguinte; proposta automática por semelhança do texto "
          "oficial, a validar pela equipe")


def fill(apps, schema_editor):
    SkillRelation = apps.get_model("cognitio", "SkillRelation")
    for rel in SkillRelation.objects.filter(kind="progressao", reference="").select_related("source", "target"):
        rel.reference = SOURCE
        rel.stage_year = f"{rel.source.years}º → {rel.target.years}º ano"[:40] if rel.source.years else ""
        rel.save(update_fields=["reference", "stage_year"])


class Migration(migrations.Migration):

    dependencies = [
        ("cognitio", "0008_grafo_tipado_decisoes_e_recuperacao"),
    ]

    operations = [
        migrations.RunPython(fill, migrations.RunPython.noop),
    ]

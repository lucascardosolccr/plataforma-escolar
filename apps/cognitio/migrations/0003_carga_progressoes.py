"""Relações propostas de progressão curricular entre habilidades da BNCC (mesmo
componente, mesma unidade temática, ano seguinte, vocabulário em comum).
Todas nascem "propostas" e precisam de validação pedagógica."""

from django.db import migrations


def load(apps, schema_editor):
    from apps.cognitio.graph import build_progressions

    build_progressions(apps.get_model("curriculum", "CurriculumItem"), apps.get_model("cognitio", "SkillRelation"))


class Migration(migrations.Migration):

    dependencies = [
        ("cognitio", "0002_grafo_alertas_modelos"),
        ("curriculum", "0004_carga_ontologia_pned"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

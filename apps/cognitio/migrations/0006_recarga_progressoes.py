"""Gera as progressões propostas que dependiam das unidades temáticas corrigidas
(primeira tabela de cada componente). Idempotente; não toca nas relações já
validadas ou rejeitadas."""

from django.db import migrations


def load(apps, schema_editor):
    from apps.cognitio.graph import build_progressions

    build_progressions(apps.get_model("curriculum", "CurriculumItem"), apps.get_model("cognitio", "SkillRelation"))


class Migration(migrations.Migration):

    dependencies = [
        ("cognitio", "0005_carga_estrategias"),
        ("curriculum", "0005_recarga_unidades"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

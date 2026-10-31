"""Banco inicial de estratégias de intervenção, com o nível de respaldo declarado."""

from django.db import migrations


def load(apps, schema_editor):
    from apps.cognitio.recommend import load_strategies

    load_strategies(apps.get_model("cognitio", "InterventionStrategy"), apps.get_model("curriculum", "SkillDimension"))


class Migration(migrations.Migration):

    dependencies = [
        ("cognitio", "0004_intervencoes"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

"""Recarrega unidade temática e objetos de conhecimento depois da correção do extrator
(primeira tabela de cada componente). O texto oficial das habilidades não muda;
se mudasse, a redação anterior ficaria em ``CurriculumItemVersion``."""

from django.db import migrations


def load(apps, schema_editor):
    from apps.curriculum.loader import load_bncc

    load_bncc(apps.get_model("curriculum", "CurriculumItem"), apps.get_model("curriculum", "CurriculumItemVersion"))


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0004_carga_ontologia_pned"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

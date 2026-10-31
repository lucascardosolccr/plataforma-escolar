"""Recarrega unidades temáticas e objetos de conhecimento lidos pela posição na página dupla do
PDF oficial da BNCC (unidades de História que vinham cortadas, objetos de História e Língua
Inglesa com pedaços da unidade, 4 habilidades sem unidade). O texto oficial das habilidades não
muda; se mudasse, a redação anterior ficaria em ``CurriculumItemVersion``."""

from django.db import migrations


def load(apps, schema_editor):
    from apps.curriculum.loader import load_bncc

    load_bncc(apps.get_model("curriculum", "CurriculumItem"), apps.get_model("curriculum", "CurriculumItemVersion"))


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0006_carga_computacao"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

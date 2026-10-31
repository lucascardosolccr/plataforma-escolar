"""Carrega as habilidades do Ensino Fundamental do complemento de Computação à BNCC
(Anexo ao Parecer CNE/CEB nº 2/2022) e sugere ligações com a matriz analítica e a PNED.
Só acrescenta: nenhum item existente é apagado."""

from django.db import migrations


def load(apps, schema_editor):
    from apps.curriculum.loader import load_computing, load_digital_and_dimensions

    Item = apps.get_model("curriculum", "CurriculumItem")
    Corr = apps.get_model("curriculum", "CurriculumCorrespondence")
    load_computing(Item, apps.get_model("curriculum", "CurriculumItemVersion"), Corr)
    load_digital_and_dimensions(Item, apps.get_model("curriculum", "SkillDimension"),
                                apps.get_model("curriculum", "ItemDimension"), Corr)


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0005_recarga_unidades"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

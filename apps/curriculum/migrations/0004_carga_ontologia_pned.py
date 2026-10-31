"""Ontologia curricular: unidade temática, objetos de conhecimento, área, competências
específicas (texto oficial da BNCC), eixo Educação Digital Escolar da PNED (Lei nº
14.533/2023, art. 3º), matriz analítica do projeto e sugestões automáticas de ligação
(não validadas). Só acrescenta ou atualiza; nada é apagado.
"""

from django.db import migrations


def load(apps, schema_editor):
    from apps.curriculum.loader import load_bncc, load_digital_and_dimensions

    Item = apps.get_model("curriculum", "CurriculumItem")
    load_bncc(Item, apps.get_model("curriculum", "CurriculumItemVersion"))
    load_digital_and_dimensions(Item, apps.get_model("curriculum", "SkillDimension"),
                                apps.get_model("curriculum", "ItemDimension"),
                                apps.get_model("curriculum", "CurriculumCorrespondence"))


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0003_ontologia_curricular"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

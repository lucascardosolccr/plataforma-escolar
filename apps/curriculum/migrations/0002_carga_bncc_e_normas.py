"""Carrega as competências gerais e as habilidades do Ensino Fundamental da BNCC
(texto do PDF oficial do MEC) e as referências normativas conferidas.

Só acrescenta linhas; desfazer a migração não apaga nada (itens podem estar
ligados a planejamentos e atividades).
"""

from django.db import migrations


def load(apps, schema_editor):
    from apps.curriculum.loader import load_bncc, load_references

    load_bncc(apps.get_model("curriculum", "CurriculumItem"))
    load_references(apps.get_model("curriculum", "NormativeReference"))


class Migration(migrations.Migration):

    dependencies = [
        ('curriculum', '0001_catalogo_curricular'),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]

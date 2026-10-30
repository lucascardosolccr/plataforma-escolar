"""Coordenadores que já existiam recebem designação "escola toda".

Antes do Prompt 14 a coordenação via a escola inteira. Sem esta migração,
eles perderiam o acesso de uma hora para a outra. A direção pode depois
restringir cada designação. Reverter apaga só as designações criadas aqui.
"""

from django.db import migrations
from django.utils import timezone

NOTE = "Criada automaticamente na atualização (acesso que já existia)."


def forwards(apps, schema_editor):
    User = apps.get_model("core", "User")
    Assignment = apps.get_model("coordination", "CoordinatorAssignment")
    today = timezone.localdate()
    for u in User.objects.filter(role="coordenacao", school__isnull=False):
        if not Assignment.objects.filter(coordinator=u).exists():
            Assignment.objects.create(school_id=u.school_id, coordinator=u, all_school=True,
                                      starts_on=today, area="Escola toda", notes=NOTE)


def backwards(apps, schema_editor):
    apps.get_model("coordination", "CoordinatorAssignment").objects.filter(notes=NOTE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("coordination", "0001_initial"),
        ("core", "0006_contato_e_identificacao_funcional"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]

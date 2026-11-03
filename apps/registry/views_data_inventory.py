"""O que a plataforma guarda sobre um estudante: base para a escola responder a um pedido do titular
(LGPD, art. 18, I e II, e art. 19).

Só a direção abre. O inventário conta registros que a secretaria e a administração não leem
(observações pedagógicas, apoio à inclusão), e dizer que eles existem já é informação sensível. A
consulta fica na auditoria.

A lista sai do próprio modelo: todo registro ligado ao estudante por chave estrangeira entra na conta.
Um módulo novo aparece aqui sem que alguém precise lembrar de incluí-lo. Registros de grupo ou de turma
(nota de rubrica do grupo, chamada sem o estudante) não entram, porque não são do estudante.
"""

from django.apps import apps as django_apps
from django.core.exceptions import PermissionDenied
from django.db.models import FileField
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.core.models import Role, audit_trail, create_audit_log

from .models import Student

SKIP_FIELDS = {"id", "school", "user"}
LABELS = {"created_at": "cadastrado em", "updated_at": "última alteração"}  # campos sem verbose_name no modelo


def can_open(user):
    return user.is_authenticated and user.role == Role.DIRECAO.value


def registration_fields(student):
    """[(rótulo, valor exibido)] do cadastro, na ordem do modelo."""
    rows = []
    for f in Student._meta.concrete_fields:
        if f.name in SKIP_FIELDS:
            continue
        value = getattr(student, f.name)
        if isinstance(f, FileField):
            shown = "sim" if value else "não"
        elif f.choices:
            shown = getattr(student, f"get_{f.name}_display")()
        elif hasattr(value, "hour"):
            shown = timezone.localtime(value).strftime("%d/%m/%Y %H:%M")
        elif hasattr(value, "strftime"):
            shown = value.strftime("%d/%m/%Y")
        else:
            shown = value if value not in (None, "") else "—"
        rows.append((LABELS.get(f.name, str(f.verbose_name)), shown))
    rows.append(("conta de acesso do estudante", "sim" if student.user_id else "não"))
    return rows


def inventory(student):
    """[{área, registro, quantidade}] de tudo o que está ligado ao estudante, só o que existe."""
    rows = []
    for rel in Student._meta.related_objects:
        model = rel.related_model
        n = model._default_manager.filter(**{rel.field.name: student}).count()
        if n:
            rows.append({"area": django_apps.get_app_config(model._meta.app_label).verbose_name,
                         "label": str(model._meta.verbose_name_plural), "count": n})
    n = audit_trail(student).count()
    if n:
        rows.append({"area": "Núcleo da plataforma", "label": "registros de auditoria sobre a ficha", "count": n})
    return sorted(rows, key=lambda r: (r["area"], r["label"]))


def student_data_inventory(request, student_id):
    user = request.user
    if not can_open(user):
        raise PermissionDenied
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    create_audit_log(user=user, action="view", request=request, target=student,
                     detail=f"Consultou o inventário de dados pessoais de {student.full_name} (LGPD)")
    guardians = [link.guardian for link in student.guardian_links.filter(status="aprovado").select_related("guardian")]
    return render(request, "registry/data_inventory.html", {
        "student": student, "fields": registration_fields(student), "rows": inventory(student),
        "guardians": guardians,
    })

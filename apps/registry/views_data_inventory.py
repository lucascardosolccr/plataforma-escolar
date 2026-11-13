"""O que a plataforma guarda sobre um estudante: base para a escola responder a um pedido do titular
(LGPD, art. 18, I e II, e art. 19).

Só a direção abre. O inventário conta registros que a secretaria e a administração não leem
(observações pedagógicas, apoio à inclusão), e dizer que eles existem já é informação sensível. A
consulta fica na auditoria.

A lista sai do próprio modelo: todo registro ligado ao estudante por chave estrangeira entra na conta.
Um módulo novo aparece aqui sem que alguém precise lembrar de incluí-lo. Registros de grupo ou de turma
(nota de rubrica do grupo, chamada sem o estudante) não entram, porque não são do estudante.
"""

import json

from django.apps import apps as django_apps
from django.core.exceptions import PermissionDenied
from django.db.models import FileField
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.text import slugify

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


# --------------------------------------------------------------------------
# Dossiê: o pacote de dados pessoais do estudante, para atender aos direitos de
# acesso (LGPD, art. 18, II) e de portabilidade (art. 18, V). O inventário acima
# diz o que a plataforma guarda e quanto; o dossiê extrai os valores num arquivo.
# Mesma introspecção do inventário, para que os dois nunca divirjam: toda tabela
# ligada ao estudante entra, e um módulo novo aparece sozinho.
#
# Fica com a direção, como o inventário: o dossiê reúne num só arquivo conteúdo
# que a secretaria e a administração não leem (observações pedagógicas, inclusão).
# O binário de fotos e documentos não entra no JSON — só o nome do arquivo —, e
# o id interno e qualquer hash de senha ficam de fora.
# --------------------------------------------------------------------------

DOSSIER_SKIP = {"id", "password"}


def _dossier_value(obj, field):
    """Valor de um campo pronto para o JSON: legível, serializável e sem binário."""
    value = getattr(obj, field.name)
    if isinstance(field, FileField):
        return value.name or None  # o caminho do arquivo; o conteúdo é entregue à parte
    if value is None or value == "":
        return None
    if field.choices:
        return getattr(obj, f"get_{field.name}_display")()
    if field.is_relation:
        return str(value)
    if hasattr(value, "hour"):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")
    if hasattr(value, "strftime"):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, (dict, list, bool, int, float, str)):
        return value
    return str(value)


def _dossier_record(obj, skip=()):
    """{rótulo em português: valor} dos campos concretos de um registro."""
    out = {}
    for f in obj._meta.concrete_fields:
        if f.name in DOSSIER_SKIP or f.name in skip:
            continue
        out[LABELS.get(f.name, str(f.verbose_name))] = _dossier_value(obj, f)
    return out


def build_dossier(student):
    """O dossiê completo do estudante como um dicionário serializável em JSON."""
    links = student.guardian_links.select_related("guardian")
    registros = []
    for rel in Student._meta.related_objects:
        model = rel.related_model
        itens = [_dossier_record(o, skip=(rel.field.name,))
                 for o in model._default_manager.filter(**{rel.field.name: student})]
        if itens:
            registros.append({
                "area": str(django_apps.get_app_config(model._meta.app_label).verbose_name),
                "registro": str(model._meta.verbose_name_plural),
                "quantidade": len(itens),
                "itens": itens,
            })
    registros.sort(key=lambda r: (r["area"], r["registro"]))
    return {
        "gerado_em": timezone.localtime().strftime("%d/%m/%Y %H:%M"),
        "finalidade": ("Pacote de dados pessoais do estudante para atender aos direitos de acesso "
                       "(LGPD, art. 18, II) e de portabilidade (art. 18, V). Fotos e documentos não "
                       "entram no arquivo: ficam listados pelo nome e são entregues à parte."),
        "escola": str(student.school),
        "estudante": student.full_name,
        "cadastro": _dossier_record(student, skip=("school", "user")),
        "responsaveis": [{
            "nome": link.guardian.get_full_name() or link.guardian.username,
            "email": link.guardian.email,
            "relacao": link.get_relation_display() if link.relation else "",
            "situacao": link.get_status_display(),
        } for link in links],
        "registros": registros,
        "auditoria": [{
            "quando": timezone.localtime(a.created_at).strftime("%d/%m/%Y %H:%M"),
            "acao": a.get_action_display(),
            "por": (a.user.get_full_name() or a.user.username) if a.user else "sistema",
            "detalhe": a.detail,
        } for a in audit_trail(student).order_by("created_at")],
    }


def student_dossier(request, student_id):
    user = request.user
    if not can_open(user):
        raise PermissionDenied
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    create_audit_log(user=user, action="export", request=request, target=student,
                     detail=f"Exportou o dossiê de dados pessoais de {student.full_name} (LGPD, art. 18 II/V)")
    payload = json.dumps(build_dossier(student), ensure_ascii=False, indent=2)
    filename = f"dossie-{slugify(student.full_name) or student.pk}-{timezone.localdate():%Y-%m-%d}.json"
    response = HttpResponse(payload, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

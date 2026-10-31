"""Regras do módulo de apoio: arquivos, histórico, avisos e orientações."""

import datetime
import hashlib
import io
import os
import re

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone

from .models import SupportCase, SupportDocument, SupportEvent, SupportNeed, SupportPlan, SupportSettings

ALLOWED = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
SIGNATURES = {".pdf": (b"%PDF-",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
              ".png": (b"\x89PNG\r\n\x1a\n",)}
# Conteúdo ativo em PDF: script, abertura automática de ação, arquivo
# embutido ou execução de programa. Laudo não precisa de nada disso.
PDF_ACTIVE = re.compile(rb"/(JavaScript|JS|Launch|EmbeddedFile|RichMedia|XFA)\b")
HARD_LIMIT_MB = 20


def case_for(student):
    case, _ = SupportCase.objects.get_or_create(student=student, defaults={"school": student.school})
    return case


def record(case, actor, action, status=None, note="", family=True):
    """Acrescenta ao histórico e, se for o caso, muda a situação da ficha."""
    old = case.status
    if status and status != old:
        case.status = status
        case.save(update_fields=["status", "updated_at"])
    return SupportEvent.objects.create(case=case, actor=actor, action=action[:200], from_status=old,
                                       to_status=case.status, note=note, visible_to_family=family)


def validate_upload(upload, school):
    """Confere tamanho, extensão, assinatura e conteúdo ativo. Imagens são
    regravadas sem metadados (EXIF/GPS). Devolve (bytes, content_type, ext)."""
    limit = min(SupportSettings.for_school(school).max_upload_mb or 10, HARD_LIMIT_MB)
    if upload is None:
        raise ValidationError("Escolha um arquivo.")
    if upload.size == 0:
        raise ValidationError("O arquivo está vazio.")
    if upload.size > limit * 1024 * 1024:
        raise ValidationError(f"O arquivo passa do limite de {limit} MB.")
    ext = os.path.splitext(upload.name or "")[1].lower()
    if ext not in ALLOWED:
        raise ValidationError("Envie PDF, JPG ou PNG.")
    data = b"".join(upload.chunks())
    if not data.startswith(SIGNATURES[ext]):
        raise ValidationError("O conteúdo do arquivo não corresponde ao formato informado.")
    if ext == ".pdf":
        if PDF_ACTIVE.search(data):
            raise ValidationError("O PDF tem conteúdo ativo (script, anexo embutido ou ação automática) e não foi "
                                  "aceito. Gere o PDF novamente (por exemplo, pela opção imprimir em PDF).")
        return data, ALLOWED[ext], ext
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
        fmt = "PNG" if ext == ".png" else "JPEG"
        if fmt == "JPEG" and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format=fmt, quality=90) if fmt == "JPEG" else img.save(out, format=fmt)
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ValidationError("A imagem está corrompida ou não é uma imagem válida.")
    return out.getvalue(), ALLOWED[ext], ext


def store_document(case, upload, *, source, user, kind="laudo", issued_on=None, issuer="", description="",
                   replaces=None):
    data, ctype, ext = validate_upload(upload, case.school)
    status = SupportDocument.Status.AWAITING if source == SupportDocument.Source.FAMILY else \
        SupportDocument.Status.RECEIVED
    doc = SupportDocument(case=case, original_name=os.path.basename(upload.name)[:200], content_type=ctype,
                          size=len(data), sha256=hashlib.sha256(data).hexdigest(), source=source, kind=kind,
                          issued_on=issued_on, issuer=issuer, description=description, status=status,
                          replaces=replaces, uploaded_by=user)
    doc.file.save(f"documento{ext}", ContentFile(data), save=False)
    doc.save()
    if replaces is not None and replaces.status != SupportDocument.Status.DISCARDED:
        replaces.status = SupportDocument.Status.REPLACED
        replaces.save(update_fields=["status"])
    return doc


def team_for(student):
    """Coordenação que alcança o estudante e direção da escola."""
    from apps.coordination.scope import reaches_student
    from apps.core.models import Role, User

    users = []
    for u in User.objects.filter(school=student.school, is_active=True,
                                 role__in=[Role.COORDENACAO.value, Role.DIRECAO.value]):
        if u.role == Role.DIRECAO.value or reaches_student(u, student):
            users.append(u)
    return users


def guardians_for(student):
    from apps.registry.models import GuardianLink

    return [l.guardian for l in GuardianLink.objects.filter(student=student, status="aprovado",
                                                            guardian__is_active=True).select_related("guardian")]


def notify(case, users, title, body, url):
    """Aviso sem diagnóstico: diz que há atualização e onde ver."""
    from apps.communication.models import Notification
    from apps.communication.services import notify_many

    notify_many(case.school, users, Notification.Kind.SUPPORT, title, body=body, url=url, student=case.student,
                priority=Notification.Priority.HIGH)


def case_url(case):
    return reverse("inclusion:case_detail", args=[case.student_id])


def audit(request, action, target, detail):
    from apps.core.models import create_audit_log

    create_audit_log(user=request.user, action=action, request=request, target=target, detail=detail)


def guidance(students):
    """Orientações que os professores podem ver, por estudante.

    Só necessidades marcadas para os professores e os campos de sala de aula do
    plano vigente. Sem categoria, sem laudo, sem notas da família.
    """
    ids = [s.pk for s in students]
    by_student = {}
    needs = SupportNeed.objects.filter(case__student_id__in=ids, active=True, share_with_teachers=True)
    for n in needs.select_related("case"):
        by_student.setdefault(n.case.student_id, {"needs": [], "plan": None})["needs"].append(n)
    plans = SupportPlan.objects.filter(case__student_id__in=ids, status__in=[SupportPlan.Status.ACTIVE,
                                                                             SupportPlan.Status.REVIEW])
    for p in plans.select_related("case").order_by("case_id", "-starts_on"):
        entry = by_student.setdefault(p.case.student_id, {"needs": [], "plan": None})
        if entry["plan"] is None:
            entry["plan"] = [(label, getattr(p, name)) for name, label in SupportPlan.PLAN_FIELDS
                             if name in SupportPlan.TEACHER_FIELDS and getattr(p, name)]
    return by_student


def students_with_guidance(class_group):
    """Quantos estudantes da turma têm orientação para os professores."""
    from apps.registry.models import Enrollment

    ids = list(Enrollment.objects.filter(class_group=class_group, status="ativo").values_list("student_id", flat=True))
    with_needs = set(SupportNeed.objects.filter(case__student_id__in=ids, active=True, share_with_teachers=True)
                     .values_list("case__student_id", flat=True))
    with_plan = set(SupportPlan.objects.filter(case__student_id__in=ids, status__in=[
        SupportPlan.Status.ACTIVE, SupportPlan.Status.REVIEW]).exclude(teacher_summary="")
        .values_list("case__student_id", flat=True))
    return len(with_needs | with_plan)


def discard_candidates(school, today=None):
    """Documentos cujo prazo de guarda venceu: estudante sem matrícula ativa
    há mais de ``retention_years`` anos (pela data de saída da última
    matrícula). Documentos de estudante ativo nunca entram."""
    from apps.registry.models import Enrollment

    today = today or timezone.localdate()
    years = SupportSettings.for_school(school).retention_years
    limit = today - datetime.timedelta(days=365 * years)
    docs = SupportDocument.objects.filter(case__school=school).exclude(status=SupportDocument.Status.DISCARDED)
    out = []
    for doc in docs.select_related("case__student"):
        enrs = list(Enrollment.objects.filter(student=doc.case.student))
        if any(e.status == "ativo" for e in enrs):
            continue
        ended = [e.ended_on for e in enrs if e.ended_on]
        if (ended and max(ended) <= limit) or (not enrs and doc.uploaded_at.date() <= limit):
            out.append(doc)
    return out


def discard(doc, user):
    """Apaga o arquivo e mantém o registro (nome, data, hash) de que existiu."""
    if doc.file:
        doc.file.delete(save=False)
    doc.file = ""
    doc.status = SupportDocument.Status.DISCARDED
    doc.discarded_by = user
    doc.discarded_at = timezone.now()
    doc.save(update_fields=["file", "status", "discarded_by", "discarded_at"])

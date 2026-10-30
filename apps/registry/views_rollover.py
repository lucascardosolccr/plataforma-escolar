"""Rematrícula em lote: leva os estudantes de uma turma para a turma do ano seguinte.

A matrícula de origem é encerrada como "concluída" (não editada) e uma nova é
aberta no ano de destino, na mesma transação por estudante. Quem fica retido
é simplesmente desmarcado e rematriculado depois, em outra turma de destino.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup
from apps.core.models import create_audit_log
from apps.core.params import id_param

from .models import Enrollment
from .views_import import can_import_students


def _origin_state(origin, today):
    """(pode encerrar?, aviso) conforme o fim do ano letivo da turma de origem.

    Encerrar a matrícula tira o estudante das listas da turma, então só vale
    depois do fim do ano. Sem data de fim cadastrada, a secretaria confirma.
    """
    end = origin.school_year.end_date
    if end and end >= today:
        return False, (
            f"O ano letivo {origin.school_year.name} termina em {end:%d/%m/%Y}. "
            "A rematrícula fica disponível depois dessa data, para que os estudantes "
            "não saiam das listas da turma antes do fim das aulas."
        )
    if not end:
        return True, (
            f"O ano letivo {origin.school_year.name} não tem data de fim cadastrada. "
            "Confirme abaixo que as aulas dele já terminaram."
        )
    return True, None


def enrollment_rollover(request):
    if not can_import_students(request.user):
        raise PermissionDenied
    school = request.user.school
    today = timezone.localdate()
    data = request.POST if request.method == "POST" else request.GET
    classes = (ClassGroup.objects.filter(school=school)
               .select_related("school_year").order_by("-school_year__name", "name"))
    origin = None
    origin_id = id_param(request, "origem", data)
    if origin_id:
        origin = get_object_or_404(classes, pk=origin_id)

    ctx = {"classes": classes, "origin": origin}
    if origin is None:
        return render(request, "registry/rollover.html", ctx)

    can_close, warning = _origin_state(origin, today)
    enrollments = list(Enrollment.objects.filter(class_group=origin, status="ativo")
                       .select_related("student").order_by("student__first_name", "student__last_name"))
    destinations = [c for c in classes if c.school_year_id != origin.school_year_id]
    ctx.update({"can_close": can_close, "warning": warning, "enrollments": enrollments,
                "destinations": destinations,
                "needs_confirmation": can_close and not origin.school_year.end_date})

    if request.method == "POST" and can_close:
        errors = []
        dest_id = id_param(request, "destino", data)
        dest = next((c for c in destinations if str(c.pk) == dest_id), None)
        if dest is None:
            errors.append("Escolha a turma de destino, de outro ano letivo.")
        chosen = set(data.getlist("ids"))
        selected = [e for e in enrollments if str(e.pk) in chosen]
        if not selected:
            errors.append("Marque pelo menos um estudante.")
        if ctx["needs_confirmation"] and data.get("confirmo") != "1":
            errors.append("Confirme que as aulas do ano de origem já terminaram.")
        if errors:
            ctx.update({"errors": errors, "dest_id": dest_id or "", "chosen": chosen})
            return render(request, "registry/rollover.html", ctx)

        ended_on = origin.school_year.end_date or today
        moved, skipped = [], []
        for e in selected:
            with transaction.atomic():
                # Relê dentro da transação: um segundo envio do mesmo formulário
                # não rematricula duas vezes nem reabre o que já foi encerrado.
                current = Enrollment.objects.select_for_update().get(pk=e.pk)
                taken = Enrollment.objects.filter(school=school, student_id=e.student_id,
                                                  school_year=dest.school_year, status="ativo").exists()
                if current.status != "ativo" or taken:
                    skipped.append(e.student.full_name)
                    continue
                current.status = "concluido"
                current.ended_on = ended_on
                current.save(update_fields=["status", "ended_on"])
                new = Enrollment.objects.create(
                    school=school, student=e.student, class_group=dest, school_year=dest.school_year,
                    enrollment_number=e.enrollment_number, status="ativo",
                )
                create_audit_log(
                    user=request.user, action="create", request=request, target=new,
                    detail=(f"Rematriculou {e.student} de {origin} ({origin.school_year}) "
                            f"para {dest} ({dest.school_year})"),
                )
            moved.append(e.student.full_name)
        if moved:
            messages.success(request, f"{len(moved)} estudante(s) rematriculado(s) em {dest.name} "
                                      f"({dest.school_year.name}). A matrícula de {origin.school_year.name} "
                                      "foi encerrada como concluída, com o histórico preservado.")
        if skipped:
            messages.warning(request, "Sem alteração (já tinham matrícula ativa no ano de destino): "
                                      + ", ".join(skipped) + ".")
        return redirect(f"{request.path}?origem={origin.pk}")

    ctx.update({"dest_id": "", "chosen": None})
    return render(request, "registry/rollover.html", ctx)

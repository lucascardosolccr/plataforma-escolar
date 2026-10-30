"""Telas da importação de estudantes por planilha e das fotos em lote."""

import json
import os

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.photos import save_photo

from . import importer
from .models import ImportBatch, Student

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def can_import_students(user):
    """Importação em massa e fotos em lote: secretaria e administração."""
    return user.is_authenticated and user.role in (Role.SECRETARIA.value, Role.ADMIN.value)


def _require(user):
    if not can_import_students(user):
        raise PermissionDenied


def import_home(request):
    _require(request.user)
    error = None
    if request.method == "POST":
        upload = request.FILES.get("file")
        if not upload:
            error = "Escolha a planilha antes de enviar."
        else:
            try:
                headers, rows, warnings = importer.read_table(upload)
            except importer.ImportFileError as exc:
                error = str(exc)
            else:
                results = importer.validate_rows(request.user.school, rows)
                batch = ImportBatch.objects.create(
                    school=request.user.school, created_by=request.user,
                    filename=os.path.basename(upload.name)[:200], total=len(results),
                    rows=json.dumps(results, ensure_ascii=False, default=str),
                    error_count=sum(1 for r in results if r["status"] == "erro"),
                )
                for w in warnings:
                    messages.warning(request, w)
                return redirect("student_import_detail", batch_id=batch.pk)
    batches = paginate(request, ImportBatch.objects.filter(school=request.user.school)
                       .select_related("created_by"), per_page=15)
    return render(request, "registry/import_home.html", {
        "error": error, "batches": batches, "page": batches, "columns": importer.COLUMNS,
        "max_rows": importer.MAX_ROWS,
    })


def import_template(request):
    _require(request.user)
    resp = HttpResponse(importer.template_xlsx(), content_type=XLSX)
    resp["Content-Disposition"] = 'attachment; filename="modelo-importacao-estudantes.xlsx"'
    return resp


def import_detail(request, batch_id):
    _require(request.user)
    batch = get_object_or_404(ImportBatch, pk=batch_id, school=request.user.school)
    results = json.loads(batch.rows or "[]")
    summary = importer.summarize(results)
    show = request.GET.get("ver", "")
    shown = [r for r in results if not show or r["status"] == show]
    return render(request, "registry/import_detail.html", {
        "batch": batch, "summary": summary, "rows": shown[:500], "truncated": len(shown) > 500,
        "show": show, "modes": ImportBatch.Mode.choices,
        "filters": [("", "Todas", summary["total"]), ("novo", "Novos", summary["novo"]),
                    ("alterar", "Com alteração", summary["alterar"]), ("igual", "Sem mudança", summary["igual"]),
                    ("erro", "Com erro", summary["erro"])],
    })


@require_POST
def import_confirm(request, batch_id):
    _require(request.user)
    batch = get_object_or_404(ImportBatch, pk=batch_id, school=request.user.school)
    if batch.status != ImportBatch.Status.PREVIEW:
        messages.error(request, "Esta importação já foi concluída ou cancelada.")
        return redirect("student_import_detail", batch_id=batch.pk)
    if request.POST.get("action") == "cancel":
        batch.status = ImportBatch.Status.CANCELED
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "finished_at"])
        create_audit_log(user=request.user, action="update", request=request, target=batch,
                         detail=f"Cancelou a importação da planilha {batch.filename}")
        messages.info(request, "Importação cancelada. Nenhum dado foi gravado.")
        return redirect("student_import")
    mode = request.POST.get("mode")
    if mode not in dict(ImportBatch.Mode.choices):
        messages.error(request, "Escolha como tratar os alunos já cadastrados.")
        return redirect("student_import_detail", batch_id=batch.pk)
    pending_changes = sum(1 for r in json.loads(batch.rows or "[]") if r["status"] == "alterar")
    if mode == ImportBatch.Mode.UPDATE and pending_changes and request.POST.get("confirm_updates") != "1":
        messages.error(request, f"Confirme que revisou as alterações em {pending_changes} aluno(s) já cadastrado(s).")
        return redirect("student_import_detail", batch_id=batch.pk)
    batch.mode = mode
    counts = importer.apply_rows(batch, request.user, request)
    messages.success(
        request,
        f"Importação concluída: {counts['created']} cadastrado(s), {counts['updated']} atualizado(s), "
        f"{counts['skipped']} ignorado(s), {counts['error']} com erro.",
    )
    return redirect("student_import_detail", batch_id=batch.pk)


def import_rejected(request, batch_id):
    _require(request.user)
    batch = get_object_or_404(ImportBatch, pk=batch_id, school=request.user.school)
    # Traz nomes e nascimentos de crianças: fica registrado como exportação.
    create_audit_log(user=request.user, action="export", request=request, target=batch,
                     detail=f"Baixou as linhas com erro da importação {batch.filename}")
    resp = HttpResponse(importer.rejected_xlsx(batch), content_type=XLSX)
    resp["Content-Disposition"] = f'attachment; filename="rejeitados-importacao-{batch.pk}.xlsx"'
    return resp


MAX_BATCH_PHOTOS = 200


def photo_batch(request):
    """Fotos em lote: o nome de cada arquivo é o código do aluno (2026001.jpg).

    A associação é só por código exato. Nunca por nome do aluno ou
    semelhança: uma foto trocada identificaria a criança errada.
    """
    _require(request.user)
    report = None
    if request.method == "POST":
        files = request.FILES.getlist("photos")[:MAX_BATCH_PHOTOS]
        codes = {s.code: s for s in Student.objects.filter(school=request.user.school).exclude(code="")}
        report = {"ok": [], "no_match": [], "invalid": []}
        for f in files:
            stem = os.path.splitext(os.path.basename(f.name))[0].strip()
            student = codes.get(stem)
            if student is None:
                report["no_match"].append(f.name)
                continue
            try:
                with transaction.atomic():
                    save_photo(student, "photo", f, name_hint=f"aluno-{student.pk}")
                    student.save(update_fields=["photo", "updated_at"])
                    create_audit_log(user=request.user, action="update", request=request, target=student,
                                     detail=f"Atualizou a fotografia de {student.full_name} (envio em lote)")
            except ValidationError as exc:
                report["invalid"].append((f.name, " ".join(exc.messages)))
                continue
            report["ok"].append((f.name, student))
        if len(request.FILES.getlist("photos")) > MAX_BATCH_PHOTOS:
            messages.warning(request, f"Só as primeiras {MAX_BATCH_PHOTOS} fotos foram processadas neste envio.")
    return render(request, "registry/photo_batch.html", {"report": report, "max": MAX_BATCH_PHOTOS})

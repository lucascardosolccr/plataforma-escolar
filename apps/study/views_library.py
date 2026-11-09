"""Biblioteca pedagógica da escola (Prompt 9 §8.7).

Reúne os materiais de estudo que os professores marcaram como compartilhados.
Só a equipe pedagógica (professor, coordenação, direção) entra; a família vê
um material apenas quando ele chega numa prova da turma do filho. Material
retirado da prova de origem sai também da biblioteca.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import id_param, safe_next
from apps.core.uploads import attachment_content_type

from . import access
from .models import ExamGuide, GuideUpdate, LibraryFavorite, StudyMaterial
from .services import content_changed, log

LIBRARY_ROLES = (Role.PROFESSOR.value, Role.COORDENACAO.value, Role.DIRECAO.value)


def _require_library(user):
    if not (user.is_authenticated and user.role in LIBRARY_ROLES):
        raise PermissionDenied


def _shared(user):
    return StudyMaterial.objects.filter(guide__school=user.school, shared=True, removed_at__isnull=True)


def library(request):
    user = request.user
    _require_library(user)
    qs = _shared(user).select_related("guide__subject", "guide__class_group", "created_by").prefetch_related(
        "curriculum").annotate(fav=Exists(LibraryFavorite.objects.filter(user=user, material=OuterRef("pk"))))
    q = (request.GET.get("q") or "").strip()[:80]
    for term in q.split()[:5]:
        qs = qs.filter(Q(title__icontains=term) | Q(description__icontains=term) | Q(tags__icontains=term)
                       | Q(author__icontains=term) | Q(curriculum__code__iexact=term)).distinct()
    kind = request.GET.get("tipo")
    if kind in StudyMaterial.Kind.values:
        qs = qs.filter(kind=kind)
    subject = id_param(request, "disciplina")
    if subject:
        qs = qs.filter(guide__subject_id=subject)
    only_fav = request.GET.get("favoritos") == "1"
    if only_fav:
        qs = qs.filter(fav=True)
    from apps.academics.models import Subject

    page = paginate(request, qs.order_by("-created_at"))
    my_guides = []
    if user.role == Role.PROFESSOR.value:
        my_guides = list(access.staff_queryset(user).exclude(status=ExamGuide.Status.ARCHIVED)
                         .select_related("class_group", "subject").order_by("-exam_date")[:30])
        my_guides = [g for g in my_guides if access.can_manage(user, g)]
    return render(request, "study/library.html", {
        "materials": page, "page": page, "q": q, "kind": kind, "subject": subject, "only_fav": only_fav,
        "kinds": StudyMaterial.Kind.choices,
        "subjects": Subject.objects.filter(school=user.school, pk__in=_shared(user).values("guide__subject")),
        "my_guides": my_guides,
    })


def library_file(request, material_id):
    user = request.user
    _require_library(user)
    m = get_object_or_404(_shared(user), pk=material_id)
    if not m.file:
        raise Http404
    return FileResponse(m.file.open("rb"), content_type=attachment_content_type(m.file.name), as_attachment=True,
                        filename=m.original_name or "material")


def library_favorite(request, material_id):
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    _require_library(user)
    m = get_object_or_404(_shared(user), pk=material_id)
    fav, created = LibraryFavorite.objects.get_or_create(user=user, material=m)
    if not created:
        fav.delete()
    # Só endereço desta plataforma: o "next" vem do formulário e poderia apontar para fora.
    return redirect(safe_next(request, "study:library"))


def library_use(request, material_id):
    """Copia o material para uma prova do próprio professor (arquivo copiado, não compartilhado)."""
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    _require_library(user)
    m = get_object_or_404(_shared(user), pk=material_id)
    guide = get_object_or_404(ExamGuide, pk=id_param(request, "prova", source=request.POST) or 0, school=user.school)
    if not access.can_manage(user, guide):
        raise PermissionDenied
    with transaction.atomic():
        copy = StudyMaterial.objects.get(pk=m.pk)
        copy.pk = None
        copy.guide, copy.topic, copy.created_by = guide, None, user
        copy.shared, copy.broken_reports, copy.broken_reported_at = False, 0, None
        if m.file:
            with m.file.open("rb") as fh:
                copy.file = ContentFile(fh.read(), name=m.original_name or "material")
        copy.save()
        # Habilidades: só as que também estão nos tópicos desta prova.
        copy.curriculum.set(m.curriculum.filter(exam_topics__guide=guide).distinct())
        text = f"Material incluído: {copy.title}"
        if guide.status == ExamGuide.Status.PUBLISHED:
            content_changed(guide, GuideUpdate.Kind.MATERIAL_ADDED, text, user)
        else:
            log(guide, GuideUpdate.Kind.MATERIAL_ADDED, text, user)
        create_audit_log(user=user, action="create", request=request, target=guide,
                         detail=f"Usou o material da biblioteca #{m.pk} na prova {guide.title}")
    messages.success(request, f"“{copy.title}” foi copiado para “{guide.title}”. Ligue-o a um tópico se quiser.")
    return redirect("study:material_edit", pk=guide.pk, material_id=copy.pk)

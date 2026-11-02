from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.academics.permissions import teacher_pairs
from apps.communication.family_events import notify_family
from apps.communication.models import Notification
from apps.communication.services import notify
from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import id_param
from apps.core.uploads import attachment_content_type
from apps.registry.models import Student

from . import access, plan, services
from .forms import AnswerForm, GuideForm, MaterialForm, QuestionForm, TopicForm
from .models import ExamGuide, ExamTopic, GuideUpdate, StudyMaterial, StudyQuestion, TopicCheck


def _require(cond):
    if not cond:
        raise PermissionDenied


def _log(request, action, target, detail):
    create_audit_log(user=request.user, action=action, request=request, target=target, detail=detail)


def _guide(request, pk):
    guide = get_object_or_404(ExamGuide.objects.select_related("class_group", "subject", "evaluation", "created_by"),
                              pk=pk, school=request.user.school)
    _require(access.can_view(request.user, guide))
    return guide


def _managed(request, pk):
    guide = get_object_or_404(ExamGuide.objects.select_related("class_group", "subject"), pk=pk,
                              school=request.user.school)
    _require(access.can_manage(request.user, guide))
    return guide


def _sync_curriculum(guide):
    """As habilidades da prova são as dos tópicos (uma fonte só)."""
    from apps.curriculum.models import CurriculumItem

    guide.curriculum.set(CurriculumItem.objects.filter(exam_topics__guide=guide).distinct())


def _family_children(user):
    from apps.registry.models import GuardianLink

    if user.role == Role.ESTUDANTE.value:
        from apps.pedagogy.access import own_student

        s = own_student(user)
        return [s] if s else []
    links = GuardianLink.objects.filter(guardian=user, status="aprovado").select_related("student")
    return sorted((l.student for l in links), key=lambda s: (s.first_name, s.last_name))


# --------------------------------------------------------------------------- lista
def guide_list(request):
    user = request.user
    today = timezone.localdate()
    when = "anteriores" if request.GET.get("quando") == "anteriores" else "proximas"
    if access.is_family(user):
        from apps.pedagogy.access import enrollments_by_student, reaches

        children = _family_children(user)
        by = enrollments_by_student([c.pk for c in children])
        guides = access.family_queryset(user).select_related("class_group", "subject").order_by("exam_date")
        guides = guides.filter(exam_date__lt=today) if when == "anteriores" else guides.filter(exam_date__gte=today)
        rows = []
        for g in guides:
            for child in children:
                if reaches(by.get(child.pk, ()), g):
                    rows.append({"guide": g, "student": child})
        if when == "anteriores":
            rows.reverse()
        return render(request, "study/list_family.html", {
            "rows": rows, "when": when, "children": children,
            "is_student": user.role == Role.ESTUDANTE.value, "today": today})
    _require(user.role in (Role.PROFESSOR.value, Role.COORDENACAO.value, Role.DIRECAO.value))
    qs = access.staff_queryset(user).select_related("class_group", "subject").annotate(
        n_topics=Count("topics", distinct=True),
        n_open=Count("questions", filter=Q(questions__answer=""), distinct=True))
    qs = qs.filter(exam_date__lt=today).order_by("-exam_date") if when == "anteriores" else \
        qs.filter(exam_date__gte=today).order_by("exam_date")
    turma = id_param(request, "turma")
    if turma:
        qs = qs.filter(class_group_id=turma)
    page = paginate(request, qs)
    return render(request, "study/list_staff.html", {
        "guides": page, "page": page, "when": when, "can_create": access.can_create(user)})


# --------------------------------------------------------------------- cadastro
def guide_create(request):
    user = request.user
    _require(access.can_create(user))
    form = GuideForm(request.POST or None, user=user)
    ev_id = id_param(request, "avaliacao")
    if request.method != "POST" and ev_id:
        ev = form.fields["evaluation"].queryset.filter(pk=ev_id).first()
        if ev:
            form.initial.update({"evaluation": ev.pk, "class_group": ev.class_group_id, "subject": ev.subject_id,
                                 "title": ev.title, "exam_date": ev.date})
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            guide = form.save(commit=False)
            guide.school = user.school
            guide.created_by = user
            guide.save()
            _log(request, "create", guide, f"Criou os conteúdos da prova {guide.title}")
        messages.success(request, "Rascunho criado. Acrescente os tópicos e os materiais e depois publique.")
        return redirect("study:detail", pk=guide.pk)
    return render(request, "study/guide_form.html", {"form": form, "obj": None})


def guide_edit(request, pk):
    user = request.user
    guide = _managed(request, pk)
    old_date = guide.exam_date
    form = GuideForm(request.POST or None, instance=guide, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # Trava otimista: só grava se ninguém gravou desde que a tela abriu.
            changed = ExamGuide.objects.filter(pk=guide.pk, version=form.cleaned_data.get("version") or guide.version) \
                .update(version=F("version") + 1)
            if not changed:
                messages.error(request, "Outra pessoa salvou estes conteúdos enquanto você editava. Nada foi gravado.")
                return redirect("study:detail", pk=guide.pk)
            # O formulário grava a instância inteira: sem isto, a versão antiga
            # carregada na memória voltaria por cima do incremento acima.
            form.instance.version = (form.cleaned_data.get("version") or guide.version) + 1
            guide = form.save()
            _log(request, "update", guide, "Alterou os conteúdos da prova: "
                 + ", ".join(form.fields[f].label.lower() for f in form.changed_data if f != "version"))
            services.date_changed(guide, old_date, user)
            if guide.status == ExamGuide.Status.PUBLISHED and {"guidance", "description", "criteria"} & set(
                    form.changed_data):
                services.content_changed(guide, GuideUpdate.Kind.EDITED, "Orientações de estudo atualizadas.", user)
        messages.success(request, "Conteúdos atualizados.")
        return redirect("study:detail", pk=guide.pk)
    return render(request, "study/guide_form.html", {"form": form, "obj": guide})


def guide_status(request, pk, action):
    if request.method != "POST":
        raise PermissionDenied
    guide = _managed(request, pk)
    with transaction.atomic():
        if action == "publicar":
            if not guide.topics.exists():
                messages.error(request, "Acrescente pelo menos um tópico antes de publicar.")
                return redirect("study:detail", pk=guide.pk)
            guide.status = ExamGuide.Status.PUBLISHED
            guide.save(update_fields=["status", "updated_at"])
            if not guide.updates.filter(kind=GuideUpdate.Kind.PUBLISHED).exists():
                services.log(guide, GuideUpdate.Kind.PUBLISHED, "Conteúdos publicados para a turma.", request.user)
            avisou = services.announce(guide)
            msg = ("Publicado. A turma e as famílias foram avisadas." if avisou else
                   f"Publicado. A turma passa a ver em {guide.published_date:%d/%m/%Y} e é avisada nesse dia.")
        elif action == "arquivar":
            guide.status = ExamGuide.Status.ARCHIVED
            guide.save(update_fields=["status", "updated_at"])
            msg = "Arquivado: sai das listas da turma. Nada foi apagado."
        elif action == "reabrir":
            guide.status = ExamGuide.Status.PUBLISHED if guide.notified_at else ExamGuide.Status.DRAFT
            guide.save(update_fields=["status", "updated_at"])
            msg = "Reaberto."
        else:
            raise Http404
        _log(request, "update", guide, f"Conteúdos da prova {guide.title}: {action}")
    messages.success(request, msg)
    return redirect("study:detail", pk=guide.pk)


def guide_reuse(request, pk):
    """Copia a estrutura (tópicos e materiais) para outra turma do professor, como rascunho."""
    user = request.user
    source = get_object_or_404(ExamGuide, pk=pk, school=user.school)
    _require(access.can_view(user, source) and access.can_create(user))
    pairs = sorted(teacher_pairs(user, edit=True))
    from apps.academics.models import ClassGroup, Subject

    classes = {c.pk: c for c in ClassGroup.objects.filter(pk__in={p[0] for p in pairs})}
    subjects = {s.pk: s for s in Subject.objects.filter(pk__in={p[1] for p in pairs})}
    options = [(f"{c}-{s}", f"{classes[c]} · {subjects[s]}") for c, s in pairs if c in classes and s in subjects]
    if request.method == "POST":
        try:
            cg_id, subj_id = (int(x) for x in request.POST.get("par", "").split("-"))
        except ValueError:
            cg_id = subj_id = None
        if (cg_id, subj_id) not in set(pairs):
            messages.error(request, "Escolha uma turma e disciplina da sua atribuição.")
            return redirect("study:reuse", pk=source.pk)
        with transaction.atomic():
            copy = ExamGuide.objects.create(
                school=user.school, class_group_id=cg_id, subject_id=subj_id, title=source.title,
                exam_date=source.exam_date if source.exam_date >= timezone.localdate() else timezone.localdate(),
                description=source.description, guidance=source.guidance, criteria=source.criteria,
                prep_time=source.prep_time, created_by=user)
            topic_map = {}
            for t in source.topics.prefetch_related("curriculum"):
                nt = ExamTopic.objects.create(guide=copy, title=t.title, description=t.description,
                                              priority=t.priority, level=t.level,
                                              prerequisite_notes=t.prerequisite_notes, order=t.order)
                nt.curriculum.set(t.curriculum.all())
                topic_map[t.pk] = nt
            for m in source.active_materials:
                nm = StudyMaterial.objects.get(pk=m.pk)
                nm.pk = None
                nm.guide, nm.topic = copy, topic_map.get(m.topic_id)
                nm.created_by, nm.broken_reports, nm.broken_reported_at = user, 0, None
                if m.file:
                    from django.core.files.base import ContentFile

                    with m.file.open("rb") as fh:
                        nm.file = ContentFile(fh.read(), name=m.original_name or "material")
                nm.save()
                nm.curriculum.set(m.curriculum.all())
            _sync_curriculum(copy)
            _log(request, "create", copy, f"Reutilizou os conteúdos da prova {source.title} (#{source.pk})")
        messages.success(request, "Cópia criada como rascunho. Confira a data da prova e os materiais.")
        return redirect("study:edit", pk=copy.pk)
    return render(request, "study/reuse.html", {"source": source, "options": options})


# ----------------------------------------------------------------- tópicos e materiais
def topic_form(request, pk, topic_id=None):
    user = request.user
    guide = _managed(request, pk)
    topic = get_object_or_404(ExamTopic, pk=topic_id, guide=guide) if topic_id else None
    form = TopicForm(request.POST or None, instance=topic, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            t = form.save(commit=False)
            t.guide = guide
            t.save()
            form.save_m2m()
            _sync_curriculum(guide)
            if guide.status == ExamGuide.Status.PUBLISHED:
                services.content_changed(guide, GuideUpdate.Kind.TOPIC,
                                         f"Tópico {'alterado' if topic else 'incluído'}: {t.title}", user)
        messages.success(request, "Tópico salvo.")
        return redirect("study:detail", pk=guide.pk)
    return render(request, "study/topic_form.html", {"form": form, "guide": guide, "obj": topic})


def topic_delete(request, pk, topic_id):
    if request.method != "POST":
        raise PermissionDenied
    guide = _managed(request, pk)
    topic = get_object_or_404(ExamTopic, pk=topic_id, guide=guide)
    with transaction.atomic():
        title = topic.title
        topic.delete()
        _sync_curriculum(guide)
        _log(request, "delete", guide, f"Retirou o tópico {title} da prova {guide.title}")
        if guide.status == ExamGuide.Status.PUBLISHED:
            services.content_changed(guide, GuideUpdate.Kind.TOPIC, f"Tópico retirado: {title}", request.user)
    messages.success(request, "Tópico retirado.")
    return redirect("study:detail", pk=guide.pk)


def material_form(request, pk, material_id=None, replace=False):
    user = request.user
    guide = _managed(request, pk)
    old = get_object_or_404(StudyMaterial, pk=material_id, guide=guide, removed_at__isnull=True) if material_id else None
    instance = None if replace else old
    initial = {}
    if replace and old:
        initial = {f: getattr(old, f) for f in ("kind", "title", "description", "why", "url", "author", "duration",
                                                 "segment", "guiding_questions", "follow_up", "accessibility",
                                                 "publisher", "edition_year", "pages", "access_type", "alternative",
                                                 "order")}
        initial.update({"topic": old.topic_id, "curriculum": list(old.curriculum.values_list("pk", flat=True))})
    form = MaterialForm(request.POST or None, request.FILES or None, instance=instance, guide=guide,
                        initial=initial or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            m = form.save(commit=False)
            m.guide = guide
            if not m.pk:
                m.created_by = user
            m.save()
            form.save_m2m()
            published = guide.status == ExamGuide.Status.PUBLISHED
            if replace and old:
                old.removed_at, old.removed_by, old.replaced_by = timezone.now(), user, m
                old.save(update_fields=["removed_at", "removed_by", "replaced_by"])
                text, kind = f"Material substituído: {old.title} → {m.title}", GuideUpdate.Kind.MATERIAL_REPLACED
            elif old:
                text, kind = f"Material atualizado: {m.title}", GuideUpdate.Kind.MATERIAL_ADDED
            else:
                text, kind = f"Material incluído: {m.title}", GuideUpdate.Kind.MATERIAL_ADDED
            _log(request, "update", guide, f"{text} (prova {guide.title})")
            if published:
                services.content_changed(guide, kind, text, user)
            else:
                services.log(guide, kind, text, user)
        messages.success(request, "Material salvo.")
        return redirect("study:detail", pk=guide.pk)
    return render(request, "study/material_form.html",
                  {"form": form, "guide": guide, "obj": instance, "replacing": old if replace else None})


def material_remove(request, pk, material_id):
    if request.method != "POST":
        raise PermissionDenied
    guide = _managed(request, pk)
    m = get_object_or_404(StudyMaterial, pk=material_id, guide=guide, removed_at__isnull=True)
    with transaction.atomic():
        m.removed_at, m.removed_by = timezone.now(), request.user
        m.save(update_fields=["removed_at", "removed_by"])
        text = f"Material retirado: {m.title}"
        _log(request, "update", guide, f"{text} (prova {guide.title})")
        if guide.status == ExamGuide.Status.PUBLISHED:
            services.content_changed(guide, GuideUpdate.Kind.MATERIAL_REMOVED, text, request.user)
        else:
            services.log(guide, GuideUpdate.Kind.MATERIAL_REMOVED, text, request.user)
    messages.success(request, "Material retirado da lista. Ele continua no histórico de atualizações.")
    return redirect("study:detail", pk=guide.pk)


def material_file(request, pk, material_id):
    """Download conferido no servidor: material retirado não é mais entregue."""
    guide = _guide(request, pk)
    m = get_object_or_404(StudyMaterial, pk=material_id, guide=guide)
    if m.removed_at and not access.can_manage(request.user, guide):
        raise Http404("Este material foi retirado pelo professor.")
    if not m.file:
        raise Http404("Material sem arquivo.")
    return FileResponse(m.file.open("rb"), content_type=attachment_content_type(m.file.name),
                        as_attachment=True, filename=m.original_name or "material")


def material_report(request, pk, material_id):
    """A família avisa que um link não abre. Um aviso ao professor por dia."""
    if request.method != "POST":
        raise PermissionDenied
    guide = _guide(request, pk)
    _require(access.is_family(request.user))
    m = get_object_or_404(StudyMaterial, pk=material_id, guide=guide, removed_at__isnull=True)
    _require(bool(m.url))
    StudyMaterial.objects.filter(pk=m.pk).update(broken_reports=F("broken_reports") + 1,
                                                 broken_reported_at=timezone.now())
    if guide.created_by_id:
        notify(guide.school, guide.created_by, Notification.Kind.EXAM, f"Link que não abre: {m.title}",
               body=f"Conteúdos da prova “{guide.title}”, turma {guide.class_group}.",
               url=reverse("study:detail", args=[guide.pk]),
               dedupe_key=f"guia-link-{m.pk}-{timezone.localdate():%Y%m%d}")
    messages.success(request, "Obrigado. O professor foi avisado de que o link não abre.")
    return redirect("study:detail", pk=guide.pk)


def material_report_clear(request, pk, material_id):
    if request.method != "POST":
        raise PermissionDenied
    guide = _managed(request, pk)
    StudyMaterial.objects.filter(pk=material_id, guide=guide).update(broken_reports=0, broken_reported_at=None)
    messages.success(request, "Aviso de link resolvido.")
    return redirect("study:detail", pk=guide.pk)


# ------------------------------------------------------------------ autorrelato e dúvidas
def topic_check(request, pk, topic_id):
    """O próprio estudante marca como está no tópico (autorrelato)."""
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    guide = _guide(request, pk)
    _require(user.role == Role.ESTUDANTE.value)
    topic = get_object_or_404(ExamTopic, pk=topic_id, guide=guide)
    status = request.POST.get("status")
    student_ids = access.family_students(user, guide)
    _require(len(student_ids) == 1)
    if status in TopicCheck.Status.values:
        TopicCheck.objects.update_or_create(topic=topic, student_id=student_ids[0], defaults={"status": status})
    elif status == "limpar":
        TopicCheck.objects.filter(topic=topic, student_id=student_ids[0]).delete()
    return redirect(reverse("study:detail", args=[guide.pk]) + "#como-estou")


def question_add(request, pk):
    if request.method != "POST":
        raise PermissionDenied
    user = request.user
    guide = _guide(request, pk)
    _require(access.is_family(user))
    allowed = access.family_students(user, guide)
    sid = id_param(request, "estudante", source=request.POST)
    student_id = int(sid) if sid else (allowed[0] if len(allowed) == 1 else None)
    _require(student_id in allowed)
    form = QuestionForm(request.POST, guide=guide)
    if form.is_valid():
        q = form.save(commit=False)
        q.guide, q.student_id, q.author = guide, student_id, user
        q.save()
        if guide.created_by_id:
            notify(guide.school, guide.created_by, Notification.Kind.EXAM, f"Nova dúvida: {guide.title}",
                   body=q.text[:140], url=reverse("study:detail", args=[guide.pk]) + "#duvidas",
                   dedupe_key=f"guia-duvida-{q.pk}")
        messages.success(request, "Dúvida enviada ao professor. A resposta aparece aqui.")
    else:
        messages.error(request, "Escreva a dúvida antes de enviar.")
    return redirect("study:detail", pk=guide.pk)


def question_answer(request, pk, question_id):
    if request.method != "POST":
        raise PermissionDenied
    guide = _managed(request, pk)
    q = get_object_or_404(StudyQuestion, pk=question_id, guide=guide)
    form = AnswerForm(request.POST)
    if form.is_valid():
        q.answer, q.answered_by, q.answered_at = form.cleaned_data["answer"], request.user, timezone.now()
        q.save(update_fields=["answer", "answered_by", "answered_at"])
        notify_family(q.student, "conteudo_prova", f"Dúvida respondida: {guide.title}",
                      url=reverse("study:detail", args=[guide.pk]), dedupe_key=f"guia-resposta-{q.pk}")
        messages.success(request, "Resposta enviada.")
    return redirect(reverse("study:detail", args=[guide.pk]) + "#duvidas")


# ------------------------------------------------------------------------- detalhe
def guide_detail(request, pk):
    user = request.user
    guide = _guide(request, pk)
    topics = list(guide.topics.prefetch_related("curriculum"))
    materials = guide.active_materials
    ctx = {"guide": guide, "topics": topics, "materials": materials,
           "updates": list(guide.updates.all()[:15]), "today": timezone.localdate()}
    if access.is_family(user):
        return render(request, "study/detail_family.html", {**ctx, **_family_context(user, guide, topics)})
    return render(request, "study/detail_staff.html", {**ctx, **_staff_context(user, guide, topics)})


def _family_context(user, guide, topics):
    from apps.cognitio.models import MasteryScale

    students = list(Student.objects.filter(pk__in=access.family_students(user, guide)).order_by("first_name"))
    share = MasteryScale.for_school(guide.school).share_with_family
    per_student = []
    for s in students:
        checks = {c.topic_id: c for c in TopicCheck.objects.filter(student=s, topic__guide=guide)}
        for t in topics:
            t.my_check = checks.get(t.pk)
        p = plan.preparation_plan(guide, s, detailed=False, personalize=share)
        if not share:
            p["note"] = ("Plano geral: segue a prioridade indicada pelo professor. A escola não ativou a "
                         "personalização pelos registros de aprendizagem.")
        per_student.append({
            "student": s, "plan": p,
            "checks": {t.pk: checks.get(t.pk) for t in topics},
            "reviewed": sum(1 for c in checks.values() if c.status == TopicCheck.Status.UNDERSTOOD),
            "questions": list(StudyQuestion.objects.filter(guide=guide, student=s).select_related("topic")),
        })
    return {"per_student": per_student, "is_student": user.role == Role.ESTUDANTE.value,
            "question_form": QuestionForm(guide=guide), "check_choices": TopicCheck.Status.choices,
            "videos": [m for m in guide.active_materials if m.kind == "video"],
            "readings": [m for m in guide.active_materials if m.kind == "leitura"],
            "others": [m for m in guide.active_materials if m.kind not in ("video", "leitura")]}


def _staff_context(user, guide, topics):
    from apps.pedagogy.views import _enrolled_students

    can_manage = access.can_manage(user, guide)
    students = list(_enrolled_students(guide.class_group))
    checks = TopicCheck.objects.filter(topic__guide=guide, student__in=students)
    by_topic = {}
    for c in checks:
        by_topic.setdefault(c.topic_id, {}).setdefault(c.status, 0)
        by_topic[c.topic_id][c.status] += 1
    questions = list(guide.questions.select_related("student", "topic", "author", "answered_by"))
    for t in topics:
        counts = by_topic.get(t.pk, {})
        t.self_report = [(label, counts.get(key, 0)) for key, label in TopicCheck.Status.choices]
        t.no_report = len(students) - sum(counts.values())
        t.n_questions = sum(1 for q in questions if q.topic_id == t.pk)
    return {
        "can_manage": can_manage,
        "students": students,
        "questions": questions,
        "open_questions": [q for q in questions if q.is_open],
        "answer_form": AnswerForm(),
        "skills": plan.class_skill_overview(guide, students),
        "removed": guide.materials.filter(removed_at__isnull=False).select_related("replaced_by")[:10],
        "broken": [m for m in guide.active_materials if m.broken_reports],
    }


def student_plan(request, pk, student_id):
    """Plano individual com os estados técnicos, para a equipe (professor e coordenação)."""
    user = request.user
    guide = _guide(request, pk)
    _require(not access.is_family(user))
    student = get_object_or_404(Student, pk=student_id, school=user.school)
    from apps.analytics.access import can_view_student_dashboard
    from apps.pedagogy.access import enrollments_by_student, reaches

    _require(can_view_student_dashboard(user, student)
             and reaches(enrollments_by_student([student.pk]).get(student.pk, ()), guide))
    p = plan.preparation_plan(guide, student, detailed=True)
    checks = {c.topic_id: c for c in TopicCheck.objects.filter(student=student, topic__guide=guide)}
    create_audit_log(user=user, action="view", request=request, target=student,
                     detail=f"Consultou o plano de preparação de {student} para {guide.title}")
    return render(request, "study/plan_student.html", {
        "guide": guide, "student": student, "plan": p, "checks": checks,
        "topics": list(guide.topics.all())})

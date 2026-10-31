"""Planejamento docente: o professor registra o plano e a coordenação acompanha.

Quem faz o quê:
- professor: escreve planos só para os pares turma+disciplina que leciona
  (``teaches`` com edição), edita enquanto rascunho ou devolvido, envia;
- coordenação: vê e devolve os planos enviados das turmas do seu alcance
  (``class_scope``); rascunho é do professor e não aparece;
- direção: vê e devolve os planos enviados da escola toda.
Secretaria, administração, família e estudante não acessam: é registro
interno da equipe pedagógica.
"""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup, Subject
from apps.academics.permissions import teacher_class_ids, teacher_subject_ids, teaches
from apps.communication.models import Notification
from apps.communication.services import notify, notify_many
from apps.coordination.scope import class_scope, reaches_class
from apps.curriculum.forms import CurriculumFormMixin
from apps.core.models import Role, User, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import id_param

from .models import LessonPlan, LessonPlanReview

DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})
REVIEWER_ROLES = (Role.COORDENACAO.value, Role.DIRECAO.value)
MAX_DAYS = 200


def is_teacher(user):
    return user.is_authenticated and user.role == Role.PROFESSOR.value


def is_reviewer(user):
    return user.is_authenticated and user.role in REVIEWER_ROLES


def can_use_planning(user):
    return is_teacher(user) or is_reviewer(user)


def can_review(user, plan):
    return is_reviewer(user) and plan.school_id == user.school_id and reaches_class(user, plan.class_group_id)


def can_view(user, plan):
    if plan.school_id != user.school_id:
        return False
    if plan.teacher_id == user.pk:
        return True
    return plan.status != LessonPlan.Status.DRAFT and can_review(user, plan)


def reviewers_for(plan):
    """Coordenadores que alcançam a turma; sem nenhum, a direção."""
    users = [u for u in User.objects.filter(school=plan.school, role=Role.COORDENACAO.value, is_active=True)
             if reaches_class(u, plan.class_group_id)]
    return users or list(User.objects.filter(school=plan.school, role=Role.DIRECAO.value, is_active=True))


class LessonPlanForm(CurriculumFormMixin, forms.ModelForm):
    class Meta:
        model = LessonPlan
        fields = ["class_group", "subject", "starts_on", "ends_on", "title", "content", "objectives",
                  "methodology", "resources", "assessment", "curriculum"]
        labels = {"class_group": "Turma", "subject": "Disciplina"}
        widgets = {
            "starts_on": DATE, "ends_on": DATE,
            "content": forms.Textarea(attrs={"rows": 3}),
            "objectives": forms.Textarea(attrs={"rows": 3}),
            "methodology": forms.Textarea(attrs={"rows": 3}),
            "resources": forms.Textarea(attrs={"rows": 2}),
            "assessment": forms.Textarea(attrs={"rows": 2}),
        }
        help_texts = {
            "starts_on": "Por exemplo, a segunda-feira da semana planejada.",
            "objectives": "O que os estudantes devem aprender ou conseguir fazer.",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["class_group"].queryset = ClassGroup.objects.filter(
            pk__in=teacher_class_ids(user, edit=True)).select_related("school_year").order_by("name")
        self.fields["subject"].queryset = Subject.choices_for(
            user.school, keep=self.instance.subject_id).filter(pk__in=teacher_subject_ids(user, edit=True))
        self.attach_curriculum(user)

    def clean(self):
        data = super().clean()
        cg, subj = data.get("class_group"), data.get("subject")
        if cg and subj and not teaches(self.user, cg, subj, edit=True):
            self.add_error("subject", "Você não leciona esta disciplina nesta turma.")
        start, end = data.get("starts_on"), data.get("ends_on")
        if start and end:
            if end < start:
                self.add_error("ends_on", "O fim não pode ser antes do início.")
            elif (end - start).days > MAX_DAYS:
                self.add_error("ends_on", f"Período longo demais (até {MAX_DAYS} dias). Divida em mais planos.")
        return data


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label="Decisão", widget=forms.RadioSelect, choices=[
        (LessonPlan.Status.APPROVED, "Validar"),
        (LessonPlan.Status.ADJUST, "Devolver para ajustes"),
    ])
    comment = forms.CharField(label="Orientação ao professor", required=False, max_length=2000,
                              widget=forms.Textarea(attrs={"rows": 3}),
                              help_text="Obrigatória ao devolver para ajustes.")

    def clean(self):
        data = super().clean()
        if data.get("decision") == LessonPlan.Status.ADJUST and not (data.get("comment") or "").strip():
            self.add_error("comment", "Explique o que ajustar.")
        return data


def _visible_qs(user):
    qs = LessonPlan.objects.filter(school=user.school).select_related("teacher", "class_group", "subject")
    if is_teacher(user):
        return qs.filter(teacher=user)
    qs = qs.exclude(status=LessonPlan.Status.DRAFT)
    scope = class_scope(user)
    return qs if scope is None else qs.filter(class_group_id__in=scope)


def lessonplan_list(request):
    user = request.user
    if not can_use_planning(user):
        raise PermissionDenied
    qs = _visible_qs(user)
    status = request.GET.get("situacao", "")
    if status in LessonPlan.Status.values:
        qs = qs.filter(status=status)
    elif is_reviewer(user) and "situacao" not in request.GET:
        status = LessonPlan.Status.SUBMITTED  # quem analisa abre no que espera por ele
        qs = qs.filter(status=status)
    class_id = id_param(request, "turma")
    if class_id:
        qs = qs.filter(class_group_id=class_id)
    teacher_id = id_param(request, "professor")
    if teacher_id and is_reviewer(user):
        qs = qs.filter(teacher_id=teacher_id)
    base = _visible_qs(user)
    tabs = [(value, label, base.filter(status=value).count()) for value, label in LessonPlan.Status.choices
            if is_teacher(user) or value != LessonPlan.Status.DRAFT]
    classes = ClassGroup.objects.filter(pk__in=base.values("class_group_id")).order_by("name")
    teachers = (User.objects.filter(pk__in=base.values("teacher_id")).order_by("first_name")
                if is_reviewer(user) else [])
    page = paginate(request, qs, per_page=20)
    return render(request, "pedagogy/lessonplan_list.html", {
        "plans": page, "page": page, "status": status, "tabs": tabs, "classes": classes, "teachers": teachers, "class_id": class_id or "",
        "teacher_id": teacher_id or "", "is_teacher": is_teacher(user),
    })


def lessonplan_create(request):
    if not is_teacher(request.user):
        raise PermissionDenied
    initial = {}
    today = timezone.localdate()
    monday = today + timedelta(days=(7 - today.weekday()) % 7)
    initial.update(starts_on=monday, ends_on=monday + timedelta(days=4))
    form = LessonPlanForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        plan = form.save(commit=False)
        plan.school = request.user.school
        plan.teacher = request.user
        plan.save()
        form.save_m2m()
        create_audit_log(user=request.user, action="create", request=request, target=plan,
                         detail=f"Criou planejamento “{plan.title}” ({plan.class_group} / {plan.subject})")
        messages.success(request, "Planejamento salvo como rascunho. Envie quando estiver pronto.")
        return redirect("pedagogy:lessonplan_detail", pk=plan.pk)
    return render(request, "pedagogy/lessonplan_form.html", {"form": form, "obj": None})


def _own(request, pk):
    plan = get_object_or_404(LessonPlan, pk=pk, school=request.user.school)
    if plan.teacher_id != request.user.pk:
        raise PermissionDenied
    return plan


def lessonplan_edit(request, pk):
    plan = _own(request, pk)
    if not plan.is_editable:
        messages.error(request, "Planejamento enviado ou validado não pode ser editado. Faça uma cópia.")
        return redirect("pedagogy:lessonplan_detail", pk=plan.pk)
    form = LessonPlanForm(request.POST or None, instance=plan, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        create_audit_log(user=request.user, action="update", request=request, target=plan,
                         detail=f"Editou planejamento “{plan.title}”")
        messages.success(request, "Planejamento atualizado.")
        return redirect("pedagogy:lessonplan_detail", pk=plan.pk)
    return render(request, "pedagogy/lessonplan_form.html", {"form": form, "obj": plan})


def lessonplan_detail(request, pk):
    plan = get_object_or_404(LessonPlan.objects.select_related("teacher", "class_group", "subject"),
                             pk=pk, school=request.user.school)
    if not can_use_planning(request.user) or not can_view(request.user, plan):
        raise PermissionDenied
    reviewing = plan.status == LessonPlan.Status.SUBMITTED and can_review(request.user, plan)
    return render(request, "pedagogy/lessonplan_detail.html", {
        "plan": plan, "reviews": plan.reviews.select_related("author"),
        "is_owner": plan.teacher_id == request.user.pk,
        "review_form": ReviewForm() if reviewing else None,
    })


@require_POST
def lessonplan_submit(request, pk):
    plan = _own(request, pk)
    with transaction.atomic():
        # UPDATE condicional: dois cliques não enviam (nem avisam) duas vezes.
        sent = LessonPlan.objects.filter(pk=plan.pk, status__in=LessonPlan.EDITABLE).update(
            status=LessonPlan.Status.SUBMITTED, submitted_at=timezone.now())
        if not sent:
            messages.error(request, "Este planejamento já foi enviado.")
            return redirect("pedagogy:lessonplan_detail", pk=plan.pk)
        teacher = request.user.get_full_name() or request.user.username
        notify_many(plan.school, reviewers_for(plan), Notification.Kind.PLANNING,
                    f"Planejamento para analisar: {plan.title}",
                    body=f"{teacher} · {plan.subject}, turma {plan.class_group.name} · "
                         f"{plan.starts_on:%d/%m} a {plan.ends_on:%d/%m}.",
                    url=reverse("pedagogy:lessonplan_detail", args=[plan.pk]))
        create_audit_log(user=request.user, action="update", request=request, target=plan,
                         detail=f"Enviou planejamento “{plan.title}” para a coordenação")
    messages.success(request, "Planejamento enviado. A coordenação foi avisada.")
    return redirect("pedagogy:lessonplan_detail", pk=plan.pk)


@require_POST
def lessonplan_review(request, pk):
    plan = get_object_or_404(LessonPlan.objects.select_related("teacher", "class_group", "subject"),
                             pk=pk, school=request.user.school)
    if not can_review(request.user, plan):
        raise PermissionDenied
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return render(request, "pedagogy/lessonplan_detail.html", {
            "plan": plan, "reviews": plan.reviews.select_related("author"), "is_owner": False,
            "review_form": form,
        }, status=200)
    decision = form.cleaned_data["decision"]
    comment = form.cleaned_data["comment"].strip()
    with transaction.atomic():
        done = LessonPlan.objects.filter(pk=plan.pk, status=LessonPlan.Status.SUBMITTED).update(status=decision)
        if not done:
            messages.error(request, "Este planejamento já foi analisado.")
            return redirect("pedagogy:lessonplan_detail", pk=plan.pk)
        LessonPlanReview.objects.create(plan=plan, author=request.user, decision=decision, comment=comment)
        approved = decision == LessonPlan.Status.APPROVED
        notify(plan.school, plan.teacher, Notification.Kind.PLANNING,
               f"Planejamento {'validado' if approved else 'devolvido para ajustes'}: {plan.title}",
               body=comment[:300], url=reverse("pedagogy:lessonplan_detail", args=[plan.pk]))
        create_audit_log(user=request.user, action="approve" if approved else "reject", request=request,
                         target=plan, detail=f"{'Validou' if approved else 'Devolveu'} planejamento “{plan.title}” "
                                             f"de {plan.teacher}")
    messages.success(request, "Devolutiva registrada. O professor foi avisado.")
    return redirect("pedagogy:lessonplan_list")


@require_POST
def lessonplan_duplicate(request, pk):
    """Copia o plano como rascunho para o período seguinte (mesma duração)."""
    plan = _own(request, pk)
    if not teaches(request.user, plan.class_group_id, plan.subject_id, edit=True):
        messages.error(request, "Você não leciona mais esta disciplina nesta turma.")
        return redirect("pedagogy:lessonplan_detail", pk=plan.pk)
    # Semana (ou menos) vai para a semana seguinte; período maior, para o seguinte.
    shift = timedelta(days=max((plan.ends_on - plan.starts_on).days + 1, 7))
    copy = LessonPlan.objects.create(
        school=plan.school, teacher=request.user, class_group=plan.class_group, subject=plan.subject,
        starts_on=plan.starts_on + shift, ends_on=plan.ends_on + shift,
        title=plan.title, content=plan.content, objectives=plan.objectives, methodology=plan.methodology,
        resources=plan.resources, assessment=plan.assessment,
    )
    copy.curriculum.set(plan.curriculum.all())
    create_audit_log(user=request.user, action="create", request=request, target=copy,
                     detail=f"Copiou o planejamento “{plan.title}” para {copy.starts_on:%d/%m/%Y}")
    messages.success(request, "Cópia criada como rascunho, no período seguinte. Ajuste o que mudar.")
    return redirect("pedagogy:lessonplan_edit", pk=copy.pk)


@require_POST
def lessonplan_delete(request, pk):
    plan = _own(request, pk)
    if plan.status != LessonPlan.Status.DRAFT:
        messages.error(request, "Só rascunho pode ser excluído.")
        return redirect("pedagogy:lessonplan_detail", pk=plan.pk)
    create_audit_log(user=request.user, action="delete", request=request, target=plan,
                     detail=f"Excluiu o rascunho de planejamento “{plan.title}”")
    plan.delete()
    messages.success(request, "Rascunho excluído.")
    return redirect("pedagogy:lessonplan_list")


def week_coverage(user, today=None):
    """Planejamento desta semana nos pares turma+disciplina que ``user`` acompanha.

    Par = atribuição vigente hoje (ano letivo atual). Coberto = há plano enviado,
    devolvido ou validado cujo período cruza a semana. Devolve
    ``{"total", "covered", "missing": [(turma, disciplina, professor), ...]}``.
    """
    from apps.academics.models import TeacherAssignment

    today = today or timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    friday = monday + timedelta(days=4)
    pairs = (TeacherAssignment.objects.filter(school=user.school, school_year__is_current=True)
             .filter(Q(starts_on__isnull=True) | Q(starts_on__lte=today))
             .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
             .select_related("class_group", "subject", "teacher"))
    scope = class_scope(user)
    if scope is not None:
        pairs = pairs.filter(class_group_id__in=scope)
    covered = set(LessonPlan.objects.filter(school=user.school, starts_on__lte=friday, ends_on__gte=monday)
                  .exclude(status=LessonPlan.Status.DRAFT).values_list("class_group_id", "subject_id"))
    seen, missing = set(), []
    for a in pairs.order_by("class_group__name", "subject__name"):
        key = (a.class_group_id, a.subject_id)
        if key in seen:
            continue
        seen.add(key)
        if key not in covered:
            missing.append((a.class_group, a.subject, a.teacher))
    return {"total": len(seen), "covered": len(seen) - len(missing), "missing": missing,
            "monday": monday, "friday": friday}

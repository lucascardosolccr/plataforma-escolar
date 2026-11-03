"""Diário de classe: o conteúdo trabalhado em cada aula.

Quem faz o quê:

- o professor registra e corrige as aulas dos pares turma+disciplina que leciona (atribuição ou
  permissão de edição);
- a coordenação lê no alcance da designação; a direção e a administração, na escola toda;
- a família e o estudante leem o **conteúdo** das aulas das turmas em que há matrícula ativa (quem
  faltou sabe o que perdeu); as observações da equipe nunca aparecem para eles;
- a secretaria não tem acesso: é registro pedagógico.

As habilidades marcadas entram como "trabalhadas" nos indicadores curriculares.
"""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.academics.permissions import teacher_pairs
from apps.coordination.scope import class_scope
from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.curriculum.forms import CurriculumFormMixin

from .models import LessonRecord

TEAM_READ = (Role.COORDENACAO.value, Role.DIRECAO.value, Role.ADMIN.value)
FAMILY = (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)


def _family_class_ids(user):
    from apps.registry.access import student_of
    from apps.registry.models import Enrollment, GuardianLink

    if user.role == Role.RESPONSAVEL.value:
        sids = GuardianLink.objects.filter(guardian=user, status="aprovado").values_list("student_id", flat=True)
    else:
        own = student_of(user)
        sids = [own.pk] if own else []
    return set(Enrollment.objects.filter(student_id__in=list(sids), status="ativo")
               .values_list("class_group_id", flat=True))


def visible_records(user):
    """Registros que a pessoa pode ler, ou None se não tem acesso ao diário."""
    qs = LessonRecord.objects.filter(school=user.school).select_related("class_group", "subject", "teacher")
    if user.role == Role.PROFESSOR.value:
        q = Q(pk__in=[])
        for c, s in teacher_pairs(user):
            q |= Q(class_group_id=c, subject_id=s)
        return qs.filter(q)
    if user.role in TEAM_READ:
        scope = class_scope(user) if user.role == Role.COORDENACAO.value else None
        return qs if scope is None else qs.filter(class_group_id__in=scope)
    if user.role in FAMILY:
        return qs.filter(class_group_id__in=_family_class_ids(user))
    return None


def can_edit(user, cg_id, subject_id):
    return user.role == Role.PROFESSOR.value and (cg_id, subject_id) in set(teacher_pairs(user, edit=True))


class LessonRecordForm(CurriculumFormMixin, forms.ModelForm):
    pair = forms.ChoiceField(label="Turma e disciplina")

    class Meta:
        model = LessonRecord
        fields = ["pair", "date", "content", "curriculum", "notes"]
        widgets = {"date": forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"}),
                   "content": forms.Textarea(attrs={"rows": 4}), "notes": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        pairs = sorted(teacher_pairs(user, edit=True))
        classes = {c.pk: c for c in ClassGroup.objects.filter(pk__in={c for c, _ in pairs})}
        subjects = {s.pk: s for s in Subject.objects.filter(pk__in={s for _, s in pairs})}
        self.fields["pair"].choices = [(f"{c}:{s}", f"{classes[c].name} · {subjects[s].name}")
                                       for c, s in pairs if c in classes and s in subjects]
        if self.instance.pk:
            self.fields["pair"].initial = f"{self.instance.class_group_id}:{self.instance.subject_id}"
            self.fields["pair"].disabled = True  # corrigir não muda de turma: abra outro registro
        self.attach_curriculum(user)

    def clean_date(self):
        d = self.cleaned_data["date"]
        if d > timezone.localdate():
            raise forms.ValidationError("O diário registra aulas que já aconteceram.")
        return d

    def clean(self):
        c = super().clean()
        raw = c.get("pair") or ""
        try:
            cg_id, subj_id = (int(x) for x in raw.split(":"))
        except ValueError:
            self.add_error("pair", "Escolha a turma e a disciplina.")
            return c
        if not can_edit(self.user, cg_id, subj_id):
            self.add_error("pair", "Você não leciona esta disciplina nesta turma.")
            return c
        self.cg_id, self.subj_id = cg_id, subj_id
        date = c.get("date")
        if date and not self.instance.pk and LessonRecord.objects.filter(
                class_group_id=cg_id, subject_id=subj_id, date=date).exists():
            self.add_error("date", "Esta aula já tem registro. Abra o registro existente para completar.")
        return c


def diary_list(request):
    user = request.user
    qs = visible_records(user)
    if qs is None:
        raise PermissionDenied
    family = user.role in FAMILY
    pairs = sorted(teacher_pairs(user)) if user.role == Role.PROFESSOR.value else []
    turma = request.GET.get("turma", "")
    if turma.isdigit():
        qs = qs.filter(class_group_id=int(turma))
    if family:  # a família vê as últimas semanas; o histórico completo é da equipe
        qs = qs.filter(date__gte=timezone.localdate() - timedelta(days=60))
    class_ids = sorted(set(qs.values_list("class_group_id", flat=True)))
    return render(request, "pedagogy/diary_list.html", {
        "page": paginate(request, qs.prefetch_related("curriculum")), "family": family, "turma": turma,
        "class_choices": [(c.pk, c.name) for c in ClassGroup.objects.filter(pk__in=class_ids).order_by("name")],
        "can_create": bool(pairs) and bool(teacher_pairs(user, edit=True)),
        "editable": {(c, s) for c, s in teacher_pairs(user, edit=True)} if pairs else set(),
    })


def diary_form(request, pk=None):
    user = request.user
    if user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    obj = None
    if pk:
        obj = get_object_or_404(LessonRecord, pk=pk, school=user.school)
        if not can_edit(user, obj.class_group_id, obj.subject_id):
            raise PermissionDenied
    initial = {}
    if not obj and request.GET.get("par"):
        initial["pair"] = request.GET["par"]
    form = LessonRecordForm(request.POST or None, instance=obj, user=user, initial=initial)
    if request.method == "POST" and form.is_valid():
        rec = form.save(commit=False)
        if not obj:
            rec.school, rec.class_group_id, rec.subject_id = user.school, form.cg_id, form.subj_id
        rec.teacher = user
        rec.save()
        form.save_m2m()
        create_audit_log(user=user, action="update" if obj else "create", request=request, target=rec,
                         detail=f"{'Corrigiu' if obj else 'Registrou'} {rec}")
        messages.success(request, "Aula registrada no diário." if not obj else "Registro corrigido.")
        return redirect("pedagogy:diary_list")
    return render(request, "pedagogy/diary_form.html", {"form": form, "obj": obj})

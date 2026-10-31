"""Banco de atividades do professor: reaproveitar o que já foi preparado.

"Minhas atividades anteriores" lista o que o professor criou, de qualquer
turma ou ano, mesmo que ele não lecione mais ali. A lista mostra só o
enunciado: nada de estudantes nem de entregas da turma antiga (essas telas
continuam exigindo o vínculo atual). "Reutilizar" cria um rascunho para uma
turma+disciplina que ele leciona hoje, copiando o texto e os anexos.
"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.academics.permissions import teacher_pairs, teaches
from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import id_param

from .models import Activity, ActivityAttachment

COPIED_FIELDS = ("title", "work_mode", "content", "objective", "description", "materials", "criteria",
                 "internal_notes")


def _teacher(user):
    if not (user.is_authenticated and user.role == Role.PROFESSOR.value):
        raise PermissionDenied


def _reusable(user, act):
    """Pode reaproveitar: quem criou, ou quem leciona o par da atividade."""
    return act.created_by_id == user.pk or teaches(user, act.class_group_id, act.subject_id, edit=True)


def _pair_choices(user):
    pairs = teacher_pairs(user, edit=True)
    classes = ClassGroup.objects.in_bulk({c for c, _ in pairs})
    subjects = Subject.choices_for(user.school).in_bulk({s for _, s in pairs})
    out = [(f"{c}:{s}", f"{classes[c].name} · {subjects[s].name}")
           for c, s in pairs if c in classes and s in subjects]
    return sorted(out, key=lambda x: x[1])


class ReuseForm(forms.Form):
    pair = forms.ChoiceField(label="Para qual turma e disciplina")
    class_date = forms.DateField(label="Data de aplicação",
                                 widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
                                 help_text="Dia em que a atividade será aplicada em aula.")
    deadline = forms.DateField(label="Data de entrega", required=False,
                               widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    copy_attachments = forms.BooleanField(label="Copiar também os anexos", required=False, initial=True)

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["pair"].choices = [("", "Escolha…")] + _pair_choices(user)

    def clean(self):
        data = super().clean()
        due = data.get("deadline")
        if due and due < timezone.localdate():
            self.add_error("deadline", "A data de entrega já passou.")
        return data


def activity_bank(request):
    user = request.user
    _teacher(user)
    qs = (Activity.objects.filter(school=user.school, created_by=user)
          .select_related("class_group__school_year", "subject")
          .annotate(attachment_count=Count("attachments")))
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(content__icontains=q) | Q(description__icontains=q))
    subject_id = id_param(request, "disciplina")
    if subject_id:
        qs = qs.filter(subject_id=subject_id)
    subjects = Subject.objects.filter(pk__in=Activity.objects.filter(school=user.school, created_by=user)
                                      .values("subject_id")).order_by("name")
    page = paginate(request, qs.order_by("-published_date", "-created_at"), per_page=20)
    return render(request, "pedagogy/activity_bank.html", {
        "acts": page, "page": page, "q": q, "subjects": subjects, "subject_id": subject_id or "",
        "has_pairs": bool(teacher_pairs(user, edit=True)),
    })


def activity_reuse(request, pk):
    user = request.user
    _teacher(user)
    src = get_object_or_404(Activity.objects.select_related("class_group", "subject"), pk=pk, school=user.school)
    if not _reusable(user, src):
        raise PermissionDenied
    initial = {}
    for value, _label in _pair_choices(user):
        if value.endswith(f":{src.subject_id}"):
            initial["pair"] = value
            break
    form = ReuseForm(request.POST or None, user=user, initial=initial)
    if not src.attachments.exists():
        del form.fields["copy_attachments"]
    if request.method == "POST" and form.is_valid():
        cg_id, subject_id = (int(x) for x in form.cleaned_data["pair"].split(":"))
        if not teaches(user, cg_id, subject_id, edit=True):  # escolha forjada
            raise PermissionDenied
        skipped = 0
        with transaction.atomic():
            copy = Activity(school=user.school, class_group_id=cg_id, subject_id=subject_id, created_by=user,
                            status=Activity.Status.DRAFT, published_date=timezone.localdate(),
                            class_date=form.cleaned_data["class_date"], deadline=form.cleaned_data["deadline"],
                            **{f: getattr(src, f) for f in COPIED_FIELDS})
            copy.save()
            copy.curriculum.set(src.curriculum.all())
            if form.cleaned_data.get("copy_attachments"):
                for att in src.attachments.all():
                    try:
                        with att.file.open("rb") as fh:
                            content = fh.read()
                    except (FileNotFoundError, OSError, ValueError):
                        skipped += 1
                        continue
                    ActivityAttachment.objects.create(
                        activity=copy, file=ContentFile(content, name=att.original_name),
                        original_name=att.original_name, size=len(content), uploaded_by=user)
            create_audit_log(user=user, action="create", request=request, target=copy,
                             detail=f"Reutilizou a atividade “{src.title}” (nº {src.pk}) como rascunho "
                                    f"para {copy.class_group}")
        if skipped:
            messages.warning(request, f"{skipped} anexo(s) não foram encontrados no servidor e ficaram de fora.")
        messages.success(request, "Rascunho criado a partir da atividade anterior. Revise e publique.")
        return redirect("pedagogy:activity_edit", pk=copy.pk)
    return render(request, "pedagogy/activity_reuse.html", {"form": form, "src": src})

"""Permissões adicionais de professores (acesso a disciplina/turma que não é dele)."""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.communication.models import Notification
from apps.communication.services import notify
from apps.core.models import Role, User, create_audit_log
from apps.core.pagination import paginate

from .models import ClassGroup, Subject, TeacherAssignment, TeacherPermission

GRANTERS = (Role.DIRECAO.value, Role.SECRETARIA.value, Role.ADMIN.value)


def can_grant(user):
    return user.is_authenticated and user.role in GRANTERS


class PermissionForm(forms.ModelForm):
    class Meta:
        model = TeacherPermission
        fields = ["teacher", "class_group", "subject", "kind", "starts_on", "ends_on", "justification"]
        widgets = {
            "starts_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "ends_on": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
        }
        help_texts = {"justification": "Ex.: substituição durante licença; apoio ao conselho de classe."}

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.fields["teacher"].queryset = User.objects.filter(
            school=school, role=Role.PROFESSOR.value, is_active=True).order_by("first_name")
        self.fields["class_group"].queryset = ClassGroup.objects.filter(school=school).order_by("name")
        self.fields["subject"].queryset = Subject.choices_for(school, keep=self.instance.subject_id)
        self.fields["starts_on"].initial = timezone.localdate()

    def clean(self):
        data = super().clean()
        s, e = data.get("starts_on"), data.get("ends_on")
        if s and e and e < s:
            self.add_error("ends_on", "O término não pode ser antes do início.")
        t, cg, subj = data.get("teacher"), data.get("class_group"), data.get("subject")
        if t and cg and subj:
            if TeacherAssignment.objects.filter(teacher=t, class_group=cg, subject=subj).exists():
                self.add_error(None, "Este professor já tem atribuição nesta turma e disciplina.")
            dup = TeacherPermission.objects.filter(teacher=t, class_group=cg, subject=subj,
                                                   status=TeacherPermission.Status.ACTIVE)
            if dup.exists():
                self.add_error(None, "Já existe permissão ativa igual. Revogue-a antes de conceder outra.")
        if not (data.get("justification") or "").strip():
            self.add_error("justification", "Informe a justificativa.")
        return data


def permission_list(request):
    if not can_grant(request.user):
        raise PermissionDenied
    school = request.user.school
    form = PermissionForm(request.POST or None, school=school)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            perm = form.save(commit=False)
            perm.school, perm.granted_by = school, request.user
            perm.save()
            create_audit_log(user=request.user, action="create", request=request, target=perm,
                             detail=f"Concedeu permissão adicional: {perm} — {perm.justification}")
            notify(school, perm.teacher, Notification.Kind.ANNOUNCEMENT,
                   f"Acesso adicional: {perm.subject} · {perm.class_group.name}",
                   body=f"{perm.get_kind_display()} a partir de {perm.starts_on:%d/%m/%Y}"
                        + (f" até {perm.ends_on:%d/%m/%Y}" if perm.ends_on else "") + f". Motivo: {perm.justification}",
                   url=reverse("my_classrooms"), dedupe_key=f"permissao-{perm.pk}")
        messages.success(request, "Permissão concedida. O professor foi avisado.")
        return redirect("teacher_permissions")
    status = request.GET.get("situacao", "ativa")
    qs = TeacherPermission.objects.filter(school=school).select_related(
        "teacher", "subject", "class_group", "granted_by", "revoked_by")
    if status in dict(TeacherPermission.Status.choices):
        qs = qs.filter(status=status)
    page = paginate(request, qs)
    today = timezone.localdate()
    for p in page:
        p.current = p.is_current(today)
    return render(request, "academics/teacher_permissions.html", {
        "form": form, "permissions": page, "page": page, "status": status,
    })


@require_POST
def permission_revoke(request, pk):
    if not can_grant(request.user):
        raise PermissionDenied
    perm = get_object_or_404(TeacherPermission, pk=pk, school=request.user.school)
    if perm.status == TeacherPermission.Status.ACTIVE:
        perm.status = TeacherPermission.Status.REVOKED
        perm.revoked_by, perm.revoked_at = request.user, timezone.now()
        perm.save(update_fields=["status", "revoked_by", "revoked_at"])
        create_audit_log(user=request.user, action="update", request=request, target=perm,
                         detail=f"Revogou permissão adicional: {perm}")
        messages.success(request, "Permissão revogada. O acesso acaba na hora; o registro fica no histórico.")
    return redirect("teacher_permissions")

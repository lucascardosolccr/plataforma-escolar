"""Pendências acompanhadas: quem resolve, até quando e o que já aconteceu.

Complementa a central de pendências (``pending.py``), que calcula o que falta
a partir dos registros. Aqui a equipe atribui um responsável e um prazo, e
cada mudança vira uma linha de histórico. Regras:

- só a equipe da escola (``STAFF_ROLES``) abre e vê pendências; a família e o
  estudante nunca;
- vê e altera a pendência quem a abriu, quem é responsável por ela e a direção
  (ou administração) da escola;
- o estudante citado precisa estar no alcance de quem abre E de quem recebe a
  pendência: atribuir não pode virar um jeito de mostrar um estudante a quem
  não tem acesso a ele;
- o link "onde se resolve" só aceita endereço interno existente;
- nada é apagado: encerrar é mudar a situação para resolvida ou cancelada.
"""

from urllib.parse import urlsplit

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone

from .models import STAFF_ROLES, FollowUp, FollowUpEvent, Role, User, create_audit_log
from .pagination import paginate

MANAGERS = (Role.DIRECAO.value, Role.ADMIN.value)
DATE = forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})


def is_staff_user(user):
    return user.is_authenticated and user.role in [r.value for r in STAFF_ROLES]


def visible_follow_ups(user):
    qs = FollowUp.objects.filter(school=user.school)
    if user.role in MANAGERS:
        return qs
    return qs.filter(Q(assignee=user) | Q(created_by=user))


def can_change(user, fu):
    return fu.school_id == user.school_id and (
        user.role in MANAGERS or user.pk in (fu.assignee_id, fu.created_by_id))


def _staff_of(school):
    return User.objects.filter(school=school, is_active=True, role__in=[r.value for r in STAFF_ROLES]) \
        .order_by("first_name", "last_name", "username")


def _student_visible(user, student):
    from apps.registry.access import students_visible_to

    qs = students_visible_to(user)
    return qs is not None and qs.filter(pk=student.pk).exists()


def clean_internal_link(value):
    value = (value or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not value.startswith("/") or value.startswith("//") or "\\" in value:
        raise forms.ValidationError("Use um endereço desta plataforma.")
    try:
        resolve(parts.path)
    except Resolver404:
        raise forms.ValidationError("Endereço não encontrado nesta plataforma.")
    return value


class FollowUpForm(forms.ModelForm):
    class Meta:
        model = FollowUp
        fields = ["title", "category", "student", "assignee", "due_date", "description", "link"]
        widgets = {"due_date": DATE, "description": forms.Textarea(attrs={"rows": 3}),
                   "link": forms.HiddenInput()}
        help_texts = {"due_date": "Opcional, mas uma pendência com prazo é cobrada na central de quem a recebe."}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.registry.access import students_visible_to

        self.user = user
        self.fields["assignee"].queryset = _staff_of(user.school)
        self.fields["assignee"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.role_label})"
        students = students_visible_to(user)
        self.fields["student"].queryset = students if students is not None \
            else self.fields["student"].queryset.none()
        self.fields["student"].required = False
        self.fields["student"].empty_label = "— nenhum estudante —"
        self.fields["link"].required = False

    def clean_link(self):
        return clean_internal_link(self.cleaned_data.get("link"))

    def clean(self):
        cleaned = super().clean()
        student, assignee = cleaned.get("student"), cleaned.get("assignee")
        if student and assignee and not _student_visible(assignee, student):
            self.add_error("assignee", "Essa pessoa não tem acesso a este estudante. Escolha outra pessoa ou "
                                       "deixe a pendência sem estudante.")
        return cleaned


class FollowUpUpdateForm(forms.Form):
    status = forms.ChoiceField(label="Situação", choices=FollowUp.Status.choices)
    assignee = forms.ModelChoiceField(label="Responsável", queryset=User.objects.none())
    due_date = forms.DateField(label="Prazo", required=False, widget=DATE)
    note = forms.CharField(label="Observação", required=False, widget=forms.Textarea(attrs={"rows": 2}),
                           help_text="Obrigatória ao cancelar. Fica no histórico.")

    def __init__(self, *args, fu, **kwargs):
        super().__init__(*args, **kwargs)
        self.fu = fu
        self.fields["assignee"].queryset = _staff_of(fu.school)
        self.fields["assignee"].label_from_instance = lambda u: f"{u.get_full_name() or u.username} ({u.role_label})"

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("status") == FollowUp.Status.CANCELADA and not (cleaned.get("note") or "").strip():
            self.add_error("note", "Diga por que a pendência foi cancelada.")
        assignee = cleaned.get("assignee")
        if assignee and self.fu.student_id and not _student_visible(assignee, self.fu.student):
            self.add_error("assignee", "Essa pessoa não tem acesso ao estudante desta pendência.")
        return cleaned


def _notify_assignee(fu, by):
    if fu.assignee_id == by.pk:
        return
    from apps.communication.models import Notification
    from apps.communication.services import notify

    prazo = f" Prazo: {fu.due_date:%d/%m/%Y}." if fu.due_date else ""
    notify(fu.school, fu.assignee, Notification.Kind.REQUEST, "Pendência atribuída a você",
           f"{fu.title}.{prazo} Atribuída por {by.get_full_name() or by.username}.",
           url=reverse("follow_up_detail", args=[fu.pk]),
           dedupe_key=f"pendencia:{fu.pk}:{fu.assignee_id}")


def _label(user):
    return user.get_full_name() or user.username if user else "—"


def follow_up_list(request):
    user = request.user
    if not is_staff_user(user):
        raise PermissionDenied
    qs = visible_follow_ups(user).select_related("assignee", "student", "created_by")
    escopo = request.GET.get("escopo", "minhas")
    if escopo == "minhas":
        qs = qs.filter(assignee=user)
    elif escopo == "abertas_por_mim":
        qs = qs.filter(created_by=user)
    else:
        escopo = "todas"
    situacao = request.GET.get("situacao", "abertas")
    if situacao == "abertas":
        qs = qs.filter(status__in=FollowUp.OPEN)
    elif situacao == "atrasadas":
        qs = qs.filter(status__in=FollowUp.OPEN, due_date__lt=timezone.localdate())
    elif situacao in FollowUp.Status.values:
        qs = qs.filter(status=situacao)
    else:
        situacao = "todas"
    page = paginate(request, qs)
    return render(request, "core/followup_list.html", {
        "page": page, "escopo": escopo, "situacao": situacao, "can_see_all": user.role in MANAGERS,
        "situacoes": [("abertas", "Abertas"), ("atrasadas", "Atrasadas")] + list(FollowUp.Status.choices),
        "escopos": [("minhas", "Sob minha responsabilidade"), ("abertas_por_mim", "Abertas por mim")],
    })


def follow_up_create(request):
    user = request.user
    if not is_staff_user(user):
        raise PermissionDenied
    initial = {"assignee": user}
    for key, field in (("titulo", "title"), ("tela", "link"), ("tipo", "category")):
        if request.GET.get(key):
            initial[field] = request.GET[key][:300]
    form = FollowUpForm(request.POST or None, initial=initial, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            fu = form.save(commit=False)
            fu.school, fu.created_by = user.school, user
            fu.save()
            FollowUpEvent.objects.create(follow_up=fu, by=user, change=f"Aberta e atribuída a {_label(fu.assignee)}"
                                         + (f", prazo {fu.due_date:%d/%m/%Y}" if fu.due_date else ""))
            create_audit_log(user=user, action="create", request=request, target=fu,
                             detail=f"Abriu a pendência '{fu.title}'")
        _notify_assignee(fu, user)
        messages.success(request, "Pendência registrada.")
        return redirect("follow_up_detail", pk=fu.pk)
    return render(request, "core/followup_form.html", {"form": form})


def follow_up_detail(request, pk):
    user = request.user
    if not is_staff_user(user):
        raise PermissionDenied
    fu = get_object_or_404(FollowUp.objects.select_related("assignee", "student", "created_by"),
                           pk=pk, school=user.school)
    if not visible_follow_ups(user).filter(pk=fu.pk).exists():
        raise PermissionDenied
    form = None
    if can_change(user, fu):
        form = FollowUpUpdateForm(request.POST or None, fu=fu, initial={
            "status": fu.status, "assignee": fu.assignee, "due_date": fu.due_date})
        if request.method == "POST" and form.is_valid():
            d = form.cleaned_data
            changes = []
            if d["status"] != fu.status:
                changes.append(f"Situação: {fu.get_status_display()} → {FollowUp.Status(d['status']).label}")
                fu.status = d["status"]
                fu.closed_at = None if fu.is_open else timezone.now()
            reassigned = d["assignee"].pk != fu.assignee_id
            if reassigned:
                changes.append(f"Responsável: {_label(fu.assignee)} → {_label(d['assignee'])}")
                fu.assignee = d["assignee"]
            if d["due_date"] != fu.due_date:
                antes = f"{fu.due_date:%d/%m/%Y}" if fu.due_date else "sem prazo"
                depois = f"{d['due_date']:%d/%m/%Y}" if d["due_date"] else "sem prazo"
                changes.append(f"Prazo: {antes} → {depois}")
                fu.due_date = d["due_date"]
            note = (d["note"] or "").strip()
            if changes or note:
                with transaction.atomic():
                    fu.save()
                    FollowUpEvent.objects.create(follow_up=fu, by=user, change="; ".join(changes) or "Observação",
                                                 note=note)
                    create_audit_log(user=user, action="update", request=request, target=fu,
                                     detail=f"Atualizou a pendência '{fu.title}': " + ("; ".join(changes) or "observação"))
                if reassigned:
                    _notify_assignee(fu, user)
                messages.success(request, "Pendência atualizada.")
            return redirect("follow_up_detail", pk=fu.pk)
    return render(request, "core/followup_detail.html", {
        "fu": fu, "form": form, "events": fu.events.select_related("by"),
    })


def open_follow_ups(user):
    """Resumo para a central de pendências: as abertas atribuídas a esta pessoa."""
    qs = FollowUp.objects.filter(school=user.school, assignee=user, status__in=FollowUp.OPEN)
    return qs.count(), qs.filter(due_date__lt=timezone.localdate()).count()

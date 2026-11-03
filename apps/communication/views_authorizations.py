"""Autorizações de passeio e atividades fora da rotina, respondidas pela família na plataforma.

Quem faz o quê:

- **criam:** professor (só as próprias turmas), coordenação (turmas da designação), direção, secretaria e
  administração;
- **acompanham:** quem criou e a equipe que alcança as turmas. Veem autorizados, não autorizados e sem
  resposta, e imprimem a lista de autorizados para o dia;
- **respondem:** o responsável com vínculo aprovado, por filho com matrícula ativa numa das turmas, até o
  prazo. A última resposta vale e cada mudança fica na auditoria. O estudante vê, mas não responde;
- **encerram ou cancelam:** quem criou, a direção e a administração. Cancelar exige motivo e avisa as
  famílias.
"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate

from .models import Authorization, AuthorizationResponse, Notification
from .services import notify_many

STAFF = (Role.PROFESSOR.value, Role.COORDENACAO.value, Role.DIRECAO.value, Role.SECRETARIA.value,
         Role.ADMIN.value)
MANAGERS = (Role.DIRECAO.value, Role.ADMIN.value)
DATE = forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})


def staff_class_ids(user):
    """Turmas que a pessoa da equipe alcança; None se não é da equipe."""
    if user.role not in STAFF:
        return None
    if user.role == Role.PROFESSOR.value:
        from apps.academics.permissions import teacher_class_ids

        return set(teacher_class_ids(user))
    all_ids = set(ClassGroup.objects.filter(school=user.school).values_list("pk", flat=True))
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        return all_ids if scope is None else set(scope) & all_ids
    return all_ids


def _family_children(user):
    """{estudante: turma ativa} dos filhos (responsável) ou do próprio estudante."""
    from apps.registry.access import student_of
    from apps.registry.models import Enrollment, GuardianLink

    if user.role == Role.RESPONSAVEL.value:
        sids = list(GuardianLink.objects.filter(guardian=user, status="aprovado").values_list("student_id", flat=True))
    elif user.role == Role.ESTUDANTE.value:
        own = student_of(user)
        sids = [own.pk] if own else []
    else:
        return {}
    return {e.student: e.class_group_id for e in Enrollment.objects.filter(student_id__in=sids, status="ativo")
            .select_related("student")}


def visible(user):
    qs = Authorization.objects.filter(school=user.school)
    ids = staff_class_ids(user)
    if ids is not None:
        return qs.filter(Q(class_groups__in=ids) | Q(created_by=user)).distinct()
    children = _family_children(user)
    if children:
        return qs.filter(class_groups__in=set(children.values())).distinct()
    return None


def can_manage(user, auth):
    return auth.school_id == user.school_id and (user.role in MANAGERS or auth.created_by_id == user.pk)


def pending_for_family(user):
    """Quantas respostas o responsável ainda deve (autorização aberta, dentro do prazo, filho na turma)."""
    if user.role != Role.RESPONSAVEL.value:
        return 0
    children = _family_children(user)
    if not children:
        return 0
    today = timezone.localdate()
    total = 0
    for auth in Authorization.objects.filter(school=user.school, status=Authorization.Status.OPEN,
                                             deadline__gte=today, class_groups__in=set(children.values())) \
            .distinct().prefetch_related("class_groups"):
        cls = {c.pk for c in auth.class_groups.all()}
        answered = set(auth.responses.values_list("student_id", flat=True))
        total += sum(1 for st, cid in children.items() if cid in cls and st.pk not in answered)
    return total


class AuthorizationForm(forms.ModelForm):
    class Meta:
        model = Authorization
        fields = ["title", "description", "event_date", "deadline", "class_groups"]
        widgets = {"event_date": DATE, "deadline": DATE, "description": forms.Textarea(attrs={"rows": 5}),
                   "class_groups": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        qs = ClassGroup.objects.filter(pk__in=staff_class_ids(user) or [])
        current = qs.filter(school_year__is_current=True)  # turmas do ano letivo atual, quando ele está marcado
        self.fields["class_groups"].queryset = (current if current.exists() else qs).order_by("name")

    def clean(self):
        c = super().clean()
        today = timezone.localdate()
        if c.get("event_date") and c["event_date"] < today:
            self.add_error("event_date", "A atividade já passou.")
        if c.get("deadline") and c.get("event_date") and c["deadline"] > c["event_date"]:
            self.add_error("deadline", "O prazo de resposta precisa ser até o dia da atividade.")
        if c.get("deadline") and c["deadline"] < today:
            self.add_error("deadline", "O prazo já passou.")
        return c


def _guardians_of(class_ids):
    from apps.core.models import User
    from apps.registry.models import Enrollment, GuardianLink

    sids = Enrollment.objects.filter(class_group_id__in=class_ids, status="ativo").values_list("student_id", flat=True)
    gids = GuardianLink.objects.filter(student_id__in=sids, status="aprovado").values_list("guardian_id", flat=True)
    return User.objects.filter(pk__in=gids, is_active=True)


def authorization_list(request):
    user = request.user
    qs = visible(user)
    if qs is None:
        raise PermissionDenied
    staff = staff_class_ids(user) is not None
    return render(request, "communication/authorization_list.html", {
        "page": paginate(request, qs.prefetch_related("class_groups")), "staff": staff,
        "can_create": staff and bool(staff_class_ids(user)), "today": timezone.localdate(),
    })


def authorization_create(request):
    user = request.user
    if not staff_class_ids(user):
        raise PermissionDenied
    form = AuthorizationForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            auth = form.save(commit=False)
            auth.school, auth.created_by = user.school, user
            auth.save()
            form.save_m2m()
            create_audit_log(user=user, action="create", request=request, target=auth,
                             detail=f"Criou a autorização '{auth.title}'")
        notify_many(user.school, _guardians_of([c.pk for c in auth.class_groups.all()]),
                    Notification.Kind.ANNOUNCEMENT, f"Autorização: {auth.title}",
                    body=f"Responda até {auth.deadline:%d/%m/%Y}. Atividade em {auth.event_date:%d/%m/%Y}.",
                    url=reverse("communication:authorization_detail", args=[auth.pk]))
        messages.success(request, "Autorização enviada às famílias.")
        return redirect("communication:authorization_detail", pk=auth.pk)
    return render(request, "communication/authorization_form.html", {"form": form})


def _staff_rows(auth, class_ids):
    from apps.registry.models import Enrollment

    responses = {r.student_id: r for r in auth.responses.select_related("answered_by")}
    groups = []
    for cg in auth.class_groups.filter(pk__in=class_ids).order_by("name"):
        rows = []
        for e in Enrollment.objects.filter(class_group=cg, status="ativo").select_related("student") \
                .order_by("student__first_name", "student__last_name"):
            rows.append({"student": e.student, "response": responses.get(e.student_id)})
        groups.append({
            "cg": cg, "rows": rows,
            "yes": sum(1 for r in rows if r["response"] and r["response"].answer == "autorizo"),
            "no": sum(1 for r in rows if r["response"] and r["response"].answer == "nao_autorizo"),
            "none": sum(1 for r in rows if not r["response"]),
        })
    return groups


def authorization_detail(request, pk):
    user = request.user
    qs = visible(user)
    if qs is None:
        raise PermissionDenied
    auth = get_object_or_404(qs, pk=pk)
    ids = staff_class_ids(user)
    ctx = {"auth": auth, "can_manage": can_manage(user, auth), "accepts": auth.accepts_answers(),
           "print": request.GET.get("imprimir") == "1"}
    if ids is not None:
        ctx["groups"] = _staff_rows(auth, ids | ({c.pk for c in auth.class_groups.all()}
                                                  if auth.created_by_id == user.pk else set()))
        ctx["staff"] = True
    else:
        cls = {c.pk for c in auth.class_groups.all()}
        responses = {r.student_id: r for r in auth.responses.filter(student__in=list(_family_children(user)))}
        ctx["children"] = [{"student": st, "response": responses.get(st.pk)}
                           for st, cid in _family_children(user).items() if cid in cls]
        ctx["can_answer"] = user.role == Role.RESPONSAVEL.value
    return render(request, "communication/authorization_detail.html", ctx)


@require_POST
def authorization_answer(request, pk):
    user = request.user
    if user.role != Role.RESPONSAVEL.value:
        raise PermissionDenied
    auth = get_object_or_404(Authorization, pk=pk, school=user.school)
    children = _family_children(user)
    cls = set(auth.class_groups.values_list("pk", flat=True))
    sid = request.POST.get("student", "")
    student = next((st for st, cid in children.items() if str(st.pk) == sid and cid in cls), None)
    if student is None:
        raise PermissionDenied
    answer = request.POST.get("answer")
    if answer not in AuthorizationResponse.Answer.values:
        messages.error(request, "Escolha autorizo ou não autorizo.")
    elif not auth.accepts_answers():
        messages.error(request, "O prazo de resposta terminou ou a autorização foi encerrada.")
    else:
        note = (request.POST.get("note") or "").strip()[:300]
        resp, created = AuthorizationResponse.objects.update_or_create(
            authorization=auth, student=student, defaults={"answer": answer, "note": note, "answered_by": user})
        create_audit_log(user=user, action="create" if created else "update", request=request, target=resp,
                         detail=f"{resp.get_answer_display()}: {student.full_name} em '{auth.title}'"
                         + (f" (obs.: {note})" if note else ""))
        messages.success(request, f"Resposta registrada: {resp.get_answer_display().lower()} ({student.first_name}).")
    return redirect("communication:authorization_detail", pk=auth.pk)


@require_POST
def authorization_status(request, pk, action):
    user = request.user
    auth = get_object_or_404(Authorization, pk=pk, school=user.school)
    if not can_manage(user, auth) or auth.status != Authorization.Status.OPEN:
        raise PermissionDenied
    if action == "encerrar":
        auth.status = Authorization.Status.CLOSED
        auth.save(update_fields=["status"])
        create_audit_log(user=user, action="update", request=request, target=auth,
                         detail=f"Encerrou as respostas de '{auth.title}'")
        messages.success(request, "Respostas encerradas.")
    elif action == "cancelar":
        reason = (request.POST.get("reason") or "").strip()[:300]
        if not reason:
            messages.error(request, "Diga por que a atividade foi cancelada: as famílias recebem o motivo.")
            return redirect("communication:authorization_detail", pk=auth.pk)
        auth.status, auth.cancel_reason = Authorization.Status.CANCELED, reason
        auth.save(update_fields=["status", "cancel_reason"])
        create_audit_log(user=user, action="update", request=request, target=auth,
                         detail=f"Cancelou '{auth.title}': {reason}")
        notify_many(user.school, _guardians_of(list(auth.class_groups.values_list("pk", flat=True))),
                    Notification.Kind.ANNOUNCEMENT, f"Cancelada: {auth.title}", body=reason,
                    url=reverse("communication:authorization_detail", args=[auth.pk]))
        messages.success(request, "Atividade cancelada e famílias avisadas.")
    else:
        raise PermissionDenied
    return redirect("communication:authorization_detail", pk=auth.pk)

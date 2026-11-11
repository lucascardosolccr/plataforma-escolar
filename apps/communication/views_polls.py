"""Consultas às famílias: uma pergunta, algumas opções, um voto por responsável.

- **criam:** a equipe, para as turmas do próprio alcance (professor só as dele; coordenação, as da
  designação); a consulta para a escola toda é da direção, da coordenação com designação "escola toda" e
  da administração;
- **votam:** responsáveis com filho de matrícula ativa numa das turmas (ou na escola, se for para todos),
  até o prazo; dá para mudar o voto;
- **resultado:** a equipe vê só os totais por opção e quantas famílias responderam, nunca quem votou em
  quê. As famílias veem o resultado depois do encerramento, se quem criou deixou;
- **encerram:** quem criou, a direção e a administração.
"""

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import ClassGroup
from apps.core.models import Role, User, create_audit_log
from apps.core.pagination import paginate
from apps.core.params import digits

from .models import Notification, Poll, PollVote
from .services import notify_many
from .views_authorizations import MANAGERS, _family_children, staff_class_ids

DATE = forms.DateInput(format=r"%Y-%m-%d", attrs={"type": "date"})


def can_poll_whole_school(user):
    if user.role in (Role.DIRECAO.value, Role.ADMIN.value):
        return True
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        return class_scope(user) is None
    return False


def _family_class_ids(user):
    return set(_family_children(user).values()) if user.role == Role.RESPONSAVEL.value else set()


def visible(user):
    qs = Poll.objects.filter(school=user.school)
    ids = staff_class_ids(user)
    if ids is not None:
        return qs.filter(Q(class_groups__in=ids) | Q(class_groups__isnull=True) | Q(created_by=user)).distinct()
    if user.role == Role.RESPONSAVEL.value:
        cls = _family_class_ids(user)
        if not cls:
            return None
        return qs.filter(Q(class_groups__in=cls) | Q(class_groups__isnull=True)).distinct()
    return None


def can_vote(user, poll):
    if user.role != Role.RESPONSAVEL.value:
        return False
    targets = set(poll.class_groups.values_list("pk", flat=True))
    cls = _family_class_ids(user)
    return bool(cls) and (not targets or bool(targets & cls))


def pending_for_family(user):
    if user.role != Role.RESPONSAVEL.value:
        return 0
    cls = _family_class_ids(user)
    if not cls:
        return 0
    today = timezone.localdate()
    return (Poll.objects.filter(school=user.school, status=Poll.Status.OPEN, deadline__gte=today)
            .filter(Q(class_groups__in=cls) | Q(class_groups__isnull=True)).exclude(votes__user=user)
            .distinct().count())


def _audience(poll):
    from apps.registry.models import Enrollment, GuardianLink

    targets = list(poll.class_groups.values_list("pk", flat=True))
    enr = Enrollment.objects.filter(school=poll.school, status="ativo")
    if targets:
        enr = enr.filter(class_group_id__in=targets)
    gids = GuardianLink.objects.filter(student_id__in=enr.values("student_id"), status="aprovado") \
        .values_list("guardian_id", flat=True)
    return User.objects.filter(pk__in=gids, is_active=True)


class PollForm(forms.ModelForm):
    options_text = forms.CharField(label="Opções", widget=forms.Textarea(attrs={"rows": 4}),
                                   help_text="Uma por linha, de 2 a 6. Ex.: Terça às 19h / Sábado às 9h.")

    class Meta:
        model = Poll
        fields = ["question", "description", "options_text", "class_groups", "deadline", "show_results"]
        widgets = {"deadline": DATE, "description": forms.Textarea(attrs={"rows": 3}),
                   "class_groups": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        qs = ClassGroup.objects.filter(pk__in=staff_class_ids(user) or [])
        current = qs.filter(school_year__is_current=True)
        self.fields["class_groups"].queryset = (current if current.exists() else qs).order_by("name")
        self.fields["class_groups"].required = False
        if not can_poll_whole_school(user):
            self.fields["class_groups"].help_text = "Escolha ao menos uma turma."
        else:
            self.fields["class_groups"].help_text = "Sem nenhuma marcada, a consulta vai para a escola toda."

    def clean_options_text(self):
        opts = [" ".join(o.split())[:120] for o in self.cleaned_data["options_text"].splitlines() if o.strip()]
        if not 2 <= len(opts) <= 6:
            raise forms.ValidationError("Escreva de 2 a 6 opções, uma por linha.")
        if len(set(o.lower() for o in opts)) != len(opts):
            raise forms.ValidationError("Há opções repetidas.")
        return opts

    def clean(self):
        c = super().clean()
        if c.get("deadline") and c["deadline"] < timezone.localdate():
            self.add_error("deadline", "O prazo já passou.")
        if not c.get("class_groups") and not can_poll_whole_school(self.user):
            self.add_error("class_groups", "Escolha ao menos uma turma.")
        return c


def poll_list(request):
    user = request.user
    qs = visible(user)
    no_link = qs is None and user.role == Role.RESPONSAVEL.value
    if no_link:  # o menu mostra o item; sem vínculo aprovado a lista fica vazia, com o motivo
        qs = Poll.objects.none()
    elif qs is None:
        raise PermissionDenied
    voted = set(PollVote.objects.filter(user=user).values_list("poll_id", flat=True))
    return render(request, "communication/poll_list.html", {
        "no_link": no_link,
        "page": paginate(request, qs.prefetch_related("class_groups")), "voted": voted,
        "staff": staff_class_ids(user) is not None, "can_create": bool(staff_class_ids(user)),
    })


def poll_create(request):
    user = request.user
    if not staff_class_ids(user):
        raise PermissionDenied
    form = PollForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        poll = form.save(commit=False)
        poll.school, poll.created_by, poll.options = user.school, user, form.cleaned_data["options_text"]
        poll.save()
        form.save_m2m()
        create_audit_log(user=user, action="create", request=request, target=poll,
                         detail=f"Criou a consulta '{poll.question}'")
        notify_many(user.school, _audience(poll), Notification.Kind.ANNOUNCEMENT, f"Consulta: {poll.question}",
                    body=f"Responda até {poll.deadline:%d/%m/%Y}.",
                    url=reverse("communication:poll_detail", args=[poll.pk]))
        messages.success(request, "Consulta enviada às famílias.")
        return redirect("communication:poll_detail", pk=poll.pk)
    return render(request, "communication/poll_form.html", {"form": form})


LOW_RESPONSE = 0.5


def poll_margins(counts, audience=None):
    """Percentual de cada opção com IC 95% de Wilson e a leitura da diferença entre as duas mais votadas.

    Com o total de famílias conhecido (``audience``), a margem usa a correção de população finita: se todas
    responderam, não há margem. A margem cobre só o acaso; quem não respondeu pode pensar diferente, e com resposta
    abaixo de 50% a tela avisa (Groves, 2006, Public Opinion Quarterly 70(5), 646–675). Ver
    ``analytics.metrics`` → "poll_margin".
    """
    from apps.core.stats import diff_of_shares, wilson

    total = sum(counts)
    population = audience if audience and audience >= total else None
    rows = []
    for k in counts:
        p, lo, hi = wilson(k, total, population=population) if total else (None, None, None)
        rows.append({"n": k, "pct": round(100 * k / total) if total else 0,
                     "low": round(100 * lo) if lo is not None else None,
                     "high": round(100 * hi) if hi is not None else None})
    margin = {"total": total, "rate": (total / audience) if audience else None}
    margin["low_response"] = margin["rate"] is not None and margin["rate"] < LOW_RESPONSE
    ranked = sorted(range(len(counts)), key=lambda i: -counts[i])
    if total and len(ranked) >= 2:
        d = diff_of_shares(counts[ranked[0]], counts[ranked[1]], total, population=population)
        margin["tie"] = d["low"] <= 0
        margin["leader"] = ranked[0] if counts[ranked[0]] > counts[ranked[1]] else None
    return rows, margin


def poll_detail(request, pk):
    user = request.user
    qs = visible(user)
    if qs is None:
        raise PermissionDenied
    poll = get_object_or_404(qs, pk=pk)
    staff = staff_class_ids(user) is not None
    counts = dict(poll.votes.values_list("option").annotate(n=Count("pk")))
    total = sum(counts.values())
    audience = _audience(poll).count() if staff else None
    results, margin = poll_margins([counts.get(i, 0) for i in range(len(poll.options))], audience)
    for r, o in zip(results, poll.options):
        r["label"] = o
    mine = PollVote.objects.filter(poll=poll, user=user).first()
    show = staff or (poll.status == Poll.Status.CLOSED and poll.show_results)
    return render(request, "communication/poll_detail.html", {
        "poll": poll, "staff": staff, "results": results if show else None, "total": total,
        "margin": margin if show else None, "audience": audience, "mine": mine,
        "can_vote": can_vote(user, poll) and poll.accepts_votes(),
        "can_manage": poll.school_id == user.school_id and (user.role in MANAGERS or poll.created_by_id == user.pk),
        "options": list(enumerate(poll.options)),
    })


@require_POST
def poll_vote(request, pk):
    user = request.user
    poll = get_object_or_404(Poll, pk=pk, school=user.school)
    if not can_vote(user, poll):
        raise PermissionDenied
    raw = request.POST.get("option", "")
    if not poll.accepts_votes():
        messages.error(request, "A consulta foi encerrada ou o prazo terminou.")
    elif not digits(raw) or int(raw) >= len(poll.options):
        messages.error(request, "Escolha uma das opções.")
    else:
        PollVote.objects.update_or_create(poll=poll, user=user, defaults={"option": int(raw)})
        # Auditoria sem a opção escolhida: a equipe não deve saber quem votou em quê.
        create_audit_log(user=user, action="update", request=request, target=poll,
                         detail=f"Respondeu à consulta '{poll.question}'")
        messages.success(request, "Resposta registrada. Dá para mudar até o prazo.")
    return redirect("communication:poll_detail", pk=poll.pk)


@require_POST
def poll_close(request, pk):
    user = request.user
    poll = get_object_or_404(Poll, pk=pk, school=user.school)
    if not (user.role in MANAGERS or poll.created_by_id == user.pk) or poll.status != Poll.Status.OPEN:
        raise PermissionDenied
    poll.status = Poll.Status.CLOSED
    poll.save(update_fields=["status"])
    create_audit_log(user=user, action="update", request=request, target=poll,
                     detail=f"Encerrou a consulta '{poll.question}'")
    messages.success(request, "Consulta encerrada.")
    return redirect("communication:poll_detail", pk=poll.pk)

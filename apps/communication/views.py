from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.params import id_param
from apps.core.models import Role, audit_trail, create_audit_log
from apps.core.pagination import Sort, paginate
from apps.core.uploads import attachment_content_type
from apps.registry.models import Student

from . import access as acc
from .forms import (
    AnnouncementForm,
    ReplyForm,
    RequestResolutionForm,
    ServiceRequestForm,
    ThreadForm,
)
from .models import (
    Announcement,
    AnnouncementRead,
    Message,
    Notification,
    ServiceRequest,
    Thread,
)
from .services import (
    notify_announcement_created,
    notify_request_created,
    notify_request_resolved,
    notify_thread_message,
)


def _log(request, action, target, detail, **kwargs):
    create_audit_log(
        user=request.user,
        action=action,
        request=request,
        target=target,
        detail=detail,
        **kwargs,
    )


# ---------- Central de notificações ----------

def notification_list(request):
    user = request.user
    acc.require(acc.can_view_notifications(user))
    qs = Notification.objects.filter(user=user).select_related("school")
    kind = request.GET.get("tipo")
    if kind in dict(Notification.Kind.choices):
        qs = qs.filter(kind=kind)
    situacao = request.GET.get("situacao")
    if situacao == "nao_lidas":
        qs = qs.filter(is_read=False)
    elif situacao == "lidas":
        qs = qs.filter(is_read=True)
    prioridade = request.GET.get("prioridade")
    if prioridade == Notification.Priority.HIGH:
        qs = qs.filter(priority=prioridade)
    else:
        prioridade = ""
    # Situação do compromisso (prazo, prova): a vencer, data passada, resolvido.
    hoje = timezone.localdate()
    estado = request.GET.get("estado")
    if estado == "a_vencer":
        qs = qs.filter(due_on__gte=hoje, resolved_at__isnull=True)
    elif estado == "vencidas":
        qs = qs.filter(due_on__lt=hoje, resolved_at__isnull=True)
    elif estado == "resolvidas":
        qs = qs.filter(resolved_at__isnull=False)
    else:
        estado = ""
    # Filtro por estudante: só os que aparecem nas próprias notificações
    # (a família escolhe entre os filhos; ninguém lista aluno alheio).
    student_choices = [
        (str(sid), name) for sid, name in
        Notification.objects.filter(user=user, student__isnull=False)
        .values_list("student_id", "student__first_name").distinct().order_by("student__first_name")
    ]
    aluno = request.GET.get("aluno", "")
    if aluno in dict(student_choices):
        qs = qs.filter(student_id=aluno)
    else:
        aluno = ""
    from datetime import date as _date

    def _d(v):
        try:
            return _date.fromisoformat(v)
        except (TypeError, ValueError):
            return None

    de, ate = _d(request.GET.get("de")), _d(request.GET.get("ate"))
    if de:
        qs = qs.filter(created_at__date__gte=de)
    if ate:
        qs = qs.filter(created_at__date__lte=ate)
    page = paginate(request, qs)
    # Agrupa por dia ("Hoje", "Ontem" ou a data) para a lista ler como um feed.
    today = timezone.localdate()
    groups = []
    for n in page:
        day = timezone.localdate(n.created_at)
        label = "Hoje" if day == today else "Ontem" if (today - day).days == 1 else day.strftime("%d/%m/%Y")
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "items": []})
        groups[-1]["items"].append(n)
    return render(
        request,
        "communication/notification_list.html",
        {
            "notifications": page,
            "groups": groups,
            "page": page,
            "kind": kind,
            "situacao": situacao,
            "filtered": bool(kind or situacao or aluno or de or ate or prioridade or estado),
            "prioridade": prioridade,
            "estado": estado,
            "prioridade_choices": [(Notification.Priority.HIGH, "Só importantes")],
            "estado_choices": [("a_vencer", "A vencer"), ("vencidas", "Data passada"),
                               ("resolvidas", "Resolvidas")],
            "today": hoje,
            "student_choices": student_choices,
            "aluno": aluno,
            "de": de,
            "ate": ate,
            "kind_choices": Notification.Kind.choices,
            "situacao_choices": [("nao_lidas", "Não lidas"), ("lidas", "Lidas")],
            "unread_total": Notification.objects.filter(user=user, is_read=False).count(),
        },
    )


@require_POST
def notification_read(request, pk):
    user = request.user
    notif = get_object_or_404(Notification, pk=pk, user=user)
    notif.mark_read()
    if notif.url:
        return redirect(notif.url)
    return redirect("communication:notification_list")


@require_POST
def notification_read_selected(request):
    """Marca como lidas as notificações escolhidas (seleção em lote).

    Só as do próprio usuário: um id alheio na lista é ignorado em silêncio.
    """
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()][:200]
    count = Notification.objects.filter(user=request.user, pk__in=ids, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )
    messages.success(request, f"{count} notificação(ões) marcada(s) como lida(s).")
    return redirect(request.POST.get("next") if _is_safe_next(request) else "communication:notification_list")


def _is_safe_next(request):
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next", "")
    return bool(nxt) and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()})


@require_POST
def notification_read_all(request):
    user = request.user
    Notification.objects.filter(user=user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )
    messages.success(request, "Notificações marcadas como lidas.")
    return redirect("communication:notification_list")


# ---------- Mensagens ----------

def thread_list(request):
    user = request.user
    acc.require(acc.can_start_thread(user))
    qs = user.threads.select_related("student").prefetch_related(
        "participants", "messages", "messages__sender"
    )
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        qs = qs.filter(student=student)
    q = request.GET.get("q", "").strip()[:80]
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(student__first_name__icontains=q) | Q(student__last_name__icontains=q)
            | Q(participants__first_name__icontains=q) | Q(participants__last_name__icontains=q)
        ).distinct()
    leitura = request.GET.get("leitura")
    if leitura == "nao_lidas":
        # Subconsulta: "tem mensagem sem leitura que não fui eu que mandei" na MESMA mensagem.
        qs = qs.filter(pk__in=Message.objects.filter(read_at__isnull=True).exclude(sender=user).values("thread_id"))
    page = paginate(request, qs.order_by("-updated_at"))
    threads = []
    for t in page:
        msgs = list(t.messages.all())
        unread = sum(1 for m in msgs if m.sender_id != user.pk and not m.read_at)
        others = [p for p in t.participants.all() if p.pk != user.pk]
        threads.append({"thread": t, "unread": unread, "last": msgs[-1] if msgs else None, "others": others})
    return render(
        request,
        "communication/thread_list.html",
        {"threads": threads, "page": page, "student_id": student_id, "q": q, "leitura": leitura,
         "leitura_choices": [("nao_lidas", "Com mensagens não lidas")], "filtered": bool(q or leitura)},
    )


def thread_create(request):
    user = request.user
    acc.require(acc.can_start_thread(user))
    initial = {}
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        initial["student"] = student
    form = ThreadForm(request.POST or None, request.FILES or None, initial=initial, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            thread = Thread.objects.create(
                school=user.school,
                title=form.cleaned_data["title"],
                student=form.cleaned_data.get("student"),
                created_by=user,
            )
            thread.participants.add(form.cleaned_data["recipient"], user)
            msg = _new_message(thread, user, form.cleaned_data)
            _log(request, "create", thread, f"Abriu conversa '{thread.title}'")
        notify_thread_message(thread, msg)
        messages.success(request, "Conversa iniciada.")
        return redirect("communication:thread_detail", pk=thread.pk)
    return render(request, "communication/thread_form.html", {"form": form})


def thread_detail(request, pk):
    thread = get_object_or_404(
        Thread.objects.select_related("student").prefetch_related(
            "participants", "messages__sender"
        ),
        pk=pk,
        school=request.user.school,
    )
    acc.require(acc.can_view_thread(request.user, thread))
    Message.objects.filter(
        thread=thread, sender__isnull=False
    ).exclude(sender=request.user).filter(read_at__isnull=True).update(
        read_at=timezone.now()
    )
    if request.method == "POST":
        form = ReplyForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                msg = _new_message(thread, request.user, form.cleaned_data)
                _log(request, "create", msg, f"Respondeu em '{thread.title}'")
            notify_thread_message(thread, msg)
            return redirect("communication:thread_detail", pk=thread.pk)
    else:
        form = ReplyForm()
    other = next(
        (
            p for p in thread.participants.all()
            if p.pk != request.user.pk
        ),
        None,
    )
    return render(
        request,
        "communication/thread_detail.html",
        {"thread": thread, "form": form, "other": other},
    )


def _new_message(thread, sender, data):
    upload = data.get("attachment")
    msg = Message(thread=thread, sender=sender, body=data["body"])
    if upload:
        msg.attachment = upload
        msg.attachment_name = upload.name[:255]
    msg.save()
    return msg


def message_attachment(request, pk):
    """Download do anexo: só para quem participa da conversa (ou a pode ver)."""
    msg = get_object_or_404(Message.objects.select_related("thread"), pk=pk,
                            thread__school=request.user.school)
    acc.require(acc.can_view_thread(request.user, msg.thread))
    if not msg.attachment:
        raise Http404("Anexo indisponível.")
    return FileResponse(
        msg.attachment.open("rb"),
        content_type=attachment_content_type(msg.attachment.name),
        as_attachment=True,
        filename=msg.attachment_name or "anexo",
    )


def _can_issue(user):
    from apps.registry.views_documents import can_issue

    return can_issue(user)


# ---------- Comunicados ----------

def announcement_list(request):
    user = request.user
    acc.require(acc.can_view_announcements(user))
    qs = Announcement.objects.filter(school=user.school).select_related(
        "class_group", "student", "created_by"
    )
    qs = _visible_announcements(user, qs)
    student_id = id_param(request, "estudante")
    if student_id:
        student = get_object_or_404(Student, pk=student_id, school=user.school)
        qs = qs.filter(student=student)
    scope = request.GET.get("abrangencia")
    if scope in dict(Announcement.Scope.choices):
        qs = qs.filter(scope=scope)
    q = request.GET.get("q", "").strip()[:80]
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
    read_qs = AnnouncementRead.objects.filter(user=user).values("announcement_id")
    leitura = request.GET.get("leitura")
    if leitura == "nao_lidos":
        qs = qs.exclude(pk__in=read_qs)
    elif leitura == "lidos":
        qs = qs.filter(pk__in=read_qs)
    read_ids = set(
        AnnouncementRead.objects.filter(
            announcement_id__in=qs.values("pk"), user=user
        ).values_list("announcement_id", flat=True)
    )
    page = paginate(request, qs)
    return render(
        request,
        "communication/announcement_list.html",
        {
            "announcements": page,
            "page": page,
            "read_ids": read_ids,
            "scope": scope,
            "q": q,
            "leitura": leitura,
            "leitura_choices": [("nao_lidos", "Não lidos"), ("lidos", "Lidos")],
            "filtered": bool(scope or q or leitura),
            "student_id": student_id,
            "scope_choices": Announcement.Scope.choices,
            "can_create": any(
                acc.can_create_announcement(user, s)
                for s in Announcement.Scope.values
            ),
        },
    )


def _visible_announcements(user, qs):
    return qs.filter(acc.announcement_q(user))


def announcement_create(request):
    user = request.user
    acc.require(acc.can_view_announcements(user))
    form = AnnouncementForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        scope = form.cleaned_data["scope"]
        acc.require(
            acc.can_create_announcement(
                user, scope, form.cleaned_data["class_group"], form.cleaned_data["student"]
            )
        )
        with transaction.atomic():
            ann = form.save(commit=False)
            ann.school = user.school
            ann.created_by = user
            if scope != Announcement.Scope.TURMA:
                ann.class_group = None
            if scope != Announcement.Scope.INDIVIDUAL:
                ann.student = None
            ann.save()
            _log(request, "create", ann, f"Publicou comunicado '{ann.title}'")
            notify_announcement_created(ann)
        messages.success(request, "Comunicado publicado e notificações enviadas.")
        return redirect("communication:announcement_list")
    return render(request, "communication/announcement_form.html", {"form": form})


def announcement_detail(request, pk):
    user = request.user
    ann = get_object_or_404(
        Announcement.objects.select_related("class_group", "student", "created_by"),
        pk=pk,
        school=user.school,
    )
    acc.require(acc.can_view_announcement(user, ann))
    _, created = AnnouncementRead.objects.get_or_create(announcement=ann, user=user)
    return render(
        request,
        "communication/announcement_detail.html",
        {
            "announcement": ann,
            "has_read": not created,
            "reader_names": ann.reads.select_related("user").values_list(
                "user__first_name", "user__last_name", "user__username"
            ),
        },
    )


# ---------- Solicitações ----------

def request_list(request):
    user = request.user
    acc.require(acc.can_view_requests(user))
    qs = ServiceRequest.objects.filter(school=user.school).select_related(
        "requester", "student"
    )
    if user.role == Role.RESPONSAVEL.value:
        qs = qs.filter(requester=user)
    elif user.role == Role.PROFESSOR.value:
        qs = qs.filter(
            Q(student_id__in=acc._teacher_student_ids(user)) | Q(requester=user)
        )
    if user.role not in acc.LGPD_STAFF:
        qs = qs.exclude(Q(category=ServiceRequest.Category.LGPD) & ~Q(requester=user))
    status = request.GET.get("status")
    if status in dict(ServiceRequest.Status.choices):
        qs = qs.filter(status=status)
    categoria = request.GET.get("categoria")
    if categoria in dict(ServiceRequest.Category.choices):
        qs = qs.filter(category=categoria)
    q = request.GET.get("q", "").strip()[:80]
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(student__first_name__icontains=q)
                       | Q(student__last_name__icontains=q))
    sort = Sort(request, {"data": "created_at", "titulo": "title", "situacao": "status"}, "-data")
    page = paginate(request, sort.apply(qs))
    return render(
        request,
        "communication/request_list.html",
        {
            "requests": page,
            "page": page,
            "status": status,
            "categoria": categoria,
            "category_choices": ServiceRequest.Category.choices,
            "q": q,
            "sort": sort,
            "filtered": bool(status or q or categoria),
            "status_choices": ServiceRequest.Status.choices,
            "can_manage": acc.can_manage_requests(user),
            "can_create": acc.can_create_request(user),
            "lgpd_open": (qs.filter(category=ServiceRequest.Category.LGPD, status__in=["recebida", "em_analise"])
                          .count() if user.role in acc.LGPD_STAFF else 0),
        },
    )


def request_create(request):
    user = request.user
    acc.require(acc.can_create_request(user))
    # Atalho "Pedir correção de dados" em Meus filhos: categoria e filho já
    # escolhidos (o formulário só aceita filhos da própria família).
    initial = {}
    if request.GET.get("categoria") in dict(ServiceRequest.Category.choices):
        initial["category"] = request.GET["categoria"]
    if request.GET.get("estudante", "").isdigit():
        initial["student"] = int(request.GET["estudante"])
    if initial.get("category") == ServiceRequest.Category.LGPD:
        initial.setdefault("title", "Pedido sobre dados pessoais")
    form = ServiceRequestForm(request.POST or None, user=user, initial=initial)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            req = form.save(commit=False)
            req.school = user.school
            req.requester = user
            req.save()
            _log(request, "create", req, f"Solicitação '{req.title}'")
            notify_request_created(req)
        messages.success(request, "Solicitação enviada. Acompanhe o andamento.")
        return redirect("communication:request_list")
    return render(request, "communication/request_form.html", {"form": form})


def request_detail(request, pk):
    user = request.user
    req = get_object_or_404(
        ServiceRequest.objects.select_related("requester", "student", "responded_by"),
        pk=pk,
        school=user.school,
    )
    acc.require(acc.can_view_request(user, req))
    form = None
    if acc.can_manage_requests(user) and (not req.is_lgpd or user.role in acc.LGPD_STAFF):
        original_status = req.status
        form = RequestResolutionForm(request.POST or None, instance=req)
        if request.method == "POST" and form.is_valid():
            with transaction.atomic():
                req.status = form.cleaned_data["status"]
                req.response = form.cleaned_data["response"]
                req.responded_by = user
                req.responded_at = timezone.now()
                req.save()
                _log(
                    request,
                    "update",
                    req,
                    f"Solicitação '{req.title}': {req.get_status_display()}",
                )
                if original_status != req.status:
                    notify_request_resolved(req)
            messages.success(request, "Solicitação atualizada.")
            # Redireciona depois de salvar: sem isso, atualizar a página
            # reenviava o formulário (auditoria e aviso à família em dobro).
            return redirect("communication:request_detail", pk=req.pk)
    history = audit_trail(req).order_by("-created_at")[:50]
    return render(
        request,
        "communication/request_detail.html",
        {"request_": req, "form": form, "history": history,
         # Pedido de documento sobre um estudante: a declaração sai daqui e responde a solicitação.
         "can_issue_document": bool(form) and req.student_id and req.category == ServiceRequest.Category.DOCUMENTO
         and _can_issue(user),
         # O inventário mostra até o que a secretaria não lê (observações, apoio à inclusão): só a direção.
         "can_inventory": bool(form) and req.is_lgpd and req.student_id and user.role == Role.DIRECAO.value},
    )


# ---------- Preferências pessoais e regras da escola ----------

def notification_preferences(request):
    """Tipos de aviso que a própria pessoa prefere não receber."""
    from .family_events import MUTABLE_KINDS
    from .models import NotificationMute

    user = request.user
    acc.require(acc.can_view_notifications(user))
    labels = dict(Notification.Kind.choices)
    if request.method == "POST":
        wanted = set(request.POST.getlist("receber"))
        with transaction.atomic():
            for kind in MUTABLE_KINDS:
                if kind in wanted:
                    NotificationMute.objects.filter(user=user, kind=kind).delete()
                else:
                    NotificationMute.objects.get_or_create(user=user, kind=kind)
        messages.success(request, "Preferências salvas.")
        return redirect("communication:notification_preferences")
    muted = set(NotificationMute.objects.filter(user=user).values_list("kind", flat=True))
    profile = getattr(user, "guardian_profile", None)
    return render(request, "communication/notification_preferences.html", {
        "kinds": [(k, labels[k], k not in muted) for k in MUTABLE_KINDS],
        "profile": profile,
        "email_enabled": _email_channel_on(),
    })


def _email_channel_on():
    from django.conf import settings

    return bool(getattr(settings, "NOTIFY_BY_EMAIL", False))


def notification_rules(request):
    """Direção e administração: quais eventos geram aviso automático à família."""
    from apps.core.models import Role as _Role

    from .family_events import EVENTS
    from .forms import ReminderPolicyForm
    from .models import NotificationRule, ReminderPolicy, ReminderRun

    user = request.user
    if user.role not in (_Role.DIRECAO.value, _Role.ADMIN.value):
        raise PermissionDenied
    policy = ReminderPolicy.for_school(user.school)
    form = ReminderPolicyForm(request.POST or None, instance=policy)
    if request.method == "POST" and form.is_valid():
        on = set(request.POST.getlist("ativo"))
        with transaction.atomic():
            for key in EVENTS:
                NotificationRule.objects.update_or_create(
                    school=user.school, event=key, defaults={"enabled": key in on, "updated_by": user})
            policy = form.save(commit=False)
            policy.school = user.school
            policy.updated_by = user
            policy.save()
            _log(request, "update", None, "Atualizou as regras de aviso à família: "
                 + (", ".join(sorted(on)) or "todas desligadas")
                 + f"; antecedência atividades [{policy.activity_days}], depois do prazo [{policy.overdue_days}], "
                   f"provas [{policy.exam_days}], responsáveis {'sim' if policy.include_guardians else 'não'}",
                 target_type="NotificationRule", target_id="escola")
        messages.success(request, "Regras de aviso salvas. A nova antecedência vale a partir do próximo processamento.")
        return redirect("communication:notification_rules")
    from .family_events import event_enabled

    return render(request, "communication/notification_rules.html", {
        "events": [(k, label, event_enabled(user.school, k)) for k, (label, _kind, _d) in EVENTS.items()],
        "form": form,
        "runs": ReminderRun.objects.all()[:7],
    })

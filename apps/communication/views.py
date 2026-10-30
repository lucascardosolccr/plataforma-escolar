from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.params import id_param
from apps.core.models import AuditLog, Role, create_audit_log
from apps.core.pagination import Sort, paginate
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
            "filtered": bool(kind or situacao),
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
    form = ThreadForm(request.POST or None, initial=initial, user=user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            thread = Thread.objects.create(
                school=user.school,
                title=form.cleaned_data["title"],
                student=form.cleaned_data.get("student"),
                created_by=user,
            )
            thread.participants.add(form.cleaned_data["recipient"], user)
            msg = Message.objects.create(
                thread=thread, sender=user, body=form.cleaned_data["body"]
            )
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
        form = ReplyForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                msg = Message.objects.create(
                    thread=thread, sender=request.user, body=form.cleaned_data["body"]
                )
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
        },
    )


def request_create(request):
    user = request.user
    acc.require(acc.can_create_request(user))
    form = ServiceRequestForm(request.POST or None, user=user)
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
    if acc.can_manage_requests(user):
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
    history = AuditLog.objects.filter(
        target_type="ServiceRequest", target_id=str(req.pk)
    ).order_by("-created_at")[:50]
    return render(
        request,
        "communication/request_detail.html",
        {"request_": req, "form": form, "history": history},
    )

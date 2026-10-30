from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.params import id_param
from apps.core.models import AuditLog, Role, create_audit_log
from apps.core.pagination import paginate
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
    page = paginate(request, qs)
    return render(
        request,
        "communication/notification_list.html",
        {
            "notifications": page,
            "page": page,
            "kind": kind,
            "kind_choices": Notification.Kind.choices,
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
    page = paginate(request, qs.order_by("-updated_at"))
    threads = []
    for t in page:
        unread = sum(
            1
            for m in t.messages.all()
            if m.sender_id != user.pk and not m.read_at
        )
        threads.append((t, unread))
    return render(
        request,
        "communication/thread_list.html",
        {"threads": threads, "page": page, "student_id": student_id},
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
    page = paginate(request, qs)
    return render(
        request,
        "communication/request_list.html",
        {
            "requests": page,
            "page": page,
            "status": status,
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

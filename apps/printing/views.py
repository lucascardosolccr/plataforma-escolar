"""Telas de "Atividades e impressões": pedidos do professor, fila e detalhe."""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.models import Role, create_audit_log
from apps.core.pagination import paginate
from apps.core.uploads import attachment_content_type, validate_attachment_content
from apps.pedagogy import access as acc
from apps.pedagogy.models import Activity

from . import services
from .models import PrintRequest

S = PrintRequest.Status
DATE = forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"})


class PrintRequestForm(forms.ModelForm):
    class Meta:
        model = PrintRequest
        fields = ["attachment", "file", "application_date", "desired_date", "copies", "pages", "duplex",
                  "color", "priority", "notes"]
        widgets = {"application_date": DATE, "desired_date": DATE, "notes": forms.Textarea(attrs={"rows": 2})}
        help_texts = {
            "copies": "Sugerido: número de estudantes ativos da turma. Ajuste se precisar.",
            "attachment": "Um dos anexos da atividade. Ou envie outro arquivo abaixo.",
        }

    def __init__(self, *args, activity=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.activity = activity
        self.fields["attachment"].queryset = activity.attachments.all()
        self.fields["attachment"].required = False
        self.fields["copies"].min_value = 1
        self.fields["priority"].required = False
        if not self.instance.pk:
            app_date = activity.class_date or timezone.localdate() + timedelta(days=2)
            self.initial.setdefault("application_date", app_date)
            self.initial.setdefault("desired_date", max(timezone.localdate(), app_date - timedelta(days=1)))
            self.initial.setdefault("copies", services.suggested_copies(activity) or 1)

    def clean_file(self):
        f = self.cleaned_data.get("file")
        if f and hasattr(f, "content_type"):
            validate_attachment_content(f)
        return f

    def clean(self):
        data = super().clean()
        if not data.get("attachment") and not data.get("file") and not self.instance.file:
            raise forms.ValidationError("Escolha um anexo da atividade ou envie o arquivo a imprimir.")
        app_date, desired = data.get("application_date"), data.get("desired_date")
        today = timezone.localdate()
        if desired and desired < today and not self.instance.pk:
            self.add_error("desired_date", "A data de impressão não pode ser no passado.")
        if app_date and desired and desired > app_date:
            self.add_error("desired_date", "A impressão precisa ficar pronta até a data de aplicação.")
        if data.get("copies") is not None and data["copies"] < 1:
            self.add_error("copies", "Informe ao menos 1 cópia.")
        if data.get("copies") and data["copies"] > 2000:
            self.add_error("copies", "Quantidade acima do limite (2000). Fale com a coordenação.")
        data["priority"] = data.get("priority") or PrintRequest.Priority.NORMAL
        # Critério de prioridade: aplicação em até 2 dias é "alta" automaticamente.
        if app_date and (app_date - today).days <= 2:
            data["priority"] = PrintRequest.Priority.HIGH
        return data


def my_requests(request):
    user = request.user
    if user.role != Role.PROFESSOR.value:
        raise PermissionDenied
    from apps.academics.permissions import pairs_q

    reqs = PrintRequest.objects.filter(requested_by=user).select_related("activity", "activity__class_group",
                                                                          "activity__subject")
    activities = Activity.objects.filter(school=user.school).filter(pairs_q(user, edit=True)) \
        .exclude(status=Activity.Status.CANCELED).select_related("class_group", "subject") \
        .order_by("-class_date", "-created_at")[:30]
    return render(request, "printing/my_requests.html", {
        # Paginado: com o corte em 100 (e a ordem por data desejada), os pedidos mais novos sumiam.
        "requests": (page := paginate(request, reqs)), "page": page, "activities": activities,
        "today": timezone.localdate(),
    })


def request_form(request, pk=None):
    user = request.user
    if pk:
        req = get_object_or_404(PrintRequest, pk=pk, school=user.school)
        if not services.is_owner(user, req) or req.status not in (S.DRAFT, S.CORRECTION):
            raise PermissionDenied
        activity = req.activity
    else:
        req = None
        activity = get_object_or_404(Activity, pk=request.GET.get("atividade") or request.POST.get("atividade") or 0,
                                     school=user.school)
    if not acc.can_manage_activities(user, activity.class_group, activity.subject):
        raise PermissionDenied
    form = PrintRequestForm(request.POST or None, request.FILES or None, instance=req, activity=activity)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.school, obj.activity = user.school, activity
        obj.requested_by = obj.requested_by or user
        if form.cleaned_data.get("file") and hasattr(form.cleaned_data["file"], "name"):
            obj.file_name = form.cleaned_data["file"].name[:255]
        obj.save()
        if not req:
            create_audit_log(user=user, action="create", request=request, target=obj,
                             detail=f"Criou pedido de impressão: {activity.title} ({obj.copies} cópias)")
        if request.POST.get("send") == "1":
            services.apply_action(obj, "submit", user, request=request)
            messages.success(request, "Pedido enviado. A coordenação foi avisada.")
        else:
            messages.success(request, "Rascunho salvo.")
        return redirect("printing:detail", pk=obj.pk)
    return render(request, "printing/request_form.html", {"form": form, "activity": activity, "req": req,
                                                          "students": services.suggested_copies(activity)})


def detail(request, pk):
    req = get_object_or_404(PrintRequest.objects.select_related(
        "activity", "activity__class_group", "activity__subject", "requested_by", "attachment"), pk=pk)
    if not services.can_view(request.user, req):
        raise PermissionDenied
    return render(request, "printing/detail.html", {
        "req": req, "events": req.events.select_related("actor"),
        "actions": services.allowed_actions(request.user, req),
        "can_edit": services.is_owner(request.user, req) and req.status in (S.DRAFT, S.CORRECTION),
    })


@require_POST
def act(request, pk):
    req = get_object_or_404(PrintRequest, pk=pk)
    action = request.POST.get("action", "")
    allowed = {k for k, _l, _n in services.allowed_actions(request.user, req)}
    if action not in allowed:
        raise PermissionDenied
    try:
        services.apply_action(req, action, request.user, note=request.POST.get("note", ""), request=request)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Situação: {req.get_status_display()}.")
    return redirect("printing:detail", pk=req.pk)


def queue(request):
    user = request.user
    if user.role not in (Role.COORDENACAO.value, Role.DIRECAO.value, Role.SECRETARIA.value, Role.ADMIN.value):
        raise PermissionDenied
    qs = PrintRequest.objects.filter(school=user.school).exclude(status=S.DRAFT).select_related(
        "activity", "activity__class_group", "activity__subject", "requested_by")
    if user.role == Role.COORDENACAO.value:
        from apps.coordination.scope import class_scope

        scope = class_scope(user)
        if scope is not None:
            qs = qs.filter(activity__class_group_id__in=scope)
        default = "analise"
    elif user.role == Role.DIRECAO.value:
        default = "analise"
    else:
        default = "impressao"
    view = request.GET.get("ver", default)
    groups = {"analise": services.OPEN_FOR_REVIEW, "impressao": services.PRINT_QUEUE,
              "concluidas": (S.DELIVERED,), "encerradas": (S.REJECTED, S.CANCELED, S.CORRECTION)}
    counts = {k: qs.filter(status__in=v).count() for k, v in groups.items()}
    if view in groups:
        qs = qs.filter(status__in=groups[view])
    else:
        view = "todas"
    if request.GET.get("prioridade") == "alta":
        qs = qs.filter(priority=PrintRequest.Priority.HIGH)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(activity__title__icontains=q) | Q(activity__class_group__name__icontains=q)
                       | Q(requested_by__first_name__icontains=q))
    page = paginate(request, qs.order_by("desired_date", "-priority", "created_at"))
    return render(request, "printing/queue.html", {
        "page": page, "rows": page, "view": view, "counts": counts, "q": q,
        "high": request.GET.get("prioridade") == "alta", "today": timezone.localdate(),
    })


def file_download(request, pk):
    req = get_object_or_404(PrintRequest, pk=pk)
    if not services.can_view(request.user, req):
        raise Http404
    if req.file:
        f, name = req.file, req.file_name or "arquivo"
    elif req.attachment:
        f, name = req.attachment.file, req.attachment.original_name
    else:
        raise Http404
    resp = FileResponse(f.open("rb"), as_attachment=True, filename=name, content_type=attachment_content_type(name))
    resp["Cache-Control"] = "private, no-store"
    return resp

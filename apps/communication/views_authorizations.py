"""Autorizações de passeio e atividades fora da rotina, respondidas pela família na plataforma.

Quem faz o quê:

- **criam:** professor (só as próprias turmas), coordenação (turmas da designação), direção, secretaria e
  administração;
- **acompanham:** quem criou e a equipe que alcança as turmas. Veem autorizados, não autorizados e sem
  resposta, e imprimem a lista de autorizados para o dia;
- **assinam:** o responsável com vínculo aprovado, por filho com matrícula ativa numa das turmas, até o
  prazo, com a senha de novo e o nome completo (``signatures``). A última assinatura vale; as anteriores ficam
  guardadas e todos os responsáveis recebem o comprovante. O estudante vê, mas não assina;
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

from . import signatures
from .models import Authorization, AuthorizationResponse, AuthorizationSignature, Notification
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
        fields = ["kind", "title", "description", "event_date", "valid_until", "deadline", "class_groups"]
        labels = {"title": "Título", "event_date": "Data da atividade (ou início da validade)"}
        help_texts = {
            "event_date": "Uso de imagem ou saída sozinho: a partir de quando vale.",
            "valid_until": "Só para uso de imagem e saída sozinho (ex.: fim do ano letivo). A família pode retirar a "
                           "autorização a qualquer momento até essa data.",
            "description": "Passeio: local, horários de saída e volta, transporte, o que levar, contato. Uso de "
                           "imagem: onde as fotos e vídeos aparecem (mural, site, redes) e por quanto tempo.",
        }
        widgets = {"event_date": DATE, "valid_until": DATE, "deadline": DATE,
                   "description": forms.Textarea(attrs={"rows": 5}), "class_groups": forms.CheckboxSelectMultiple()}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        qs = ClassGroup.objects.filter(pk__in=staff_class_ids(user) or [])
        current = qs.filter(school_year__is_current=True)  # turmas do ano letivo atual, quando ele está marcado
        self.fields["class_groups"].queryset = (current if current.exists() else qs).order_by("name")
        self.fields["kind"].required = False  # sem o campo, é passeio (como antes dos tipos)

    def clean(self):
        c = super().clean()
        c["kind"] = c.get("kind") or Authorization.Kind.TRIP
        today = timezone.localdate()
        ongoing = c.get("kind") in Authorization.ONGOING
        start, until, deadline = c.get("event_date"), c.get("valid_until"), c.get("deadline")
        if start and start < today and not ongoing:
            self.add_error("event_date", "A atividade já passou.")
        if ongoing:
            if not until:
                self.add_error("valid_until", "Diga até quando a autorização vale.")
            elif until < today:
                self.add_error("valid_until", "Essa data já passou.")
            elif start and until < start:
                self.add_error("valid_until", "Precisa ser depois do início da validade.")
            elif deadline and deadline > until:
                self.add_error("deadline", "O prazo de resposta precisa ser até o fim da validade.")
        else:
            c["valid_until"] = None
            if deadline and start and deadline > start:
                self.add_error("deadline", "O prazo de resposta precisa ser até o dia da atividade.")
        if deadline and deadline < today:
            self.add_error("deadline", "O prazo já passou.")
        return c


def _when(auth):
    if auth.ongoing:
        return f"Vale de {auth.event_date:%d/%m/%Y} até {auth.last_day():%d/%m/%Y}"
    return f"Atividade em {auth.event_date:%d/%m/%Y}"


def _guardians_of(class_ids):
    from apps.core.models import User
    from apps.registry.models import Enrollment, GuardianLink

    sids = Enrollment.objects.filter(class_group_id__in=class_ids, status="ativo").values_list("student_id", flat=True)
    gids = GuardianLink.objects.filter(student_id__in=sids, status="aprovado").values_list("guardian_id", flat=True)
    return User.objects.filter(pk__in=gids, is_active=True)


def authorization_list(request):
    user = request.user
    qs = visible(user)
    no_link = qs is None and user.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)
    if no_link:  # o menu mostra o item; sem vínculo aprovado a lista fica vazia, com o motivo
        qs = Authorization.objects.none()
    elif qs is None:
        raise PermissionDenied
    staff = staff_class_ids(user) is not None
    return render(request, "communication/authorization_list.html", {
        "no_link": no_link,
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
                    body=f"Responda até {auth.deadline:%d/%m/%Y}. " + _when(auth) + ".",
                    url=reverse("communication:authorization_detail", args=[auth.pk]))
        messages.success(request, "Autorização enviada às famílias.")
        return redirect("communication:authorization_detail", pk=auth.pk)
    return render(request, "communication/authorization_form.html", {"form": form})


def _staff_rows(auth, class_ids, checks=None):
    from apps.registry.models import Enrollment

    checks = checks or {}
    responses = {r.student_id: r for r in auth.responses.select_related("answered_by", "signature")}
    groups = []
    for cg in auth.class_groups.filter(pk__in=class_ids).order_by("name"):
        rows = []
        for e in Enrollment.objects.filter(class_group=cg, status="ativo").select_related("student") \
                .order_by("student__first_name", "student__last_name"):
            r = responses.get(e.student_id)
            rows.append({"student": e.student, "response": r,
                         "check": checks.get(r.signature_id) if r and r.signature_id else None})
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
        checks, broken = signatures.verify_all(auth)
        ctx["groups"] = _staff_rows(auth, ids | ({c.pk for c in auth.class_groups.all()}
                                                  if auth.created_by_id == user.pk else set()), checks)
        ctx["staff"] = True
        ctx["n_signatures"], ctx["broken"] = len(checks), broken
        ctx["outdated"] = sum(1 for g in ctx["groups"] for r in g["rows"] if r["check"] and not r["check"]["doc_ok"])
        if ctx["print"] and not auth.ongoing:
            _trip_care(user, auth, ctx["groups"])
    else:
        cls = {c.pk for c in auth.class_groups.all()}
        responses = {r.student_id: r for r in auth.responses.filter(student__in=list(_family_children(user)))
                     .select_related("signature")}
        revocable = auth.accepts_revocation() and not ctx["accepts"]
        ctx["children"] = [{"student": st, "response": responses.get(st.pk),
                            "revoke": revocable and getattr(responses.get(st.pk), "answer", "") == "autorizo"}
                           for st, cid in _family_children(user).items() if cid in cls]
        ctx["can_answer"] = user.role == Role.RESPONSAVEL.value
    return render(request, "communication/authorization_detail.html", ctx)


def _signable(user, pk, student_id):
    """(autorização, estudante) que este responsável pode assinar, ou PermissionDenied."""
    if user.role != Role.RESPONSAVEL.value:
        raise PermissionDenied
    auth = get_object_or_404(Authorization, pk=pk, school=user.school)
    cls = set(auth.class_groups.values_list("pk", flat=True))
    student = next((st for st, cid in _family_children(user).items() if st.pk == student_id and cid in cls), None)
    if student is None:
        raise PermissionDenied
    return auth, student


@require_POST
def authorization_answer(request, pk):
    """Endereço antigo de resposta rápida: sem assinatura não vale mais. Leva à tela de assinatura."""
    from apps.core.params import as_id

    auth, student = _signable(request.user, pk, as_id(request.POST.get("student")) or 0)
    messages.info(request, "Para responder, confira o texto e assine com a sua senha.")
    return redirect("communication:authorization_sign", pk=auth.pk, student_id=student.pk)


def authorization_sign(request, pk, student_id):
    """Assinatura da autorização: o texto inteiro, a resposta, o nome completo e a senha de novo."""
    user = request.user
    auth, student = _signable(user, pk, student_id)
    current = AuthorizationResponse.objects.filter(authorization=auth, student=student).select_related(
        "signature").first()
    # Depois do prazo, uso de imagem e saída sozinho ainda aceitam a retirada de quem autorizou (só "não autorizo").
    revoke_only = (not auth.accepts_answers() and auth.accepts_revocation()
                   and current is not None and current.answer == AuthorizationResponse.Answer.YES)
    if not auth.accepts_answers() and not revoke_only:
        messages.error(request, "O prazo de resposta terminou ou a autorização foi encerrada.")
        return redirect("communication:authorization_detail", pk=auth.pk)
    error, post = None, {}
    if request.method == "POST":
        post = {"answer": request.POST.get("answer", ""), "note": (request.POST.get("note") or "").strip()[:300],
                "nome": (request.POST.get("nome") or "").strip()[:150], "ciente": bool(request.POST.get("ciente"))}
        nonce, error = signatures.read_token(request.POST.get("token"), user, auth, student)
        if error is None:
            if signatures.locked(user):
                error = "Assinatura bloqueada por 15 minutos depois de 5 senhas erradas. Se não foi você, troque a senha."
            elif post["answer"] not in AuthorizationResponse.Answer.values:
                error = "Escolha autorizo ou não autorizo."
            elif revoke_only and post["answer"] != AuthorizationResponse.Answer.NO:
                error = "O prazo terminou: agora só é possível retirar a autorização."
            elif not post["ciente"]:
                error = "Confirme que leu o texto e que é responsável legal pelo estudante."
            elif not signatures.name_matches(user, post["nome"]):
                error = ("Digite o seu nome completo, como está na sua conta." if user.get_full_name()
                         else "Digite o seu nome completo (nome e sobrenome).")
            elif not user.check_password(request.POST.get("senha", "")):
                signatures.record_failure(request, user, auth)
                left = signatures.MAX_FAILURES - signatures.failures(user)
                error = (f"Senha incorreta. Restam {left} tentativa(s) antes do bloqueio de 15 minutos." if left > 0
                         else "Senha incorreta. Assinatura bloqueada por 15 minutos e você foi avisado(a).")
            else:
                sig = signatures.sign(request, auth, student, user, post["answer"], post["note"], post["nome"], nonce)
                if auth.ongoing and current and current.answer == "autorizo" and sig.answer == "nao_autorizo":
                    _tell_revoked(auth, student, sig)
                messages.success(request, f"Assinado: {sig.get_answer_display().lower()} ({student.first_name}). "
                                          f"Comprovante {sig.display_code}.")
                return redirect("communication:authorization_receipt", code=sig.code)
    from apps.care.models import HealthRecord

    return render(request, "communication/authorization_sign.html", {
        "auth": auth, "student": student, "current": current, "document": auth.document_text(), "error": error,
        "post": post, "token": signatures.issue_token(user, auth, student), "account_name": user.get_full_name(),
        "revoke_only": revoke_only,
        "health": HealthRecord.objects.filter(student=student).first() if not auth.ongoing else None})


def _tell_revoked(auth, student, sig):
    """Retirada de uso de imagem ou de saída sozinho: quem criou e a direção ficam sabendo na hora (a lista de
    fotos e a tela de retirada já mudam sozinhas)."""
    from apps.core.models import User

    what = "o uso de imagem" if auth.kind == Authorization.Kind.IMAGE else "a saída sozinho(a)"
    people = User.objects.filter(Q(pk=auth.created_by_id) | Q(school=auth.school, role=Role.DIRECAO.value),
                                 is_active=True)
    notify_many(auth.school, people, Notification.Kind.ANNOUNCEMENT,
                f"Autorização retirada: {what} de {student.full_name}",
                body=f"{sig.signer_name} retirou a autorização '{auth.title}' (comprovante {sig.display_code}).",
                url=reverse("communication:authorization_receipt", args=[sig.code]),
                dedupe_key=f"autorizacao-retirada:{sig.pk}", priority=Notification.Priority.HIGH)


def _can_see_signature(user, sig):
    from apps.registry.models import Enrollment, GuardianLink

    auth = sig.authorization
    if auth.school_id != user.school_id:
        return False
    if user.role == Role.RESPONSAVEL.value:
        return GuardianLink.objects.filter(guardian=user, student_id=sig.student_id, status="aprovado").exists()
    ids = staff_class_ids(user)
    if ids is None:
        return False
    if user.role in MANAGERS or auth.created_by_id == user.pk:
        return True
    reach = ids & set(auth.class_groups.values_list("pk", flat=True))
    return Enrollment.objects.filter(student_id=sig.student_id, class_group_id__in=reach).exists()


def authorization_receipt(request, code):
    """Comprovante de uma assinatura, com a conferência: selo, encadeamento, texto e se ainda vale."""
    from apps.gate.symbols import qr_svg

    sig = get_object_or_404(AuthorizationSignature.objects.select_related("authorization", "student", "signer"),
                            code=signatures.normalize_code(code))
    if not _can_see_signature(request.user, sig):
        raise PermissionDenied
    check = signatures.verify(sig)
    url = request.build_absolute_uri(reverse("communication:authorization_receipt", args=[sig.code]))
    if request.user.role != Role.RESPONSAVEL.value:
        create_audit_log(user=request.user, action="view", request=request, target=sig,
                         detail=f"Conferiu o comprovante {sig.display_code}")
    return render(request, "communication/authorization_receipt.html", {
        "sig": sig, "check": check, "qr": qr_svg(url, label=f"QR Code do comprovante {sig.display_code}"),
        "history": AuthorizationSignature.objects.filter(authorization=sig.authorization, student=sig.student)
        .select_related("signer").order_by("-pk")})


def authorization_verify(request):
    """Conferir um comprovante pelo código (papel, aviso, print de tela)."""
    raw = request.GET.get("codigo", "")
    code = signatures.normalize_code(raw)
    if raw and len(code) == 10:
        sig = AuthorizationSignature.objects.filter(code=code, authorization__school=request.user.school).first()
        if sig and _can_see_signature(request.user, sig):
            return redirect("communication:authorization_receipt", code=code)
    if raw:
        messages.error(request, "Comprovante não encontrado (ou de um estudante que você não acompanha). Confira os "
                                "10 caracteres.")
    return render(request, "communication/authorization_verify.html", {"codigo": raw[:20]})


def authorization_images(request):
    """Antes de publicar foto ou vídeo: quem da turma tem autorização de uso de imagem valendo hoje. Sem assinatura
    válida, não pode aparecer (``consents``)."""
    from apps.core.params import as_id
    from apps.registry.models import Enrollment

    from .consents import standing

    user = request.user
    ids = staff_class_ids(user)
    if ids is None:
        raise PermissionDenied
    classes = ClassGroup.objects.filter(pk__in=ids)
    current = classes.filter(school_year__is_current=True)
    classes = (current if current.exists() else classes).order_by("name")
    chosen = as_id(request.GET.get("turma"))
    shown = [c for c in classes if c.pk == chosen] if chosen else list(classes)
    enrollments = list(Enrollment.objects.filter(class_group__in=shown, status="ativo").select_related("student")
                       .order_by("student__first_name", "student__last_name"))
    rows = standing(user.school, Authorization.Kind.IMAGE, [e.student_id for e in enrollments])
    groups = []
    for cg in shown:
        yes, no = [], []
        for e in (e for e in enrollments if e.class_group_id == cg.pk):
            row = rows.get(e.student_id)
            (yes if row and row["granted"] else no).append(
                {"student": e.student, "sig": row and row["sig"], "auth": row and row["auth"],
                 "reason": row["reason"] if row else "sem resposta"})
        groups.append({"cg": cg, "yes": yes, "no": no})
    in_force = Authorization.objects.filter(school=user.school, kind=Authorization.Kind.IMAGE,
                                            event_date__lte=timezone.localdate(),
                                            valid_until__gte=timezone.localdate()) \
        .exclude(status=Authorization.Status.CANCELED)
    return render(request, "communication/authorization_images.html", {
        "groups": groups, "classes": classes, "chosen": chosen, "in_force": list(in_force),
        "can_create": bool(ids), "today": timezone.localdate()})


@require_POST
def authorization_remind(request, pk):
    """Lembrete a quem ainda não respondeu (uma vez por dia)."""
    from apps.core.models import User
    from apps.registry.models import Enrollment, GuardianLink

    user = request.user
    auth = get_object_or_404(Authorization, pk=pk, school=user.school)
    if not can_manage(user, auth) or not auth.accepts_answers():
        raise PermissionDenied
    answered = set(auth.responses.values_list("student_id", flat=True))
    sids = set(Enrollment.objects.filter(class_group__in=auth.class_groups.all(), status="ativo")
               .values_list("student_id", flat=True)) - answered
    guardians = User.objects.filter(pk__in=GuardianLink.objects.filter(student_id__in=sids, status="aprovado")
                                    .values_list("guardian_id", flat=True), is_active=True)
    n = notify_many(user.school, guardians, Notification.Kind.ANNOUNCEMENT, f"Lembrete: autorização {auth.title}",
                    body=f"Ainda falta a sua assinatura. Responda até {auth.deadline:%d/%m/%Y}.",
                    url=reverse("communication:authorization_detail", args=[auth.pk]),
                    dedupe_key=f"autorizacao-lembrete:{auth.pk}:{timezone.localdate():%Y%m%d}")
    create_audit_log(user=user, action="update", request=request, target=auth,
                     detail=f"Lembrou {n} responsável(is) sem resposta em '{auth.title}'")
    messages.success(request, f"Lembrete enviado a {n} responsável(is)." if n else
                     "Ninguém para lembrar hoje (todos responderam ou já receberam o lembrete de hoje).")
    return redirect("communication:authorization_detail", pk=auth.pk)


def _trip_care(user, auth, groups):
    """Para a lista impressa do passeio: alertas de saúde e o primeiro contato de emergência dos autorizados
    (em ``row["care"]``), só do que a pessoa pode ver (``care.access``). Quem leva a turma precisa disso fora da
    escola."""
    from apps.care.access import health_level
    from apps.care.models import EmergencyContact, HealthRecord

    ids = [r["student"].pk for g in groups for r in g["rows"] if r["response"] and r["response"].answer == "autorizo"]
    records = {h.student_id: h for h in HealthRecord.objects.filter(student_id__in=ids)}
    contacts = {}
    for c in EmergencyContact.objects.filter(student_id__in=ids).order_by("order"):
        contacts.setdefault(c.student_id, c)
    shown = 0
    for g in groups:
        for r in g["rows"]:
            st = r["student"]
            if st.pk not in ids:
                continue
            level = health_level(user, st)
            if level is None and not can_manage(user, auth):
                continue
            h = records.get(st.pk)
            r["care"] = {"alert": h if h and h.has_alert and level else None,
                         "contact": contacts.get(st.pk) if (level == "full" or can_manage(user, auth)) else None}
            shown += bool(r["care"]["alert"] or r["care"]["contact"])
    if shown:
        create_audit_log(user=user, action="view", request=None, target=auth,
                         detail=f"Abriu a lista de autorizados de '{auth.title}' com alertas de saúde e contatos")


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

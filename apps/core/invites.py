"""Cadastro de escolas e convites da equipe.

**Quem faz o quê**

- **Administrador da plataforma** (perfil Administrador com ``is_superuser``, o criado por ``initadmin``):
  cadastra qualquer escola, gera convites de qualquer perfil para qualquer escola e pode passar a trabalhar
  numa escola (troca a escola da própria conta).
- **Direção e administração da escola:** geram convites da própria escola. A direção convida coordenação,
  secretaria e professores; convite de direção e de administração só sai do administrador da plataforma ou
  da administração da escola.

**Código:** 12 símbolos do alfabeto de Crockford (sem I, L, O e U), 11 aleatórios (``secrets``, 55 bits) e
1 verificador Luhn mod 32, que pega erro de digitação antes de consultar o banco. Mostrado em grupos de 4.

**Segurança**

- O perfil e a escola vêm do código, nunca do formulário.
- Prazo, limite de usos e cancelamento a qualquer momento.
- Aprovação da direção ligada por padrão para secretaria e administração (veem dados de todos os estudantes).
  Professor e coordenação sem atribuição ou designação não alcançam dado de estudante; mesmo assim a escola
  pode exigir aprovação em qualquer convite.
- Tentativas com código errado são contadas por endereço: 10 em uma hora bloqueiam novas tentativas.
- Conta recusada é apagada (nunca funcionou); fica só o nome no histórico do convite.
"""

import datetime
import secrets

from django.db import transaction
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

from .models import AuditLog, InviteCode, InviteSignup, Role, User

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ALIASES = {"O": "0", "I": "1", "L": "1"}
CODE_LENGTH = 12
FAILED_LIMIT_PER_HOUR = 10
SIGNUP_LIMIT_PER_HOUR = 10

# Padrões por perfil: (limite de cadastros, dias de validade, exige aprovação)
DEFAULTS = {
    Role.DIRECAO.value: (1, 14, False),
    Role.ADMIN.value: (1, 14, True),
    Role.SECRETARIA.value: (5, 30, True),
    Role.COORDENACAO.value: (10, 30, False),
    Role.PROFESSOR.value: (60, 30, False),
}
# Quem vai aprovar recebe o aviso e vê a pendência.
APPROVERS = (Role.DIRECAO.value, Role.ADMIN.value)


# --------------------------------------------------------------------------- código


def _check_char(body):
    factor, total, n = 2, 0, len(ALPHABET)
    for ch in reversed(body):
        addend = factor * ALPHABET.index(ch)
        factor = 1 if factor == 2 else 2
        total += addend // n + addend % n
    return ALPHABET[(n - total % n) % n]


def normalize(text):
    t = "".join(ch for ch in (text or "").upper() if ch.isascii() and ch.isalnum())
    return "".join(ALIASES.get(ch, ch) for ch in t)


def valid_shape(code):
    return (len(code) == CODE_LENGTH and all(ch in ALPHABET for ch in code)
            and _check_char(code[:-1]) == code[-1])


def new_code():
    while True:
        body = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH - 1))
        code = body + _check_char(body)
        if not InviteCode.objects.filter(code=code).exists():
            return code


# --------------------------------------------------------------------------- permissões


def is_platform_admin(user):
    return bool(getattr(user, "is_authenticated", False) and user.role == Role.ADMIN.value and user.is_superuser)


def can_manage_school(user, school):
    """Gerar e cancelar convites, aprovar cadastros e ver a equipe da escola."""
    if is_platform_admin(user):
        return True
    return (getattr(user, "is_authenticated", False) and user.role in APPROVERS
            and user.school_id is not None and user.school_id == school.pk)


def roles_user_can_invite(user):
    if is_platform_admin(user) or user.role == Role.ADMIN.value:
        return [r.value for r in InviteCode.ROLES]
    if user.role == Role.DIRECAO.value:
        return [Role.COORDENACAO.value, Role.SECRETARIA.value, Role.PROFESSOR.value]
    return []


# --------------------------------------------------------------------------- convites


def create_invite(school, role, user, note="", max_uses=None, days=None, requires_approval=None):
    uses, valid_days, approval = DEFAULTS[role]
    return InviteCode.objects.create(
        school=school, role=role, code=new_code(), note=note[:120],
        max_uses=max_uses or uses,
        expires_at=timezone.now() + datetime.timedelta(days=days or valid_days),
        requires_approval=approval if requires_approval is None else requires_approval,
        created_by=user)


def with_usage(qs):
    """Convites com ``used`` (cadastros que contam: pendentes e ativos; recusados liberam a vaga)."""
    return qs.annotate(used=Count("signups", filter=~Q(signups__status=InviteSignup.Status.REJECTED)))


def state(invite, now=None):
    """("ativo" | "cancelado" | "vencido" | "esgotado", texto para quem tenta usar)."""
    now = now or timezone.now()
    used = getattr(invite, "used", None)
    if used is None:
        used = invite.signups.exclude(status=InviteSignup.Status.REJECTED).count()
    if invite.revoked_at:
        return "cancelado", "Este código foi cancelado. Peça um novo a quem o enviou."
    if invite.expires_at <= now:
        return "vencido", f"Este código venceu em {timezone.localtime(invite.expires_at):%d/%m/%Y}. Peça um novo."
    if used >= invite.max_uses:
        return "esgotado", "Este código já foi usado o número máximo de vezes. Peça um novo a quem o enviou."
    return "ativo", ""


def find(raw):
    """(convite, erro). O erro é seguro para mostrar a quem digitou."""
    code = normalize(raw)
    if not code:
        return None, "Informe o código de convite."
    if not valid_shape(code):
        return None, "Código de convite inválido: confira os 12 caracteres."
    invite = InviteCode.objects.select_related("school").filter(code=code).first()
    if invite is None:
        return None, "Código de convite não encontrado. Confira com quem o enviou."
    status, message = state(invite)
    return (invite, "") if status == "ativo" else (None, message)


def revoke(invite, user):
    invite.revoked_at = timezone.now()
    invite.revoked_by = user
    invite.save(update_fields=["revoked_at", "revoked_by"])


# --------------------------------------------------------------------------- cadastro e aprovação


def too_many(request, detail_prefix, limit):
    ip = request.META.get("REMOTE_ADDR")
    if not ip:
        return False
    since = timezone.now() - datetime.timedelta(hours=1)
    return AuditLog.objects.filter(detail__startswith=detail_prefix, ip_address=ip,
                                   created_at__gte=since).count() >= limit


@transaction.atomic
def sign_up(invite, data):
    """Cria a conta do convite. Trava o convite para dois cadastros simultâneos não passarem do limite."""
    invite = InviteCode.objects.select_for_update().get(pk=invite.pk)
    status, message = state(invite)
    if status != "ativo":
        raise ValueError(message)
    pending = invite.requires_approval
    user = User(username=data["username"], first_name=data["first_name"], last_name=data.get("last_name", ""),
                email=data.get("email", ""), phone=data.get("phone", ""), role=invite.role, school=invite.school,
                is_active=not pending)
    user.set_password(data["password1"])
    user.save()
    signup = InviteSignup.objects.create(
        invite=invite, user=user, name=user.get_full_name() or user.username, username=user.username,
        status=InviteSignup.Status.PENDING if pending else InviteSignup.Status.APPROVED)
    if pending:
        _notify_approvers(signup)
    return signup


def _approvers(school):
    return User.objects.filter(school=school, role__in=APPROVERS, is_active=True)


def _notify_approvers(signup):
    from apps.communication.models import Notification
    from apps.communication.services import notify_many

    invite = signup.invite
    notify_many(invite.school, _approvers(invite.school), Notification.Kind.REQUEST,
                f"Cadastro aguardando aprovação: {signup.name} ({invite.get_role_display()})",
                body=f"Usou o código {invite.display_code}" + (f" ({invite.note})" if invite.note else "") + ".",
                url=reverse("school_team", args=[invite.school_id]), dedupe_key=f"convite:{signup.pk}")


def pending_for(school):
    return InviteSignup.objects.filter(invite__school=school, status=InviteSignup.Status.PENDING) \
        .select_related("invite", "user")


@transaction.atomic
def decide(signup, approve, user):
    signup.decided_by = user
    signup.decided_at = timezone.now()
    if approve:
        signup.status = InviteSignup.Status.APPROVED
        signup.user.is_active = True
        signup.user.save(update_fields=["is_active"])
        signup.save(update_fields=["status", "decided_by", "decided_at"])
        return
    signup.status = InviteSignup.Status.REJECTED
    account = signup.user
    signup.user = None
    signup.save(update_fields=["status", "decided_by", "decided_at", "user"])
    account.delete()


def awaiting_approval(username, password):
    """Para a tela de login dizer "aguarda aprovação" a quem acertou a senha de uma conta ainda pendente
    (sem revelar nada a quem errou a senha)."""
    user = User.objects.filter(username__iexact=(username or "").strip(), is_active=False).first()
    if user is None or not user.check_password(password or ""):
        return False
    return InviteSignup.objects.filter(user=user, status=InviteSignup.Status.PENDING).exists()

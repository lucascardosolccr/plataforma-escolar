"""Recuperação de senha sem a escola e sem e-mail: códigos de uso único.

Fluxo:

1. Na conta (Alterar senha → Códigos de recuperação), a pessoa confirma a senha
   atual e gera 8 códigos. Eles aparecem uma única vez, para imprimir ou anotar.
   Gerar de novo invalida os anteriores.
2. Esqueceu a senha: na tela de entrada, "Esqueci minha senha" pede o usuário,
   um código e a senha nova. O código vale uma vez.

Segurança:

- só o hash do código fica no banco (HMAC-SHA-256 com a SECRET_KEY);
- cada falha conta no mesmo limite do login (``ThrottledAuthenticationForm``):
  5 falhas por usuário ou 20 por endereço em 15 minutos pausam as tentativas,
  mesmo com o código certo;
- a mensagem de erro é a mesma para usuário inexistente, conta inativa e
  código errado, para não revelar quais contas existem;
- a senha nova passa pelos mesmos validadores da troca de senha, e um erro de
  validação não gasta o código;
- tudo vai para a auditoria, e a pessoa recebe um aviso na central.
"""

import hashlib
import hmac
import secrets

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import password_validation
from django.contrib.auth.decorators import login_not_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import ThrottledAuthenticationForm
from .models import RecoveryCode, User, create_audit_log

CODE_COUNT = 8
# Sem caracteres ambíguos (O/0, I/1/L): o código é copiado de um papel.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
GENERIC_ERROR = "Usuário ou código inválido. Confira os dados; cada código vale uma vez."


def _normalize(code):
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def code_hash(code):
    return hmac.new(settings.SECRET_KEY.encode(), _normalize(code).encode(), hashlib.sha256).hexdigest()


def new_code():
    raw = "".join(secrets.choice(_ALPHABET) for _ in range(10))
    return f"{raw[:5]}-{raw[5:]}"


def generate_codes(user):
    """Apaga os códigos anteriores e cria novos; devolve os códigos em claro (mostrados uma vez)."""
    codes = [new_code() for _ in range(CODE_COUNT)]
    with transaction.atomic():
        RecoveryCode.objects.filter(user=user).delete()
        RecoveryCode.objects.bulk_create([RecoveryCode(user=user, code_hash=code_hash(c)) for c in codes])
    return codes


class ConfirmPasswordForm(forms.Form):
    password = forms.CharField(label="Sua senha atual", widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        if not self.user.check_password(self.cleaned_data["password"]):
            raise forms.ValidationError("Senha incorreta.")
        return self.cleaned_data["password"]


class RecoverForm(forms.Form):
    username = forms.CharField(label="Usuário", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "username"}))
    code = forms.CharField(label="Código de recuperação", max_length=20,
                           help_text="Um dos códigos da folha que você gerou, como ABCDE-23456.")
    new_password1 = forms.CharField(label="Nova senha", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                    help_text=password_validation.password_validators_help_text_html())
    new_password2 = forms.CharField(label="Repita a nova senha",
                                    widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("new_password1"), cleaned.get("new_password2")
        if p1 and p2 and p1 != p2:
            self.add_error("new_password2", "As duas senhas não são iguais.")
        return cleaned


def recovery_codes(request):
    user = request.user
    form = ConfirmPasswordForm(request.POST or None, user=user)
    codes = None
    if request.method == "POST" and form.is_valid():
        codes = generate_codes(user)
        create_audit_log(user=user, action="update", request=request, target=user,
                         detail="Gerou novos códigos de recuperação de senha (os anteriores deixaram de valer)")
        form = ConfirmPasswordForm(user=user)
    qs = RecoveryCode.objects.filter(user=user)
    return render(request, "core/recovery_codes.html", {
        "form": form, "codes": codes, "unused": qs.filter(used_at__isnull=True).count(),
        "generated_at": qs.order_by("-created_at").values_list("created_at", flat=True).first(),
    })


def _fail(request, username):
    # Conta no limite de tentativas do login (mesma ação e mesmo alvo).
    create_audit_log(user=None, action="login_failed", request=request, target_type="login",
                     target_id=username[:50], detail=f"Falha na recuperação de senha para: {username}")


@login_not_required
def password_recover(request):
    if request.user.is_authenticated:
        return redirect("password_change")
    form = RecoverForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        if ThrottledAuthenticationForm(request)._is_locked(username):
            form.add_error(None, ThrottledAuthenticationForm.error_messages["locked"])
            return render(request, "registration/password_recover.html", {"form": form})
        user = User.objects.filter(username=username, is_active=True).first()
        rc = (RecoveryCode.objects.filter(user=user, code_hash=code_hash(form.cleaned_data["code"]),
                                          used_at__isnull=True).first() if user else None)
        if rc is None:
            _fail(request, username)
            form.add_error(None, GENERIC_ERROR)
            return render(request, "registration/password_recover.html", {"form": form})
        try:
            password_validation.validate_password(form.cleaned_data["new_password1"], user)
        except forms.ValidationError as exc:
            form.add_error("new_password1", exc)  # o código não é gasto
            return render(request, "registration/password_recover.html", {"form": form})
        with transaction.atomic():
            rc.used_at = timezone.now()
            rc.save(update_fields=["used_at"])
            user.set_password(form.cleaned_data["new_password1"])
            user.must_change_password = False
            user.save(update_fields=["password", "must_change_password"])
            # "Redefiniu a senha" zera a contagem de falhas da conta (ver ThrottledAuthenticationForm).
            create_audit_log(user=user, action="update", request=request, target=user,
                             detail=f"Redefiniu a senha de {user.username} com um código de recuperação")
        left = RecoveryCode.objects.filter(user=user, used_at__isnull=True).count()
        if user.school_id:
            from apps.communication.models import Notification
            from apps.communication.services import notify

            notify(user.school, user, Notification.Kind.REQUEST, "Senha redefinida com um código de recuperação",
                   f"Se não foi você, procure a escola. Restam {left} código(s).", url=reverse("recovery_codes"))
        messages.success(request, f"Senha redefinida. Entre com a nova senha. Restam {left} código(s) de recuperação.")
        return redirect("login")
    return render(request, "registration/password_recover.html", {"form": form})

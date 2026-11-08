from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError

from .models import Role, STAFF_ROLES, School, User


def _check_password(form, password, user):
    try:
        password_validation.validate_password(password, user=user)
    except ValidationError as exc:
        form.add_error("password1", exc)


class ProfessionalUserForm(forms.ModelForm):
    """Criação de conta por um administrador (nunca autoassinável).
    Disponibiliza apenas perfis profissionais + responsável; a senha é
    temporária e o usuário deve trocá-la no primeiro acesso guiado.
    """

    role = forms.ChoiceField(
        label="Perfil",
        choices=[(r.value, r.label) for r in STAFF_ROLES] + [(Role.RESPONSAVEL.value, Role.RESPONSAVEL.label)],
    )
    password1 = forms.CharField(
        label="Senha temporária",
        widget=forms.PasswordInput,
        help_text="O usuário deve trocar a senha após o primeiro acesso.",
    )
    password2 = forms.CharField(
        label="Confirmação da senha temporária",
        widget=forms.PasswordInput,
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "email", "phone", "staff_code", "role", "school"]
        labels = {
            "username": "Usuário (login)",
            "first_name": "Nome",
            "last_name": "Sobrenome",
            "email": "E-mail",
            "school": "Escola",
        }

    def __init__(self, *args, allowed_schools=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["school"].required = True
        if allowed_schools is not None:
            self.fields["school"].queryset = allowed_schools

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Já existe um usuário com este login.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "As senhas não coincidem.")
        elif p1 and p2:
            user = User(
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
                email=cleaned.get("email", ""),
            )
            _check_password(self, p1, user)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        # A senha é digitada por quem cria a conta, portanto é conhecida por
        # outra pessoa. A troca passa a ser exigida no primeiro acesso, em vez
        # de ficar só como recomendação no texto de ajuda.
        user.must_change_password = True
        if commit:
            user.save()
        return user


class PublicSignupForm(forms.Form):
    """Cadastro público de responsável.

    O perfil é SEMPRE forçado para RESPONSAVEL no servidor — é impossível
    se autodeclarar professor, secretário ou diretor por esta via.
    """

    school_code = forms.CharField(label="Código da escola", max_length=50)
    username = forms.CharField(label="Usuário (login)", max_length=150)
    first_name = forms.CharField(label="Nome", max_length=120)
    last_name = forms.CharField(label="Sobrenome", max_length=120, required=False)
    email = forms.EmailField(label="E-mail")
    phone = forms.CharField(label="Telefone", max_length=30, required=False)
    password1 = forms.CharField(label="Senha", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmação da senha", widget=forms.PasswordInput)

    def clean_school_code(self):
        code = self.cleaned_data["school_code"].strip().lower()
        try:
            return School.objects.get(code__iexact=code)
        except School.DoesNotExist:
            raise forms.ValidationError("Código de escola não encontrado. Verifique com a secretaria.")

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Já existe um usuário com este login.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "As senhas não coincidem.")
        elif p1 and p2:
            user = User(
                username=cleaned.get("username", ""),
                first_name=cleaned.get("first_name", ""),
                last_name=cleaned.get("last_name", ""),
                email=cleaned.get("email", ""),
            )
            _check_password(self, p1, user)
        return cleaned

    def save(self):
        from django.db import transaction

        with transaction.atomic():
            user = User(
                username=self.cleaned_data["username"],
                first_name=self.cleaned_data["first_name"],
                last_name=self.cleaned_data["last_name"],
                email=self.cleaned_data["email"],
                school=self.cleaned_data["school_code"],
                role=Role.RESPONSAVEL.value,
            )
            user.set_password(self.cleaned_data["password1"])
            user.save()
            from apps.registry.models import GuardianProfile

            GuardianProfile.objects.create(
                user=user, phone=self.cleaned_data["phone"]
            )
        return user

class ThrottledAuthenticationForm(AuthenticationForm):
    """Login com limite de tentativas, contadas no registro de auditoria.

    Sem limite, um robô podia testar senhas sem parar contra contas de
    famílias e da equipe, que dão acesso a dados de crianças. As falhas já
    eram gravadas na auditoria (``signals.on_login_failed``); aqui elas são
    contadas numa janela de tempo, sem cache nem dependência nova, e valem
    mesmo depois de reiniciar o servidor.

    O bloqueio vale para o nome digitado, exista a conta ou não: a mensagem
    não revela se o usuário existe.
    """

    WINDOW_MINUTES = 15
    MAX_PER_USERNAME = 5
    MAX_PER_IP = 20

    error_messages = {
        **AuthenticationForm.error_messages,
        "invalid_login": "Usuário ou senha incorretos. Verifique os dados e tente novamente.",
        "locked": (
            "Muitas tentativas sem sucesso. Por segurança, o acesso foi pausado por "
            "15 minutos. Se esqueceu a senha, use um código de recuperação ou peça uma nova à "
            "secretaria ou à administração da escola."
        ),
    }

    def clean(self):
        username = (self.data.get("username") or "").strip()
        if username and self._is_locked(username):
            raise ValidationError(self.error_messages["locked"], code="locked")
        try:
            return super().clean()
        except ValidationError:
            from .invites import awaiting_approval

            # Só quem acertou a senha de um cadastro por convite ainda pendente fica sabendo; para os
            # demais, a mensagem continua a mesma de sempre.
            if awaiting_approval(username, self.data.get("password")):
                raise ValidationError(
                    "Seu cadastro ainda aguarda a aprovação da direção da escola. Você vai conseguir entrar "
                    "assim que ele for aprovado.", code="pending")
            raise

    def _is_locked(self, username):
        from datetime import timedelta

        from django.utils import timezone

        from .models import AuditLog

        since = timezone.now() - timedelta(minutes=self.WINDOW_MINUTES)
        recent = AuditLog.objects.filter(action="login_failed", created_at__gte=since)
        # Senha nova dada pela escola zera a contagem da conta: quem errou,
        # pediu ajuda e recebeu outra senha entra na hora, sem esperar.
        by_name = recent.filter(target_type="login", target_id=username[:50])
        account = User.objects.filter(username=username).only("pk").first()
        if account:
            reset = (
                AuditLog.objects.filter(target_type="User", target_id=str(account.pk),
                                        detail__startswith="Redefiniu a senha", created_at__gte=since)
                .order_by("-created_at").values_list("created_at", flat=True).first()
            )
            if reset:
                by_name = by_name.filter(created_at__gt=reset)
        if by_name.count() >= self.MAX_PER_USERNAME:
            return True
        ip = self.request.META.get("REMOTE_ADDR") if self.request else None
        return bool(ip) and recent.filter(ip_address=ip).count() >= self.MAX_PER_IP


UFS = ("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO").split()


class SchoolForm(forms.ModelForm):
    """Cadastro da escola pelo administrador da plataforma."""

    code = forms.CharField(label="Código da escola", max_length=50, required=False,
                           help_text="As famílias digitam no cadastro de responsável. Em branco, sai do nome "
                                     "(ex.: emef-joao-cabral).")
    inep = forms.CharField(label="Código INEP", max_length=12, required=False,
                           help_text="8 algarismos do Censo Escolar, quando a escola tem.")

    class Meta:
        model = School
        fields = ["name", "code", "inep", "city", "uf"]

    def clean(self):
        from django.utils.text import slugify

        cleaned = super().clean()
        typed = cleaned.get("code", "")
        code = slugify(typed or cleaned.get("name", ""))[:50].strip("-")
        if not code:
            self.add_error("code", "Use letras e números (ex.: emef-joao-cabral).")
            return cleaned
        taken = School.objects.exclude(pk=self.instance.pk)
        if typed and taken.filter(code=code).exists():
            self.add_error("code", "Já existe uma escola com este código.")
        elif not typed:  # gerado do nome: acrescenta -2, -3… se já existir
            base, n = code[:46], 2
            while taken.filter(code=code).exists():
                code, n = f"{base}-{n}", n + 1
        cleaned["code"] = code
        return cleaned

    def clean_inep(self):
        inep = "".join(ch for ch in self.cleaned_data["inep"] if ch.isdigit())
        if inep and len(inep) != 8:
            raise forms.ValidationError("O código INEP tem 8 algarismos.")
        if inep and School.objects.filter(inep=inep).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Já existe uma escola com este código INEP.")
        return inep

    def clean_uf(self):
        uf = self.cleaned_data["uf"].strip().upper()
        if uf and uf not in UFS:
            raise forms.ValidationError("UF inválida.")
        return uf


class InviteForm(forms.Form):
    """Novo código de convite. Em branco, limite e prazo seguem o padrão do perfil."""

    role = forms.ChoiceField(label="Perfil de quem vai se cadastrar")
    note = forms.CharField(label="Para quem (opcional)", max_length=120, required=False,
                           help_text="Aparece só para a escola. Ex.: \"Professores do 6º ao 9º ano\".")
    max_uses = forms.IntegerField(label="Limite de cadastros", min_value=1, max_value=500, required=False,
                                  help_text="Em branco: 1 para direção e administração, 5 para secretaria, "
                                            "10 para coordenação, 60 para professores.")
    days = forms.IntegerField(label="Válido por (dias)", min_value=1, max_value=90, required=False,
                              help_text="Em branco: 14 dias para direção e administração, 30 para os demais.")
    approval = forms.ChoiceField(
        label="Aprovação da direção", initial="padrao",
        choices=[("padrao", "Padrão do perfil (exige para secretaria e administração)"),
                 ("sim", "Exigir para cada cadastro"), ("nao", "Não exigir")])

    def __init__(self, *args, roles=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["role"].choices = [(r, Role(r).label) for r in roles]

    def approval_value(self):
        return {"sim": True, "nao": False}.get(self.cleaned_data["approval"])


class InviteSignupForm(forms.Form):
    """Cadastro da equipe com o código de convite. Perfil e escola vêm do código, nunca daqui."""

    code = forms.CharField(label="Código de convite", max_length=40,
                           help_text="12 caracteres, recebidos da direção ou da administração.")
    first_name = forms.CharField(label="Nome", max_length=120)
    last_name = forms.CharField(label="Sobrenome", max_length=120)
    email = forms.EmailField(label="E-mail")
    phone = forms.CharField(label="Telefone", max_length=30, required=False)
    username = forms.CharField(label="Usuário (login)", max_length=150,
                               help_text="Sem espaço. É com ele que você vai entrar.")
    password1 = forms.CharField(label="Senha", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmação da senha", widget=forms.PasswordInput)

    def clean_code(self):
        from .invites import find

        invite, error = find(self.cleaned_data["code"])
        if invite is None:
            raise forms.ValidationError(error)
        self.invite = invite
        return invite.code

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if not username or any(ch.isspace() for ch in username):
            raise forms.ValidationError("Use um usuário sem espaço.")
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Já existe um usuário com este login.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "As senhas não coincidem.")
        elif p1 and p2:
            _check_password(self, p1, User(username=cleaned.get("username", ""), first_name=cleaned.get("first_name", ""),
                                           last_name=cleaned.get("last_name", ""), email=cleaned.get("email", "")))
        return cleaned

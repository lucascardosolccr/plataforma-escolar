from django import forms

from .models import Role, STAFF_ROLES, School, User


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
        fields = ["username", "first_name", "last_name", "email", "role", "school"]
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
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
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
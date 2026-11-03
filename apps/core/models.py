from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .uploads import safe_photo_path, validate_photo


class School(models.Model):
    name = models.CharField("nome", max_length=200)
    code = models.SlugField("código", max_length=50, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "escola"
        verbose_name_plural = "escolas"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Role(models.TextChoices):
    ADMIN = "admin", "Administrador"
    DIRECAO = "direcao", "Direção"
    COORDENACAO = "coordenacao", "Coordenação Pedagógica"
    SECRETARIA = "secretaria", "Secretaria"
    PROFESSOR = "professor", "Professor"
    RESPONSAVEL = "responsavel", "Responsável"
    # Conta do próprio estudante. Nunca é criada pelo cadastro público nem
    # pela tela de contas profissionais: só a partir da ficha do estudante,
    # pela secretaria, para que o acesso fique obrigatoriamente vinculado a
    # uma matrícula real.
    ESTUDANTE = "estudante", "Estudante"


STAFF_ROLES = [
    Role.ADMIN,
    Role.DIRECAO,
    Role.COORDENACAO,
    Role.SECRETARIA,
    Role.PROFESSOR,
]


class User(AbstractUser):
    role = models.CharField(
        "perfil",
        max_length=20,
        choices=Role.choices,
        default=Role.RESPONSAVEL,
    )
    school = models.ForeignKey(
        School,
        verbose_name="escola",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )
    phone = models.CharField("telefone", max_length=30, blank=True)
    staff_code = models.CharField("identificação funcional", max_length=40, blank=True,
                                  help_text="Matrícula funcional, quando a escola usa.")
    photo = models.ImageField(
        "fotografia", upload_to=safe_photo_path, validators=[validate_photo], null=True, blank=True,
        help_text="Identificação visual. Nunca usada para reconhecimento facial.",
    )
    must_change_password = models.BooleanField(
        "precisa trocar a senha",
        default=False,
        help_text=(
            "Marcado quando a conta nasce com senha temporária ou quando a "
            "senha é redefinida pela escola. Enquanto estiver marcado, o "
            "usuário só consegue acessar a tela de troca de senha."
        ),
    )

    class Meta:
        verbose_name = "usuário"
        verbose_name_plural = "usuários"

    @property
    def role_label(self):
        return Role(self.role).label

    @property
    def is_staff_role(self):
        return self.role in [r.value for r in STAFF_ROLES]


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ("login", "Login"),
        ("login_failed", "Falha de login"),
        ("logout", "Logout"),
        ("create", "Criação"),
        ("update", "Atualização"),
        ("delete", "Exclusão"),
        ("approve", "Aprovação"),
        ("reject", "Rejeição"),
        # Exportação de dados (CSV/Excel): quem levou quais dados para fora.
        ("export", "Exportação"),
        # Prompt 15: dado sensível (necessidades específicas, laudos).
        ("view", "Consulta"),
        ("download", "Download"),
        ("import", "Importação"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="usuário",
    )
    school = models.ForeignKey(
        School,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="escola",
    )
    action = models.CharField("ação", max_length=20, choices=ACTION_CHOICES)
    target_type = models.CharField("tipo de registro", max_length=100, blank=True)
    target_id = models.CharField("identificador", max_length=50, blank=True)
    detail = models.TextField("detalhes", blank=True)
    ip_address = models.GenericIPAddressField("IP", null=True, blank=True)
    created_at = models.DateTimeField("data", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.target_type}"


def create_audit_log(*, user, action, request=None, target=None, detail="", school=None, target_id=None,
                     target_type=None):
    return AuditLog.objects.create(
        user=user,
        school=school or getattr(user, "school", None),
        action=action,
        target_type=target_type if target_type is not None else (target.__class__.__name__ if target else ""),
        target_id=target_id if target_id is not None else (getattr(target, "pk", "") if target else ""),
        detail=detail,
        ip_address=getattr(request, "META", {}).get("REMOTE_ADDR"),
    )


def audit_trail(obj):
    """Registros da auditoria sobre ``obj``: da mesma escola e de depois que ele foi criado.

    Tipo e número não bastam. No SQLite, quando uma migração recria uma tabela vazia, a numeração recomeça,
    e um registro novo herdava o histórico de outro já apagado, até de outra escola (visto em 03/11/2026
    numa solicitação). Entradas sem escola (conta de sistema) continuam aparecendo.
    """
    from datetime import timedelta

    from django.db.models import Q

    qs = AuditLog.objects.filter(target_type=obj.__class__.__name__, target_id=str(obj.pk))
    school_id = getattr(obj, "school_id", None)
    if school_id:
        qs = qs.filter(Q(school_id=school_id) | Q(school__isnull=True))
    created = getattr(obj, "created_at", None)
    if created:
        qs = qs.filter(created_at__gte=created - timedelta(minutes=1))
    return qs.select_related("user")


class PrivacyContact(models.Model):
    """Controlador e encarregado pelo tratamento de dados pessoais da escola (LGPD, art. 5º, VI e VIII, e art. 41).

    A identidade e o contato do encarregado devem ser divulgados publicamente, de forma clara (art. 41, § 1º):
    por isso a página de privacidade abre sem login. Quem preenche é a direção ou a administração."""

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="privacy_contact")
    controller = models.CharField("controlador dos dados", max_length=200,
                                  help_text="Quem decide sobre o tratamento dos dados. Em escola pública, em geral "
                                            "a secretaria de educação; em escola particular, a mantenedora.")
    officer_name = models.CharField("encarregado (LGPD, art. 41)", max_length=150,
                                    help_text="Pessoa ou setor que atende os titulares e a ANPD.")
    officer_email = models.EmailField("e-mail do encarregado", blank=True)
    officer_phone = models.CharField("telefone do encarregado", max_length=40, blank=True)
    channel = models.TextField("como fazer um pedido", blank=True,
                               help_text="Ex.: pela plataforma, em Solicitações; na secretaria; por e-mail.")
    responders = models.CharField("quem responde aos pedidos na escola", max_length=200, blank=True,
                                  help_text="Ex.: direção e secretaria escolar.")
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "contato de privacidade"
        verbose_name_plural = "contatos de privacidade"

    def __str__(self):
        return f"{self.school}: {self.officer_name}"


class UserPreference(models.Model):
    """Favoritos do menu e filtros salvos, guardados na conta.

    Antes ficavam só no navegador; aqui acompanham a pessoa em qualquer
    computador. Guarda apenas chaves do menu e endereços internos com filtros
    (nunca dados de estudante): ver ``views_prefs.save_preferences``.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")
    favorites = models.JSONField("favoritos do menu", default=list, blank=True)
    saved_filters = models.JSONField("filtros salvos", default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def as_json(self):
        return {"saved": True, "favorites": self.favorites, "filters": self.saved_filters}


class FollowUp(models.Model):
    """Pendência acompanhada (Prompt 15 §6.4): responsável, prazo, situação e histórico.

    A central de pendências calcula as pendências a partir do estado real dos
    registros (chamada sem registro, nota sem lançamento...). Isso diz o QUE
    falta, mas não QUEM resolve nem ATÉ QUANDO. Esta tabela registra a
    atribuição: uma pessoa da equipe abre a pendência, escolhe o responsável e
    o prazo, e cada mudança fica no histórico (``FollowUpEvent``). Nada é
    apagado: encerrar é mudar a situação. A família nunca vê estas pendências.
    """

    class Category(models.TextChoices):
        DOCUMENTACAO = "documentacao", "Documentação"
        ATIVIDADES = "atividades", "Atividades"
        REGISTROS = "registros", "Registros pedagógicos"
        AVALIACOES = "avaliacoes", "Avaliações e notas"
        FREQUENCIA = "frequencia", "Frequência"
        SOLICITACAO = "solicitacao", "Solicitação administrativa"
        OUTRA = "outra", "Outra"

    class Status(models.TextChoices):
        ABERTA = "aberta", "Aberta"
        ANDAMENTO = "andamento", "Em andamento"
        RESOLVIDA = "resolvida", "Resolvida"
        CANCELADA = "cancelada", "Cancelada"

    OPEN = (Status.ABERTA, Status.ANDAMENTO)

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="follow_ups", verbose_name="escola")
    title = models.CharField("o que precisa ser resolvido", max_length=200)
    description = models.TextField("detalhes", blank=True)
    category = models.CharField("tipo", max_length=15, choices=Category.choices, default=Category.OUTRA)
    student = models.ForeignKey("registry.Student", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="follow_ups", verbose_name="estudante")
    link = models.CharField("tela onde se resolve", max_length=300, blank=True)
    assignee = models.ForeignKey(User, on_delete=models.PROTECT, related_name="follow_ups_assigned",
                                 verbose_name="responsável")
    due_date = models.DateField("prazo", null=True, blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.ABERTA)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="follow_ups_created",
                                   verbose_name="aberta por")
    created_at = models.DateTimeField("aberta em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)
    closed_at = models.DateTimeField("encerrada em", null=True, blank=True)

    class Meta:
        ordering = ["due_date", "-created_at"]
        verbose_name = "pendência acompanhada"
        verbose_name_plural = "pendências acompanhadas"
        indexes = [models.Index(fields=["school", "assignee", "status"])]

    def __str__(self):
        return self.title

    @property
    def is_open(self):
        return self.status in self.OPEN

    @property
    def is_overdue(self):
        return self.is_open and self.due_date is not None and self.due_date < timezone.localdate()


class FollowUpEvent(models.Model):
    """Uma linha do histórico da pendência: quem mudou o quê, quando e por quê."""

    follow_up = models.ForeignKey(FollowUp, on_delete=models.CASCADE, related_name="events")
    by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, verbose_name="por")
    at = models.DateTimeField("em", auto_now_add=True)
    change = models.CharField("mudança", max_length=300)
    note = models.TextField("observação", blank=True)

    class Meta:
        ordering = ["at", "pk"]
        verbose_name = "histórico da pendência"
        verbose_name_plural = "históricos das pendências"


class RecoveryCode(models.Model):
    """Código de recuperação de senha, de uso único (Prompt 2 §5.25).

    A plataforma não envia e-mail (custo zero), então "esqueci a senha" dependia
    sempre da escola. Com estes códigos, a própria pessoa gera uma folha na
    conta, guarda em papel e, se esquecer a senha, define outra com o usuário e
    um código. Só o hash fica no banco (HMAC-SHA-256 com a SECRET_KEY; o código
    tem cerca de 49 bits e as tentativas são limitadas como as do login).
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "código de recuperação"
        verbose_name_plural = "códigos de recuperação"

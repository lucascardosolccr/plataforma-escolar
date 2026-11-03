from django.conf import settings
from django.db import models

from apps.core.uploads import (
    safe_attachment_path,
    safe_photo_path,
    validate_attachment,
    validate_photo,
)


class Student(models.Model):
    STATUS_CHOICES = [
        ("ativo", "Ativo"),
        ("transferido", "Transferido"),
        ("concluido", "Concluído"),
        ("inativo", "Inativo"),
    ]

    school = models.ForeignKey(
        "core.School",
        verbose_name="escola",
        on_delete=models.PROTECT,
        related_name="students",
    )
    first_name = models.CharField("nome", max_length=120)
    last_name = models.CharField("sobrenome", max_length=120, blank=True)
    birth_date = models.DateField("data de nascimento", null=True, blank=True)
    photo = models.ImageField(
        "fotografia",
        upload_to=safe_photo_path,
        validators=[validate_photo],
        null=True,
        blank=True,
    )
    status = models.CharField(
        "status", max_length=12, choices=STATUS_CHOICES, default="ativo"
    )
    # Código do aluno na escola (RA, matrícula da rede...). Opcional, mas único
    # na escola quando preenchido: é a chave que torna a importação por
    # planilha repetível sem duplicar e que associa fotos enviadas em lote.
    code = models.CharField(
        "código do aluno", max_length=30, blank=True,
        help_text="RA ou código usado pela escola. Único na escola.",
    )
    # Contato do responsável informado na matrícula, para quem ainda não tem
    # conta na plataforma (a secretaria precisa de alguém a quem ligar).
    guardian_contact_name = models.CharField("responsável (contato)", max_length=150, blank=True)
    guardian_contact_phone = models.CharField("telefone do responsável", max_length=30, blank=True)
    notes = models.TextField(
        "observações da secretaria",
        blank=True,
        help_text="Visível apenas a perfis administrativos.",
    )
    user = models.OneToOneField(
        "core.User",
        verbose_name="conta de acesso do estudante",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="student_record",
        help_text=(
            "Opcional. Criada pela secretaria a partir da ficha, quando a "
            "escola decide dar acesso ao próprio estudante."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "estudante"
        verbose_name_plural = "estudantes"
        ordering = ["first_name", "last_name"]
        indexes = [models.Index(fields=["school", "first_name", "last_name"])]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "code"], condition=~models.Q(code=""),
                name="uniq_student_code_per_school",
            )
        ]

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def full_name(self):
        return str(self)


class GuardianProfile(models.Model):
    RELATION_CHOICES = [
        ("mae", "Mãe"),
        ("pai", "Pai"),
        ("avo", "Avó/avô"),
        ("tutora", "Tutor(a) legal"),
        ("irmao", "Irmão/irmã"),
        ("outro", "Outro responsável"),
    ]
    COMMS_CHOICES = [
        ("email", "E-mail"),
        ("telefone", "Telefone"),
        ("nenhum", "Somente na plataforma"),
    ]

    user = models.OneToOneField(
        "core.User",
        on_delete=models.CASCADE,
        related_name="guardian_profile",
        verbose_name="usuário",
    )
    phone = models.CharField("telefone", max_length=30, blank=True)
    emergency_contact = models.CharField(
        "contato de emergência", max_length=200, blank=True
    )
    address = models.CharField("endereço", max_length=200, blank=True)
    relation = models.CharField(
        "relação com o estudante", max_length=10, choices=RELATION_CHOICES, blank=True
    )
    comm_preference = models.CharField(
        "preferência de comunicação",
        max_length=10,
        choices=COMMS_CHOICES,
        default="nenhum",
    )
    photo = models.ImageField(
        "fotografia",
        upload_to=safe_photo_path,
        validators=[validate_photo],
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "perfil do responsável"
        verbose_name_plural = "perfis dos responsáveis"

    def __str__(self):
        return f"Perfil de {self.user.get_full_name() or self.user.username}"


class GuardianLink(models.Model):
    STATUS_CHOICES = [
        ("pendente", "Pendente de validação"),
        ("aprovado", "Aprovado"),
        ("rejeitado", "Rejeitado"),
    ]

    school = models.ForeignKey(
        "core.School",
        verbose_name="escola",
        on_delete=models.PROTECT,
        related_name="guardian_links",
    )
    guardian = models.ForeignKey(
        "core.User",
        verbose_name="responsável",
        on_delete=models.CASCADE,
        related_name="guardian_links",
        limit_choices_to={"role": "responsavel"},
    )
    student = models.ForeignKey(
        Student,
        verbose_name="estudante",
        on_delete=models.CASCADE,
        related_name="guardian_links",
    )
    relation = models.CharField(
        "relação", max_length=10, choices=GuardianProfile.RELATION_CHOICES, blank=True
    )
    status = models.CharField(
        "situação", max_length=10, choices=STATUS_CHOICES, default="pendente"
    )
    requested_by = models.ForeignKey(
        "core.User",
        verbose_name="solicitado por",
        on_delete=models.SET_NULL,
        null=True,
        related_name="+",
    )
    validated_by = models.ForeignKey(
        "core.User",
        verbose_name="validado por",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    validated_at = models.DateTimeField("validado em", null=True, blank=True)
    rejection_reason = models.CharField(
        "motivo da rejeição", max_length=255, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "vínculo responsável-estudante"
        verbose_name_plural = "vínculos responsável-estudante"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["guardian", "student"], name="uniq_guardian_link"
            )
        ]

    def __str__(self):
        return f"{self.guardian} ↔ {self.student} ({self.get_status_display()})"


class Enrollment(models.Model):
    STATUS_CHOICES = [
        ("ativo", "Ativo"),
        ("transferido", "Transferido"),
        ("concluido", "Concluído"),
        ("desistente", "Desistente"),
    ]

    school = models.ForeignKey(
        "core.School",
        verbose_name="escola",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    student = models.ForeignKey(
        Student,
        verbose_name="estudante",
        on_delete=models.CASCADE,
        related_name="enrollments",
    )
    class_group = models.ForeignKey(
        "academics.ClassGroup",
        verbose_name="turma",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    school_year = models.ForeignKey(
        "academics.SchoolYear",
        verbose_name="ano letivo",
        on_delete=models.PROTECT,
        related_name="enrollments",
    )
    enrollment_number = models.CharField(
        "número de matrícula", max_length=20, blank=True
    )
    status = models.CharField(
        "status", max_length=12, choices=STATUS_CHOICES, default="ativo"
    )
    # Período em que o estudante esteve NESTA turma. Em branco significa
    # "desde o início" / "sem saída registrada" — assim as matrículas antigas,
    # criadas antes destes campos, continuam alcançando o que sempre alcançaram.
    started_on = models.DateField(
        "entrada na turma",
        null=True,
        blank=True,
        help_text="Deixe em branco se o estudante está na turma desde o início do ano.",
    )
    ended_on = models.DateField(
        "saída da turma",
        null=True,
        blank=True,
        help_text="Preenchida automaticamente ao transferir, concluir ou registrar desistência.",
    )
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "matrícula"
        verbose_name_plural = "matrículas"
        ordering = ["-school_year__name", "student__first_name"]
        constraints = [
            # Uma matrícula ATIVA por ano. A regra antiga (uma não-desistente
            # por ano) impedia a transferência de turma sem editar a matrícula
            # no lugar — o que apagava o histórico da turma anterior.
            models.UniqueConstraint(
                fields=["school", "student", "school_year"],
                condition=models.Q(status="ativo"),
                name="uniq_active_enrollment_per_year",
            )
        ]

    def covers(self, published_date, deadline=None):
        """A publicação (atividade, trabalho) feita para a turma alcança esta matrícula?

        Não alcança o que foi publicado depois que o estudante saiu, nem o que
        já tinha prazo encerrado quando ele entrou — não lhe foi atribuído, e
        exibir como "prazo encerrado" sugeriria uma pendência que não existe.
        O resto, inclusive o que ainda está vigente na chegada, alcança.
        """
        if self.ended_on and published_date > self.ended_on:
            return False
        if self.started_on and deadline and deadline < self.started_on:
            return False
        return True

    def __str__(self):
        return f"{self.student} — {self.class_group} ({self.school_year})"

class RegistrationSettings(models.Model):
    """O que a família pode fazer no cadastro, decidido pela escola.

    Uma linha por escola, criada na primeira leitura com o padrão mais
    conservador: cadastro pela família desligado.
    """

    MODE_OFF = "desligado"
    MODE_PHOTO = "foto"
    MODE_FULL = "completo"
    MODE_CHOICES = [
        (MODE_OFF, "Desligado: só a secretaria cadastra"),
        (MODE_PHOTO, "Só fotografia: a família envia ou troca a foto do filho"),
        (MODE_FULL, "Completo: a família faz o pré-cadastro do filho"),
    ]
    #: Campos opcionais do pré-cadastro que a escola pode pedir à família.
    #: Nome, nascimento e ano/série são sempre pedidos.
    OPTIONAL_FIELDS = [
        ("photo", "Fotografia"),
        ("desired_turn", "Turno desejado"),
        ("phone", "Telefone de contato"),
        ("address", "Endereço"),
        ("relation", "Parentesco"),
        ("school_notes", "Informações que a escola precisa saber"),
        ("documents", "Documentos (certidão, comprovante de residência)"),
    ]

    school = models.OneToOneField(
        "core.School", on_delete=models.CASCADE, related_name="registration_settings",
        verbose_name="escola",
    )
    family_mode = models.CharField(
        "cadastro pela família", max_length=10, choices=MODE_CHOICES, default=MODE_OFF
    )
    allow_correction_requests = models.BooleanField(
        "família pode pedir correção de dados", default=True,
        help_text="Abre uma solicitação à secretaria; os dados só mudam quando ela aceita.",
    )
    family_fields = models.CharField(
        "campos pedidos à família", max_length=200,
        default="photo,desired_turn,phone,relation,documents",
    )
    opens_on = models.DateField("abre em", null=True, blank=True)
    closes_on = models.DateField("fecha em", null=True, blank=True)
    school_year = models.ForeignKey(
        "academics.SchoolYear", on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="ano letivo dos novos cadastros",
        help_text="Em branco: o ano letivo atual.",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuração de cadastro"
        verbose_name_plural = "configurações de cadastro"

    def __str__(self):
        return f"Cadastro de {self.school}: {self.get_family_mode_display()}"

    @classmethod
    def for_school(cls, school):
        obj, _ = cls.objects.get_or_create(school=school)
        return obj

    @property
    def fields_list(self):
        valid = {k for k, _ in self.OPTIONAL_FIELDS}
        return [f for f in (self.family_fields or "").split(",") if f in valid]

    def is_open(self, today=None):
        """Período de cadastro aberto hoje? Sem datas = sempre aberto."""
        from django.utils import timezone

        today = today or timezone.localdate()
        if self.opens_on and today < self.opens_on:
            return False
        if self.closes_on and today > self.closes_on:
            return False
        return True

    @property
    def family_can_apply(self):
        return self.family_mode == self.MODE_FULL and self.is_open()

    def open_years(self):
        """Anos letivos abertos a novos pré-cadastros.

        São os marcados em ``SchoolYear.accepts_applications``. Escola que
        ainda não marcou nenhum segue a regra anterior: o ano escolhido aqui
        ou, em branco, o ano atual.
        """
        from apps.academics.models import SchoolYear

        years = list(SchoolYear.objects.filter(school=self.school, accepts_applications=True).order_by("name"))
        if years:
            return years
        legacy = self.school_year or SchoolYear.objects.filter(school=self.school, is_current=True).first()
        return [legacy] if legacy else []

    @property
    def family_can_send_photo(self):
        return self.family_mode in (self.MODE_PHOTO, self.MODE_FULL)


class StudentApplication(models.Model):
    """Pré-cadastro de estudante feito pela família.

    Nunca vira matrícula sozinho: a secretaria aprova (criando a ficha e o
    vínculo da família) e só então, se escolher uma turma, abre a matrícula.
    """

    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        SUBMITTED = "enviado", "Enviado à secretaria"
        CORRECTION = "correcao", "Correção solicitada"
        APPROVED = "aprovado", "Aprovado"
        REJECTED = "recusado", "Recusado"
        CANCELED = "cancelado", "Cancelado pela família"

    EDITABLE = ("rascunho", "correcao")

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, verbose_name="escola")
    guardian = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_applications",
        verbose_name="responsável",
    )
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DRAFT)
    step = models.PositiveSmallIntegerField("etapa", default=1)
    first_name = models.CharField("nome do estudante", max_length=120, blank=True)
    last_name = models.CharField("sobrenome", max_length=120, blank=True)
    birth_date = models.DateField("data de nascimento", null=True, blank=True)
    desired_grade = models.CharField("ano/série", max_length=40, blank=True)
    desired_turn = models.CharField(
        "turno desejado", max_length=10, blank=True,
        choices=[("manha", "Manhã"), ("tarde", "Tarde"), ("integral", "Integral"), ("noite", "Noite")],
    )
    photo = models.ImageField(
        "fotografia", upload_to=safe_photo_path, validators=[validate_photo], null=True, blank=True
    )
    phone = models.CharField("telefone de contato", max_length=30, blank=True)
    address = models.CharField("endereço", max_length=200, blank=True)
    relation = models.CharField("parentesco", max_length=10, blank=True,
                                choices=GuardianProfile.RELATION_CHOICES)
    school_notes = models.TextField(
        "informações que a escola precisa saber", blank=True,
        help_text="Só o necessário: por exemplo, quem pode buscar o estudante.",
    )
    school_year = models.ForeignKey(
        "academics.SchoolYear", on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="ano letivo pretendido",
    )
    review_note = models.TextField("mensagem da secretaria", blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True, related_name="applications",
        verbose_name="ficha criada",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pré-cadastro"
        verbose_name_plural = "pré-cadastros"
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Pré-cadastro de {self.full_name or '(sem nome)'}"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def editable(self):
        return self.status in self.EDITABLE


class ApplicationDocument(models.Model):
    KIND_CHOICES = [
        ("certidao", "Certidão de nascimento ou RG"),
        ("residencia", "Comprovante de residência"),
        ("historico", "Histórico ou declaração escolar"),
        ("outro", "Outro documento"),
    ]
    application = models.ForeignKey(
        StudentApplication, on_delete=models.CASCADE, related_name="documents"
    )
    kind = models.CharField("tipo", max_length=12, choices=KIND_CHOICES)
    file = models.FileField("arquivo", upload_to=safe_attachment_path, validators=[validate_attachment])
    original_name = models.CharField(max_length=200)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "documento do pré-cadastro"
        verbose_name_plural = "documentos do pré-cadastro"
        ordering = ["uploaded_at"]

    def __str__(self):
        return f"{self.get_kind_display()} — {self.original_name}"


class ImportBatch(models.Model):
    """Uma importação de estudantes por planilha, do envio ao relatório.

    As linhas lidas e validadas ficam em ``rows`` (JSON) entre a
    pré-visualização e a confirmação; nada é gravado nos cadastros antes da
    confirmação explícita.
    """

    class Status(models.TextChoices):
        PREVIEW = "previa", "Aguardando confirmação"
        DONE = "concluida", "Concluída"
        CANCELED = "cancelada", "Cancelada"

    class Mode(models.TextChoices):
        NEW_ONLY = "novos", "Cadastrar só alunos novos (ignorar os já cadastrados)"
        UPDATE = "atualizar", "Cadastrar novos e atualizar os já cadastrados"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, verbose_name="escola")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+",
        verbose_name="responsável",
    )
    filename = models.CharField("arquivo", max_length=200)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.PREVIEW)
    mode = models.CharField("tratamento", max_length=10, choices=Mode.choices, default=Mode.NEW_ONLY)
    rows = models.TextField("linhas (JSON)", blank=True)
    total = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField("cadastrados", default=0)
    updated_count = models.PositiveIntegerField("atualizados", default=0)
    skipped_count = models.PositiveIntegerField("ignorados", default=0)
    error_count = models.PositiveIntegerField("com erro", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "importação de estudantes"
        verbose_name_plural = "importações de estudantes"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Importação {self.filename} ({self.get_status_display()})"


class PhotoException(models.Model):
    """Dispensa justificada de fotografia (estudante ou conta), registrada
    pela administração. A foto é só identificação visual: ninguém perde
    acesso por não ter foto; a dispensa tira a pendência das listas."""

    school = models.ForeignKey("core.School", on_delete=models.CASCADE)
    student = models.ForeignKey(Student, on_delete=models.CASCADE, null=True, blank=True,
                                related_name="photo_exceptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                             related_name="photo_exceptions")
    reason = models.CharField("justificativa", max_length=300)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "dispensa de fotografia"
        verbose_name_plural = "dispensas de fotografia"


class DocumentSettings(models.Model):
    """Dados institucionais das declarações (preenchidos uma vez pela escola).

    A plataforma não inventa endereço, INEP ou quem assina: enquanto os campos
    estiverem vazios, a declaração mostra a lacuna para ser preenchida à mão.
    """

    school = models.OneToOneField("core.School", on_delete=models.CASCADE, related_name="document_settings")
    header = models.TextField("cabeçalho", blank=True,
                              help_text="Uma informação por linha: mantenedora, endereço, telefone, código INEP, CNPJ.")
    city = models.CharField("cidade (para a data)", max_length=80, blank=True)
    signer_name = models.CharField("quem assina", max_length=120, blank=True)
    signer_role = models.CharField("cargo de quem assina", max_length=120, blank=True, default="Secretaria escolar")
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def for_school(cls, school):
        return cls.objects.filter(school=school).first() or cls(school=school)


class IssuedDocument(models.Model):
    """Declaração emitida: número, código de verificação e o texto exato que saiu.

    Nada é apagado nem reescrito: reimprimir mostra o mesmo texto, e uma nova
    declaração é um novo registro com outro número.
    """

    class Kind(models.TextChoices):
        ENROLLMENT = "matricula", "Declaração de matrícula"
        ATTENDANCE = "frequencia", "Declaração de frequência"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="issued_documents")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="issued_documents")
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices)
    year = models.PositiveSmallIntegerField("ano da numeração")
    sequence = models.PositiveIntegerField("número")
    code = models.CharField("código de verificação", max_length=9, unique=True)
    purpose = models.CharField("finalidade", max_length=120, blank=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    body = models.TextField("texto emitido")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                  related_name="documents_issued")
    issued_at = models.DateTimeField(auto_now_add=True)
    request = models.ForeignKey("communication.ServiceRequest", on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="documents")

    class Meta:
        ordering = ["-issued_at", "-pk"]
        constraints = [models.UniqueConstraint(fields=["school", "year", "sequence"], name="uniq_document_number")]
        verbose_name = "declaração emitida"
        verbose_name_plural = "declarações emitidas"

    @property
    def number(self):
        return f"{self.sequence:04d}/{self.year}"

    def __str__(self):
        return f"{self.get_kind_display()} nº {self.number}"

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject
from apps.core.models import School, User
from apps.core.uploads import safe_attachment_path, validate_attachment
from apps.registry.models import Student


class FamilyVisibility:
    """Regra única do que chega à família (responsável e conta do estudante).

    Vale para atividades e trabalhos em grupo. Chega o que foi publicado e
    cuja data já veio; e, depois de cancelado, só o que a família já via no
    momento do cancelamento. Rascunho cancelado nunca chega — antes, cada tela
    filtrava ``exclude(status=DRAFT)`` por conta própria e o rascunho
    cancelado aparecia para a família.
    """

    @classmethod
    def family_visible_q(cls, prefix="", today=None):
        """Filtro de banco equivalente a ``is_visible_to_family``.

        ``prefix`` permite filtrar a partir de outro modelo, como
        ``group__group_work__`` nos integrantes de um grupo.
        """
        today = today or timezone.localdate()
        published = cls.Status.PUBLISHED
        canceled = cls.Status.CANCELED
        return Q(**{f"{prefix}published_date__lte": today}) & (
            Q(**{f"{prefix}status": published})
            | Q(**{f"{prefix}status": canceled, f"{prefix}visible_before_cancel": True})
        )

    @property
    def is_visible_to_family(self):
        if self.published_date > timezone.localdate():
            return False
        if self.status == self.Status.PUBLISHED:
            return True
        return self.status == self.Status.CANCELED and self.visible_before_cancel

    def cancel(self, reason):
        """Cancela guardando se a família já via o item (não salva)."""
        self.visible_before_cancel = self.is_visible_to_family
        self.status = self.Status.CANCELED
        self.cancel_reason = reason


class AcademicRule(models.Model):
    """Regras acadêmicas configuráveis por disciplina. O sistema nunca presume
    que todas as disciplinas usam a mesma fórmula de média."""

    class Formula(models.TextChoices):
        ARITHMETIC = "aritmetica", "Média aritmética"
        WEIGHTED = "ponderada", "Média ponderada"
        BEST = "melhor_nota", "Melhor nota"
        SUM = "soma", "Soma das notas"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, verbose_name="disciplina"
    )
    formula = models.CharField(
        "fórmula de média",
        max_length=15,
        choices=Formula.choices,
        default=Formula.ARITHMETIC,
    )
    passing_grade = models.DecimalField(
        "média de aprovação", max_digits=4, decimal_places=2, default=6.0
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["school", "subject"], name="uniq_academic_rule_per_subject"
            )
        ]
        verbose_name = "regra acadêmica"
        verbose_name_plural = "regras acadêmicas"

    def __str__(self):
        return f"{self.subject} — {self.get_formula_display()} (>= {self.passing_grade})"


class Evaluation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        PUBLISHED = "publicada", "Publicada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, verbose_name="disciplina")
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.PROTECT, verbose_name="turma"
    )
    class Kind(models.TextChoices):
        UNSPECIFIED = "", "Não informado"
        DIAGNOSTIC = "diagnostica", "Diagnóstica"
        FORMATIVE = "formativa", "Formativa"
        SUMMATIVE = "somativa", "Somativa"
        RECOVERY = "recuperacao", "Recuperação"

    title = models.CharField("título", max_length=200)
    description = models.TextField("descrição", blank=True)
    # Opcional: as avaliações antigas ficam "não informado" em vez de ganhar
    # um tipo inventado. Permite comparar instrumentos e ver a recuperação.
    kind = models.CharField(
        "tipo de avaliação", max_length=12, choices=Kind.choices, blank=True, default=""
    )
    weight = models.DecimalField("peso", max_digits=4, decimal_places=2, default=1.0)
    date = models.DateField("data", default=timezone.localdate)
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices, default=Status.DRAFT
    )
    # "Rascunho" quer dizer notas ainda não publicadas; a data da prova pode
    # (e deve) ser conhecida antes. Com a data divulgada, a prova entra na
    # agenda do estudante e da família e gera lembretes.
    announced = models.BooleanField(
        "divulgar a data para a turma", default=False,
        help_text="Estudantes e responsáveis veem a data na agenda e recebem lembretes.")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="evaluations_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["school", "class_group", "subject"])]
        ordering = ["-date"]
        verbose_name = "avaliação"
        verbose_name_plural = "avaliações"

    def __str__(self):
        return f"{self.title} — {self.class_group}"

    @property
    def family_visible(self):
        return self.status == self.Status.PUBLISHED or self.announced


class Grade(models.Model):
    """Nota individual. Nunca é apagada nem alterada sem histórico: toda
    criação/alteração gera registro de auditoria (append-only)."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    evaluation = models.ForeignKey(
        Evaluation, on_delete=models.CASCADE, related_name="grades", verbose_name="avaliação"
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="grades", verbose_name="estudante"
    )
    value = models.DecimalField(
        "nota", max_digits=4, decimal_places=2, null=True, blank=True
    )
    observation = models.TextField("observação", blank=True)
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="grades_updated"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["evaluation", "student"], name="uniq_grade_per_evaluation"
            )
        ]
        indexes = [models.Index(fields=["school", "student"])]
        verbose_name = "nota"
        verbose_name_plural = "notas"

    def __str__(self):
        return f"{self.student} — {self.evaluation}: {self.value}"


class Activity(FamilyVisibility, models.Model):
    """Atividade de casa / tarefa lançada para uma turma e disciplina.

    A atividade pertence à TURMA, não a cada estudante: existe um único
    registro e o alcance é derivado das matrículas da turma. Isso faz com que
    quem entra na turma depois passe a ver as atividades vigentes e com que
    editar a atividade atualize todos de uma vez, sem cópias divergentes.
    O acompanhamento individual fica em ``Submission``.
    """

    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        PUBLISHED = "publicada", "Publicada"
        CANCELED = "cancelada", "Cancelada"

    class WorkMode(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        GROUP = "grupo", "Em grupo"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.CASCADE, verbose_name="turma"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    title = models.CharField("título", max_length=200)
    # Só informa como a atividade é feita. A composição de grupos com entrega
    # por grupo continua no módulo "Trabalhos em grupo".
    work_mode = models.CharField("realização", max_length=10, choices=WorkMode.choices,
                                 default=WorkMode.INDIVIDUAL)
    description = models.TextField("instruções", blank=True)
    content = models.CharField("conteúdo trabalhado", max_length=200, blank=True)
    objective = models.CharField("objetivo pedagógico", max_length=300, blank=True)
    # Só para a equipe (professor, coordenação, impressão): nunca aparece à família.
    internal_notes = models.TextField("observações internas", blank=True)
    criteria = models.TextField("critérios de avaliação", blank=True)
    materials = models.TextField(
        "materiais necessários e orientações complementares", blank=True
    )
    deadline = models.DateField("data de entrega", null=True, blank=True)
    published_date = models.DateField("data de publicação", default=timezone.localdate)
    class_date = models.DateField(
        "data de aplicação",
        null=True,
        blank=True,
        help_text="Dia em que a atividade será aplicada ou trabalhada em aula.",
    )
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices, default=Status.PUBLISHED
    )
    cancel_reason = models.CharField(
        "motivo do cancelamento", max_length=255, blank=True
    )
    visible_before_cancel = models.BooleanField(
        "família já via quando foi cancelada", default=False
    )
    # Quando a família foi avisada. Fica vazio enquanto a data de publicação
    # não chega: avisar antes mandaria um link que ainda responde "acesso
    # negado". Também impede aviso duplicado (ver communication.services).
    notified_at = models.DateTimeField("família avisada em", null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="activities_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["-published_date", "-created_at"]
        indexes = [
            models.Index(fields=["school", "class_group", "status"]),
            models.Index(fields=["class_group", "status", "published_date"]),
        ]
        verbose_name = "atividade"
        verbose_name_plural = "atividades"

    def __str__(self):
        return f"{self.title} — {self.class_group}"

    def family_situation(self, today=None):
        """Rótulo de acompanhamento mostrado à família.

        Deriva do prazo; nunca de visualização. Ver uma atividade não a conclui.
        """
        today = today or timezone.localdate()
        if self.status == self.Status.CANCELED:
            return "cancelada", "Cancelada"
        if self.status == self.Status.DRAFT:
            return "rascunho", "Rascunho"
        if self.published_date > today:
            return "agendada", "Agendada"
        if not self.deadline:
            return "publicada", "Publicada"
        if self.deadline < today:
            return "encerrada", "Prazo encerrado"
        if (self.deadline - today).days <= 2:
            return "a_vencer", "A vencer"
        return "pendente", "Pendente"


class ActivityAttachment(models.Model):
    """Arquivo de apoio da atividade.

    O arquivo nunca é exposto por URL pública de mídia: o download passa por
    uma view que confere o vínculo de quem pede (ver pedagogy.views).
    """

    activity = models.ForeignKey(
        Activity,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="atividade",
    )
    file = models.FileField(
        "arquivo",
        upload_to=safe_attachment_path,
        validators=[validate_attachment],
    )
    original_name = models.CharField("nome do arquivo", max_length=255)
    size = models.PositiveIntegerField("tamanho em bytes", default=0)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, verbose_name="enviado por"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        verbose_name = "anexo da atividade"
        verbose_name_plural = "anexos da atividade"

    def __str__(self):
        return f"{self.original_name} — {self.activity.title}"


class Submission(models.Model):
    """Entrega / não entrega de atividade por estudante."""

    class Status(models.TextChoices):
        DELIVERED = "entregue", "Entregue"
        # Entregue depois do prazo. Antes só havia entregue/não entregue e o
        # painel não conseguia separar "no prazo" de "com atraso".
        LATE = "atrasado", "Entregue com atraso"
        NOT_DELIVERED = "nao_entregue", "Não entregue"

    # Situações que contam como entrega feita (no prazo ou não).
    DELIVERED_STATUSES = (Status.DELIVERED, Status.LATE)

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    activity = models.ForeignKey(
        Activity, on_delete=models.CASCADE, related_name="submissions", verbose_name="atividade"
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="submissions", verbose_name="estudante"
    )
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices, default=Status.DELIVERED
    )
    grade = models.DecimalField(
        "nota da atividade",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Opcional. Não entra no cálculo da média da disciplina, que usa "
            "apenas as avaliações."
        ),
    )
    comment = models.TextField("observação", blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["activity", "student"], name="uniq_submission_per_activity"
            )
        ]
        verbose_name = "entrega"
        verbose_name_plural = "entregas"

    def __str__(self):
        return f"{self.student} — {self.activity}: {self.get_status_display()}"


class GroupWork(FamilyVisibility, models.Model):
    """Trabalho em grupo: UMA entidade compartilhada pela turma.

    Quatro alunos num grupo não geram quatro trabalhos. O trabalho pertence à
    turma, os grupos pertencem ao trabalho e os integrantes pertencem ao
    grupo. Assim editar o enunciado atualiza todos de uma vez e a composição
    do grupo tem um só lugar de verdade.
    """

    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        PUBLISHED = "publicada", "Publicada"
        CANCELED = "cancelada", "Cancelada"

    class DeliveryMode(models.TextChoices):
        GROUP = "grupo", "Uma entrega por grupo"
        INDIVIDUAL = "individual", "Uma entrega por integrante"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.CASCADE, verbose_name="turma"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, verbose_name="disciplina"
    )
    title = models.CharField("título", max_length=200)
    description = models.TextField("o que deve ser feito")
    objectives = models.TextField("objetivos pedagógicos", blank=True)
    guidelines = models.TextField("orientações e critérios de avaliação", blank=True)
    materials = models.TextField("materiais necessários", blank=True)
    presentation = models.CharField(
        "forma de apresentação ou entrega",
        max_length=200,
        blank=True,
        help_text="Ex.: cartaz, seminário de 10 minutos, arquivo impresso.",
    )
    notes = models.TextField("observações complementares", blank=True)
    published_date = models.DateField("data de publicação", default=timezone.localdate)
    deadline = models.DateField("prazo de entrega", null=True, blank=True)
    delivery_mode = models.CharField(
        "forma de registro da entrega",
        max_length=12,
        choices=DeliveryMode.choices,
        default=DeliveryMode.GROUP,
        help_text=(
            "Define se a entrega é registrada uma vez para o grupo ou "
            "separadamente para cada integrante. Nunca se marca o grupo "
            "inteiro a partir de um só integrante."
        ),
    )
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices, default=Status.PUBLISHED
    )
    cancel_reason = models.CharField(
        "motivo do cancelamento", max_length=255, blank=True
    )
    visible_before_cancel = models.BooleanField(
        "família já via quando foi cancelado", default=False
    )
    notified_at = models.DateTimeField("família avisada em", null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="group_works_created"
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizado em", auto_now=True)

    class Meta:
        ordering = ["-published_date", "-created_at"]
        indexes = [
            models.Index(fields=["school", "class_group", "status"]),
            models.Index(fields=["class_group", "status", "published_date"]),
        ]
        verbose_name = "trabalho em grupo"
        verbose_name_plural = "trabalhos em grupo"

    def __str__(self):
        return f"{self.title} — {self.class_group}"

    def situation(self, today=None):
        """Rótulo de acompanhamento. Deriva do prazo, nunca de visualização."""
        today = today or timezone.localdate()
        if self.status == self.Status.CANCELED:
            return "cancelada", "Cancelado"
        if self.status == self.Status.DRAFT:
            return "rascunho", "Rascunho"
        if self.published_date > today:
            return "agendada", "Agendado"
        if not self.deadline:
            return "publicada", "Atribuído"
        if self.deadline < today:
            return "encerrada", "Prazo encerrado"
        if (self.deadline - today).days <= 2:
            return "a_vencer", "A vencer"
        return "pendente", "Em andamento"


class WorkGroup(models.Model):
    """Um grupo dentro de um trabalho."""

    group_work = models.ForeignKey(
        GroupWork,
        on_delete=models.CASCADE,
        related_name="groups",
        verbose_name="trabalho",
    )
    name = models.CharField("nome do grupo", max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["group_work", "name"], name="uniq_group_name_per_work"
            )
        ]
        verbose_name = "grupo do trabalho"
        verbose_name_plural = "grupos do trabalho"

    def __str__(self):
        return f"{self.name} — {self.group_work.title}"

    def active_members(self):
        return self.members.filter(removed_at__isnull=True).select_related("student")


class WorkGroupMember(models.Model):
    """Participação de um estudante num grupo.

    Sair do grupo marca ``removed_at`` em vez de apagar a linha: a §7.4 do
    prompt exige preservar o histórico de participação, e uma composição
    apagada não se reconstrói depois.
    """

    group = models.ForeignKey(
        WorkGroup,
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name="grupo",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="work_group_memberships",
        verbose_name="estudante",
    )
    added_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    added_at = models.DateTimeField(auto_now_add=True)
    removed_at = models.DateTimeField("saiu em", null=True, blank=True)

    class Meta:
        ordering = ["student__first_name", "student__last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "student"], name="uniq_member_per_group"
            )
        ]
        indexes = [models.Index(fields=["student", "removed_at"])]
        verbose_name = "integrante do grupo"
        verbose_name_plural = "integrantes do grupo"

    def __str__(self):
        saiu = " (saiu)" if self.removed_at else ""
        return f"{self.student} em {self.group.name}{saiu}"


class GroupWorkAttachment(models.Model):
    """Arquivo de apoio do trabalho, servido só por view que confere vínculo."""

    group_work = models.ForeignKey(
        GroupWork,
        on_delete=models.CASCADE,
        related_name="attachments",
        verbose_name="trabalho",
    )
    file = models.FileField(
        "arquivo", upload_to=safe_attachment_path, validators=[validate_attachment]
    )
    original_name = models.CharField("nome do arquivo", max_length=255)
    size = models.PositiveIntegerField("tamanho em bytes", default=0)
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, verbose_name="enviado por"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at"]
        verbose_name = "anexo do trabalho"
        verbose_name_plural = "anexos do trabalho"

    def __str__(self):
        return f"{self.original_name} — {self.group_work.title}"


class GroupWorkDelivery(models.Model):
    """Entrega registrada pelo PROFESSOR.

    Quando ``delivery_mode`` é "grupo", existe uma linha por grupo e
    ``student`` fica nulo. Quando é "individual", existe uma linha por
    integrante. As duas restrições abaixo impedem a mistura — sem elas, um
    registro de grupo e outro individual poderiam coexistir e ninguém saberia
    qual vale.
    """

    class Status(models.TextChoices):
        DELIVERED = "entregue", "Entregue"
        LATE = "atrasado", "Entregue com atraso"
        NOT_DELIVERED = "nao_entregue", "Não entregue"

    group_work = models.ForeignKey(
        GroupWork,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="trabalho",
    )
    group = models.ForeignKey(
        WorkGroup,
        on_delete=models.CASCADE,
        related_name="deliveries",
        verbose_name="grupo",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="group_work_deliveries",
        verbose_name="integrante",
    )
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices, default=Status.DELIVERED
    )
    grade = models.DecimalField(
        "nota do trabalho",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Opcional. Não entra no cálculo da média da disciplina, que usa "
            "apenas as avaliações."
        ),
    )
    comment = models.TextField("observação do professor", blank=True)
    delivered_at = models.DateField("data da entrega", null=True, blank=True)
    registered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["group"],
                condition=models.Q(student__isnull=True),
                name="uniq_group_delivery",
            ),
            models.UniqueConstraint(
                fields=["group", "student"],
                condition=models.Q(student__isnull=False),
                name="uniq_member_delivery",
            ),
        ]
        verbose_name = "entrega do trabalho"
        verbose_name_plural = "entregas do trabalho"

    def __str__(self):
        quem = self.student or self.group
        return f"{quem} — {self.get_status_display()}"


class AttendanceRecord(models.Model):
    """Frequência oficial: presente / atraso / falta, por estudante, turma e data."""

    class Status(models.TextChoices):
        PRESENT = "presente", "Presente"
        LATE = "atraso", "Atraso"
        ABSENT = "falta", "Falta"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.CASCADE, verbose_name="turma"
    )
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="attendance", verbose_name="estudante"
    )
    date = models.DateField("data", default=timezone.localdate)
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices, default=Status.PRESENT
    )
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="attendance_recorded"
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["class_group", "student", "date"],
                name="uniq_attendance_per_student_date",
            )
        ]
        indexes = [models.Index(fields=["class_group", "date"])]
        verbose_name = "registro de frequência"
        verbose_name_plural = "registros de frequência"

    def __str__(self):
        return f"{self.student} — {self.date}: {self.get_status_display()}"


class AbsenceJustification(models.Model):
    """Justificativa de falta enviada pela família. NUNCA altera a frequência
    oficial — a secretaria analisa e decide."

    """

    class Status(models.TextChoices):
        RECEIVED = "recebida", "Recebida"
        UNDER_REVIEW = "em_analise", "Em análise"
        APPROVED = "aprovada", "Aprovada"
        REFUSED = "recusada", "Recusada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="justifications", verbose_name="estudante"
    )
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="turma"
    )
    start_date = models.DateField("data inicial")
    end_date = models.DateField("data final")
    reason = models.TextField("motivo")
    submitted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, verbose_name="enviado por"
    )
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices, default=Status.RECEIVED
    )
    note = models.TextField("parecer da secretaria", blank=True)
    validated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="justifications_validated"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "justificativa de falta"
        verbose_name_plural = "justificativas de falta"

    def __str__(self):
        return f"Justificativa de {self.student} ({self.start_date}..{self.end_date})"


class Occurrence(models.Model):
    """Ocorrência escolar com histórico de atualização (via auditoria)."""

    class Status(models.TextChoices):
        OPEN = "aberta", "Aberta"
        FOLLOW_UP = "em_acompanhamento", "Em acompanhamento"
        REFERRED = "encaminhada", "Encaminhada"
        CLOSED = "concluida", "Concluída"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="occurrences", verbose_name="estudante"
    )
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="occurrences_recorded"
    )
    date = models.DateField("data", default=timezone.localdate)
    description = models.TextField("descrição objetiva")
    providencias = models.TextField("providências adotadas", blank=True)
    encaminhamento = models.CharField(
        "encaminhamento", max_length=200, blank=True, help_text="Orientação educacional, família, direção…"
    )
    status = models.CharField(
        "situação", max_length=20, choices=Status.choices, default=Status.OPEN
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["student", "date"])]
        ordering = ["-date", "-created_at"]
        verbose_name = "ocorrência"
        verbose_name_plural = "ocorrências"

    def __str__(self):
        return f"Ocorrência de {self.student} em {self.date}"


class PedagogicalObservation(models.Model):
    """Observação pedagógica: dificuldades, habilidades e estratégias registradas
    pelo professor/coordenação sobre um estudante."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="observations", verbose_name="estudante"
    )
    teacher = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="observations_recorded",
        verbose_name="quem registrou",
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="disciplina"
    )
    content = models.CharField("conteúdo/tema", max_length=200)
    dificuldades = models.TextField("dificuldades observadas", blank=True)
    habilidades = models.TextField("habilidades consolidadas", blank=True)
    estrategias = models.TextField("estratégias/reforço recomendado", blank=True)
    # Registro interno da equipe x informação compartilhada com a família.
    # Padrão "compartilhar" preserva o comportamento anterior (a família já via).
    shared_with_family = models.BooleanField(
        "compartilhar com a família", default=True,
        help_text="Desmarcado: registro interno da equipe pedagógica. A família não vê nem é avisada.",
    )
    observed_at = models.DateField("data", default=timezone.localdate)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-observed_at", "-created_at"]
        verbose_name = "observação pedagógica"
        verbose_name_plural = "observações pedagógicas"

    def __str__(self):
        return f"Observação de {self.student} — {self.content}"


class InterventionPlan(models.Model):
    """Plano de acompanhamento individual do estudante."""

    class Status(models.TextChoices):
        ACTIVE = "ativo", "Ativo"
        DONE = "concluido", "Concluído"
        CANCELED = "cancelado", "Cancelado"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="plans", verbose_name="estudante"
    )
    title = models.CharField("título", max_length=200)
    description = models.TextField("objetivos e estratégias")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="plans_created"
    )
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices, default=Status.ACTIVE
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "plano de acompanhamento"
        verbose_name_plural = "planos de acompanhamento"

    def __str__(self):
        return f"{self.title} — {self.student} ({self.get_status_display()})"


class PlanNote(models.Model):
    """Evolução registrada por ponto no plano de acompanhamento."""

    plan = models.ForeignKey(
        InterventionPlan, on_delete=models.CASCADE, related_name="notes", verbose_name="plano"
    )
    note = models.TextField("registro de evolução")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "registro de evolução"
        verbose_name_plural = "registros de evolução"

    def __str__(self):
        return f"Evolução de {self.plan} — {self.created_at.date()}"


class SchoolConfig(models.Model):
    """Configurações da escola aplicáveis ao pedagógico (limites, regras)."""

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="config")
    max_absences_percent = models.DecimalField(
        "limite de faltas (%)", max_digits=5, decimal_places=1, default=25.0
    )

    class Meta:
        verbose_name = "configuração da escola"
        verbose_name_plural = "configurações da escola"

    def __str__(self):
        return f"Config de {self.school} — faltas <= {self.max_absences_percent}%"


class LessonPlan(models.Model):
    """Planejamento docente: o que o professor vai trabalhar com a turma num período.

    Documento interno da equipe: a família e o estudante nunca veem. O
    professor escreve e envia; a coordenação que acompanha a turma (e a
    direção) devolve com orientação ou valida. Cada devolutiva fica em
    ``LessonPlanReview``, então o histórico de idas e vindas não se perde.
    """

    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        SUBMITTED = "enviado", "Enviado para a coordenação"
        ADJUST = "ajustes", "Devolvido para ajustes"
        APPROVED = "validado", "Validado"

    #: Situações em que o professor ainda pode editar.
    EDITABLE = (Status.DRAFT, Status.ADJUST)

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="lesson_plans",
                                verbose_name="professor")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, verbose_name="turma")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    starts_on = models.DateField("início do período")
    ends_on = models.DateField("fim do período")
    title = models.CharField("tema ou unidade", max_length=200)
    content = models.TextField("conteúdos")
    objectives = models.TextField("objetivos de aprendizagem")
    methodology = models.TextField("estratégias e metodologia", blank=True)
    resources = models.TextField("recursos e materiais", blank=True)
    assessment = models.TextField("avaliação prevista", blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DRAFT)
    submitted_at = models.DateTimeField("enviado em", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_on", "-created_at"]
        indexes = [models.Index(fields=["school", "status"]), models.Index(fields=["class_group", "starts_on"])]
        verbose_name = "planejamento"
        verbose_name_plural = "planejamentos"

    def __str__(self):
        return f"{self.title} — {self.class_group} / {self.subject}"

    @property
    def is_editable(self):
        return self.status in self.EDITABLE


class LessonPlanReview(models.Model):
    """Devolutiva da coordenação (ou da direção) sobre um planejamento."""

    plan = models.ForeignKey(LessonPlan, on_delete=models.CASCADE, related_name="reviews",
                             verbose_name="planejamento")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    decision = models.CharField("decisão", max_length=10, choices=LessonPlan.Status.choices)
    comment = models.TextField("orientação", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "devolutiva de planejamento"
        verbose_name_plural = "devolutivas de planejamento"

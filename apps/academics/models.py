from django.db import models
from django.utils import timezone


class SchoolYear(models.Model):
    school = models.ForeignKey(
        "core.School",
        verbose_name="escola",
        on_delete=models.CASCADE,
        related_name="school_years",
    )
    name = models.CharField("nome", max_length=30, help_text="Ex.: 2026")
    start_date = models.DateField("início", null=True, blank=True)
    end_date = models.DateField("fim", null=True, blank=True)
    is_current = models.BooleanField("ano letivo atual", default=False)
    accepts_applications = models.BooleanField(
        "aceita novos pré-cadastros", default=False,
        help_text="Marcado nas Configurações de cadastro: as famílias podem pedir vaga para este ano.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ano letivo"
        verbose_name_plural = "anos letivos"
        ordering = ["-name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "name"], name="uniq_school_year_per_school"
            )
        ]

    def __str__(self):
        return self.name


class ClassGroup(models.Model):
    TURNO_CHOICES = [
        ("manha", "Manhã"),
        ("tarde", "Tarde"),
        ("integral", "Integral"),
        ("noite", "Noite"),
    ]

    school = models.ForeignKey(
        "core.School",
        verbose_name="escola",
        on_delete=models.CASCADE,
        related_name="class_groups",
    )
    school_year = models.ForeignKey(
        SchoolYear,
        verbose_name="ano letivo",
        on_delete=models.CASCADE,
        related_name="class_groups",
    )
    name = models.CharField("nome da turma", max_length=60, help_text="Ex.: 1º Ano A")
    grade = models.CharField("série", max_length=40, blank=True)
    turn = models.CharField("turno", max_length=10, choices=TURNO_CHOICES, default="manha")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "turma"
        verbose_name_plural = "turmas"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "school_year", "name"],
                name="uniq_classgroup_per_year",
            )
        ]

    def __str__(self):
        return f"{self.name} · {self.school_year}"


class Subject(models.Model):
    school = models.ForeignKey(
        "core.School",
        verbose_name="escola",
        on_delete=models.CASCADE,
        related_name="subjects",
    )
    name = models.CharField("nome", max_length=80)
    code = models.SlugField("código", max_length=40, blank=True)
    is_active = models.BooleanField(
        "ativa", default=True,
        help_text="Desativada: some das listas de escolha, mas o histórico (notas, atividades) continua.",
    )
    workload_hours = models.PositiveSmallIntegerField("carga horária anual (h)", null=True, blank=True)
    grade_level = models.CharField("ano/série", max_length=60, blank=True,
                                   help_text="Ex.: 1º ao 5º ano. Em branco: todas.")
    # Vigência: fora dela a disciplina sai das listas de escolha (como a
    # desativada), mas o histórico continua. Em branco: sem limite.
    valid_from = models.DateField("vigente a partir de", null=True, blank=True)
    valid_until = models.DateField("vigente até", null=True, blank=True,
                                   help_text="Em branco: sem data para encerrar.")

    class Meta:
        verbose_name = "disciplina"
        verbose_name_plural = "disciplinas"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="uniq_subject_per_school")
        ]

    def __str__(self):
        return self.name

    @staticmethod
    def available_q(today=None):
        """Filtro das disciplinas que podem ser escolhidas hoje: ativas e na vigência."""
        today = today or timezone.localdate()
        return (models.Q(is_active=True)
                & (models.Q(valid_from__isnull=True) | models.Q(valid_from__lte=today))
                & (models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=today)))

    @classmethod
    def choices_for(cls, school, keep=None, today=None):
        """Disciplinas da escola disponíveis para escolha, mais ``keep`` (a já
        gravada no registro em edição, para ele continuar válido)."""
        q = cls.available_q(today)
        if keep:
            q |= models.Q(pk=keep)
        return cls.objects.filter(models.Q(school=school) & q)

    def availability(self, today=None):
        """Rótulo curto da situação, ou "" quando disponível."""
        today = today or timezone.localdate()
        if not self.is_active:
            return "Inativa"
        if self.valid_from and self.valid_from > today:
            return f"A partir de {self.valid_from:%d/%m/%Y}"
        if self.valid_until and self.valid_until < today:
            return f"Vigência encerrada em {self.valid_until:%d/%m/%Y}"
        return ""


class TeacherAssignment(models.Model):
    school = models.ForeignKey(
        "core.School",
        verbose_name="escola",
        on_delete=models.CASCADE,
        related_name="teacher_assignments",
    )
    school_year = models.ForeignKey(
        SchoolYear,
        verbose_name="ano letivo",
        on_delete=models.CASCADE,
        related_name="teacher_assignments",
    )
    teacher = models.ForeignKey(
        "core.User",
        verbose_name="professor",
        on_delete=models.CASCADE,
        related_name="teacher_assignments",
        limit_choices_to={"role": "professor"},
    )
    class_group = models.ForeignKey(
        ClassGroup,
        verbose_name="turma",
        on_delete=models.CASCADE,
        related_name="teacher_assignments",
    )
    subject = models.ForeignKey(
        Subject,
        verbose_name="disciplina",
        on_delete=models.CASCADE,
        related_name="teacher_assignments",
    )
    # Período de atuação. Em branco: o ano letivo inteiro. Fora dele, a
    # atribuição não dá acesso a nada (substituição, licença...).
    starts_on = models.DateField("início da atuação", null=True, blank=True)
    ends_on = models.DateField("fim da atuação", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "atribuição de professor"
        verbose_name_plural = "atribuições de professores"
        ordering = ["class_group__name", "subject__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "school_year", "teacher", "class_group", "subject"],
                name="uniq_teacher_assignment",
            )
        ]

    def __str__(self):
        return f"{self.teacher} — {self.subject} ({self.class_group})"

class TeacherPermission(models.Model):
    """Acesso adicional de um professor a uma disciplina/turma que não é dele.

    Concedido pela direção, secretaria ou administração, com justificativa e
    prazo. Revogar não apaga: o registro fica no histórico.
    """

    class Kind(models.TextChoices):
        VIEW = "consulta", "Consulta (só ver)"
        EDIT = "edicao", "Consulta e lançamento"

    class Status(models.TextChoices):
        ACTIVE = "ativa", "Ativa"
        REVOKED = "revogada", "Revogada"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="teacher_permissions")
    teacher = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="extra_permissions",
                                verbose_name="professor", limit_choices_to={"role": "professor"})
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, verbose_name="turma")
    kind = models.CharField("tipo de permissão", max_length=10, choices=Kind.choices, default=Kind.VIEW)
    starts_on = models.DateField("início")
    ends_on = models.DateField("término", null=True, blank=True, help_text="Em branco: até ser revogada.")
    justification = models.CharField("justificativa", max_length=300)
    granted_by = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, related_name="+",
                                   verbose_name="autorizado por")
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.ACTIVE)
    revoked_by = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "permissão adicional de professor"
        verbose_name_plural = "permissões adicionais de professores"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.teacher} · {self.subject} · {self.class_group} ({self.get_kind_display()})"

    def is_current(self, today=None):
        from django.utils import timezone

        today = today or timezone.localdate()
        return (self.status == self.Status.ACTIVE and self.starts_on <= today
                and (self.ends_on is None or self.ends_on >= today))

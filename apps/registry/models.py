from django.conf import settings
from django.db import models

from apps.core.uploads import safe_photo_path, validate_photo


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
    registered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "matrícula"
        verbose_name_plural = "matrículas"
        ordering = ["-school_year__name", "student__first_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["school", "student", "school_year"],
                condition=~models.Q(status="desistente"),
                name="uniq_enrollment_per_year",
            )
        ]

    def __str__(self):
        return f"{self.student} — {self.class_group} ({self.school_year})"
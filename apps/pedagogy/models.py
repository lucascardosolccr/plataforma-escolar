from django.db import models
from django.utils import timezone

from apps.academics.models import ClassGroup, SchoolYear, Subject
from apps.core.models import School, User
from apps.registry.models import Student


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
    title = models.CharField("título", max_length=200)
    description = models.TextField("descrição", blank=True)
    weight = models.DecimalField("peso", max_digits=4, decimal_places=2, default=1.0)
    date = models.DateField("data", default=timezone.localdate)
    status = models.CharField(
        "situação", max_length=10, choices=Status.choices, default=Status.DRAFT
    )
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


class Activity(models.Model):
    """Atividade, trabalho, tarefa ou avaliação lançada para uma turma/disciplina."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.CASCADE, verbose_name="turma"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    title = models.CharField("título", max_length=200)
    description = models.TextField("descrição", blank=True)
    criteria = models.TextField("critérios de avaliação", blank=True)
    deadline = models.DateField("prazo", null=True, blank=True)
    published_date = models.DateField("data de publicação", default=timezone.localdate)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="activities_created"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_date", "-created_at"]
        verbose_name = "atividade"
        verbose_name_plural = "atividades"

    def __str__(self):
        return f"{self.title} — {self.class_group}"


class Submission(models.Model):
    """Entrega / não entrega de atividade por estudante."""

    class Status(models.TextChoices):
        DELIVERED = "entregue", "Entregue"
        NOT_DELIVERED = "nao_entregue", "Não entregue"

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
    comment = models.TextField("observação", blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

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
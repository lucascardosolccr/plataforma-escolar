from django.db import models


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

    class Meta:
        verbose_name = "disciplina"
        verbose_name_plural = "disciplinas"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="uniq_subject_per_school")
        ]

    def __str__(self):
        return self.name


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
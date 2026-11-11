"""Anos anteriores do estudante e resultado final de cada ano letivo.

Dois registros, ambos digitados pela secretaria a partir de documentos oficiais:

- ``PriorYear``: um ano cursado ANTES da plataforma (nesta escola ou em outra), copiado do histórico escolar
  em papel ou importado de planilha. Guarda só o que o histórico traz: série, escola, resultado, frequência e a
  nota final de cada componente. Sem cópia do documento.
- ``YearResult``: o resultado final oficial de um ano letivo cursado NA plataforma (aprovado, retido...). Sem
  ele, a trajetória deduz o resultado e diz que deduziu.

Nada aqui é dado sensível (LGPD art. 5º, II): nem saúde, nem inclusão, nem cor, renda ou família.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core.models import School


class Outcome(models.TextChoices):
    APPROVED = "aprovado", "Aprovado"
    COUNCIL = "aprovado_conselho", "Aprovado pelo conselho de classe"
    PARTIAL = "progressao_parcial", "Aprovado com dependência (progressão parcial)"
    RETAINED = "reprovado", "Retido (reprovado)"
    RETAINED_ABSENCE = "reprovado_falta", "Retido por frequência"
    TRANSFERRED = "transferido", "Transferido durante o ano"
    DROPOUT = "abandono", "Abandono (deixou de frequentar)"
    UNKNOWN = "nao_informado", "Não informado"


PROMOTED = {Outcome.APPROVED, Outcome.COUNCIL, Outcome.PARTIAL}
RETAINED = {Outcome.RETAINED, Outcome.RETAINED_ABSENCE}


class PriorYear(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Digitado"
        IMPORT = "importacao", "Importado de planilha"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="prior_years")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="prior_years",
                                verbose_name="estudante")
    year = models.PositiveSmallIntegerField("ano", validators=[MinValueValidator(1980), MaxValueValidator(2100)])
    grade_label = models.CharField("ano/série", max_length=40, help_text="Como está no histórico. Ex.: 3º ano.")
    stage = models.PositiveSmallIntegerField(
        "etapa (número)", null=True, blank=True,
        help_text="1 a 9 no fundamental, 10 a 12 no médio. Deduzido do ano/série.")
    school_name = models.CharField("escola", max_length=150, help_text="Escola onde o ano foi cursado.")
    outcome = models.CharField("resultado final", max_length=20, choices=Outcome.choices, default=Outcome.UNKNOWN)
    attendance_percent = models.DecimalField(
        "frequência anual (%)", max_digits=4, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))])
    passing_grade = models.DecimalField(
        "média de aprovação da escola de origem", max_digits=4, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("10"))],
        help_text="Na escala de 0 a 10. Em branco: a média de aprovação desta escola.")
    notes = models.CharField("observação", max_length=300, blank=True)
    source = models.CharField("origem", max_length=12, choices=Source.choices, default=Source.MANUAL)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["year", "pk"]
        verbose_name = "ano anterior do estudante"
        verbose_name_plural = "anos anteriores dos estudantes"
        constraints = [models.UniqueConstraint(fields=["student", "year", "school_name"],
                                               name="uniq_prior_year_per_school")]

    def __str__(self):
        return f"{self.student} · {self.year} · {self.grade_label}"


class PriorGrade(models.Model):
    record = models.ForeignKey(PriorYear, on_delete=models.CASCADE, related_name="grades")
    subject = models.CharField("componente", max_length=80)
    value = models.DecimalField("nota final", max_digits=5, decimal_places=2, null=True, blank=True)
    scale_max = models.DecimalField("nota máxima da escala", max_digits=5, decimal_places=2, default=Decimal("10"))
    concept = models.CharField("conceito", max_length=12, blank=True,
                               help_text="Quando o histórico traz conceito (A, B, MB...) em vez de nota.")

    class Meta:
        ordering = ["subject"]
        verbose_name = "nota de ano anterior"
        verbose_name_plural = "notas de anos anteriores"
        constraints = [models.UniqueConstraint(fields=["record", "subject"], name="uniq_prior_grade_subject")]

    def normalized(self):
        """Nota na escala de 0 a 10, ou None (conceito não vira número: inventaria precisão)."""
        if self.value is None or not self.scale_max:
            return None
        return float(self.value) * 10.0 / float(self.scale_max)


class YearResult(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="year_results")
    enrollment = models.OneToOneField("registry.Enrollment", on_delete=models.CASCADE, related_name="year_result",
                                      verbose_name="matrícula")
    outcome = models.CharField("resultado final", max_length=20, choices=Outcome.choices)
    note = models.CharField("observação", max_length=300, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    decided_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "resultado final do ano letivo"
        verbose_name_plural = "resultados finais dos anos letivos"

    def __str__(self):
        return f"{self.enrollment} · {self.get_outcome_display()}"

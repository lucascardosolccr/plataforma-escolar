"""Documentos da matrícula entregues em papel na secretaria.

A plataforma não guarda cópia dos documentos (dado pessoal de criança, LGPD art. 14): registra só que foi entregue,
quando e por quem conferiu, ou que a escola dispensou, com o motivo. A lista de documentos é de cada escola.
"""

from django.conf import settings
from django.db import models

from apps.core.models import School


class RequiredDocument(models.Model):
    #: Lista inicial, que a escola ajusta: (nome, obrigatório, orientação).
    DEFAULTS = [
        ("Certidão de nascimento ou RG do estudante", True, "Cópia simples; traga o original para conferir."),
        ("CPF do estudante", True, "Pode estar na certidão ou no RG."),
        ("Comprovante de residência", True, "Conta de água, luz ou telefone dos últimos 3 meses."),
        ("Documento com foto do responsável", True, ""),
        ("Caderneta de vacinação", True, "Cópia das páginas com as vacinas."),
        ("Histórico escolar ou declaração de transferência", False, "Para quem veio de outra escola."),
        ("Cartão do SUS", False, ""),
    ]

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="required_documents")
    name = models.CharField("documento", max_length=120)
    hint = models.CharField("orientação para a família", max_length=200, blank=True)
    mandatory = models.BooleanField("obrigatório", default=True,
                                    help_text="Desmarcado: só para quem tem (aparece, mas não conta como pendência).")
    position = models.PositiveSmallIntegerField("ordem", default=0)
    active = models.BooleanField("em uso", default=True)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "documento da matrícula"
        verbose_name_plural = "documentos da matrícula"

    def __str__(self):
        return self.name


class StudentDocument(models.Model):
    class Status(models.TextChoices):
        DELIVERED = "entregue", "Entregue"
        WAIVED = "dispensado", "Dispensado"

    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="paperwork",
                                verbose_name="estudante")
    document = models.ForeignKey(RequiredDocument, on_delete=models.CASCADE, related_name="deliveries",
                                 verbose_name="documento")
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DELIVERED)
    on = models.DateField("em")
    note = models.CharField("observação", max_length=200, blank=True)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    registered_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "documento entregue"
        verbose_name_plural = "documentos entregues"
        constraints = [models.UniqueConstraint(fields=["student", "document"], name="uniq_student_document")]

    def __str__(self):
        return f"{self.document} de {self.student}: {self.get_status_display()}"

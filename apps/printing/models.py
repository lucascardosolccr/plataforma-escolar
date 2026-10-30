from django.conf import settings
from django.db import models

from apps.core.uploads import safe_attachment_path, validate_attachment


class PrintRequest(models.Model):
    """Pedido de impressão de uma atividade, do professor à entrega.

    Fluxo: professor envia → coordenação analisa e aprova (ou pede correção,
    ou recusa, sempre justificando) → secretaria/setor de impressão imprime
    e entrega. Cada mudança fica em ``PrintEvent``; nada some sem histórico.
    """

    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        SENT = "enviada", "Enviada · aguardando análise"
        REVIEW = "analise", "Em análise · aguardando aprovação"
        APPROVED = "aguardando", "Aguardando impressão"
        PRINTING = "imprimindo", "Em impressão"
        PRINTED = "impressa", "Impressa"
        READY = "retirada", "Disponível para retirada"
        DELIVERED = "entregue", "Entregue"
        CORRECTION = "correcao", "Correção solicitada"
        REJECTED = "rejeitada", "Rejeitada"
        CANCELED = "cancelada", "Cancelada"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Normal"
        HIGH = "alta", "Alta (aplicação em até 2 dias)"

    school = models.ForeignKey("core.School", on_delete=models.CASCADE, related_name="print_requests")
    activity = models.ForeignKey("pedagogy.Activity", on_delete=models.CASCADE, related_name="print_requests",
                                 verbose_name="atividade")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                     related_name="print_requests", verbose_name="professor")
    attachment = models.ForeignKey("pedagogy.ActivityAttachment", on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name="arquivo da atividade")
    file = models.FileField("outro arquivo", upload_to=safe_attachment_path, validators=[validate_attachment],
                            null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    application_date = models.DateField("data de aplicação")
    desired_date = models.DateField("impressão desejada para")
    copies = models.PositiveIntegerField("cópias")
    pages = models.PositiveIntegerField("páginas por cópia", null=True, blank=True)
    duplex = models.BooleanField("frente e verso", default=False)
    color = models.BooleanField("colorida", default=False)
    priority = models.CharField("prioridade", max_length=6, choices=Priority.choices, default=Priority.NORMAL)
    notes = models.TextField("observações", blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DRAFT)
    decision_note = models.TextField("justificativa da coordenação", blank=True)
    submissions = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "pedido de impressão"
        verbose_name_plural = "pedidos de impressão"
        ordering = ["desired_date", "-priority", "created_at"]

    def __str__(self):
        return f"Impressão: {self.activity.title} ({self.copies} cópias)"

    @property
    def class_group(self):
        return self.activity.class_group

    @property
    def subject(self):
        return self.activity.subject

    @property
    def total_sheets(self):
        if not self.pages:
            return None
        per_copy = (self.pages + 1) // 2 if self.duplex else self.pages
        return per_copy * self.copies


class PrintEvent(models.Model):
    request = models.ForeignKey(PrintRequest, on_delete=models.CASCADE, related_name="events")
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    @property
    def to_label(self):
        return PrintRequest.Status(self.to_status).label

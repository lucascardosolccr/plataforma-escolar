"""Confirmação de rematrícula.

A secretaria abre uma campanha para o ano seguinte (prazo, orientações, termo de aceite opcional). A família de cada
estudante das turmas escolhidas responde se ele continua, diz o motivo se não continua e confere os dados de contato.
Cada resposta leva um selo (HMAC com a chave do servidor) e um código de comprovante: se alguém mudar a resposta direto
no banco, o selo deixa de conferir. A escola acompanha por turma e, na rematrícula em lote, quem disse que sai já vem
desmarcado.
"""

from django.conf import settings
from django.db import models

from apps.core.models import School


class Campaign(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="reenroll_campaigns",
                               verbose_name="escola")
    target_year = models.ForeignKey("academics.SchoolYear", on_delete=models.PROTECT, related_name="+",
                                    verbose_name="ano letivo de destino",
                                    help_text="O ano para o qual a família confirma a continuidade.")
    title = models.CharField("título", max_length=120, help_text="Ex.: Rematrícula 2027")
    message = models.TextField("orientações para as famílias", blank=True,
                               help_text="Documentos, datas, valores, o que muda no ano que vem, contato da secretaria.")
    terms = models.TextField("termo de aceite", blank=True,
                             help_text="Opcional. Se preenchido, quem confirma a continuidade precisa marcar “Li e "
                                       "concordo” (ex.: regimento, contrato, calendário).")
    class_groups = models.ManyToManyField("academics.ClassGroup", blank=True, related_name="+", verbose_name="turmas",
                                          help_text="Em branco: todas as turmas do ano letivo atual. Deixe de fora, "
                                                    "por exemplo, a última série, que se forma.")
    opens_on = models.DateField("início")
    deadline = models.DateField("prazo para responder")
    closed = models.BooleanField("encerrada antes do prazo", default=False)
    announced_at = models.DateTimeField(null=True, blank=True)
    reminded_on = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "campanha de rematrícula"
        verbose_name_plural = "campanhas de rematrícula"
        ordering = ["-opens_on", "-pk"]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("reenroll:detail", args=[self.pk])

    def is_open(self, today):
        return not self.closed and self.opens_on <= today <= self.deadline

    def state(self, today):
        if self.closed or today > self.deadline:
            return "encerrada"
        return "aberta" if today >= self.opens_on else "agendada"


class Answer(models.Model):
    class Decision(models.TextChoices):
        STAY = "continua", "Vai continuar"
        LEAVE = "sai", "Não vai continuar"

    class Reason(models.TextChoices):
        MOVING = "mudanca", "Mudança de cidade ou bairro"
        TRANSFER = "transferencia", "Vai estudar em outra escola"
        COST = "custo", "Custo ou situação financeira"
        SCHEDULE = "horario", "Horário, turno ou transporte"
        OTHER = "outro", "Outro motivo"

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="answers")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="+")
    decision = models.CharField("decisão", max_length=10, choices=Decision.choices)
    reason = models.CharField("motivo", max_length=15, choices=Reason.choices, blank=True)
    reason_text = models.CharField("comentário", max_length=300, blank=True)
    data_changes = models.TextField("mudanças no cadastro", max_length=1000, blank=True)
    data_done = models.BooleanField("cadastro atualizado pela secretaria", default=False)
    data_done_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+")
    accepted_terms = models.BooleanField(default=False)
    answered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    answered_by_name = models.CharField(max_length=150, blank=True)
    in_person = models.BooleanField("registrada pela escola", default=False)
    answered_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    seal = models.CharField(max_length=64)

    class Meta:
        verbose_name = "resposta de rematrícula"
        verbose_name_plural = "respostas de rematrícula"
        constraints = [models.UniqueConstraint(fields=["campaign", "student"], name="uniq_reenroll_answer")]

    def __str__(self):
        return f"{self.student} — {self.get_decision_display()}"

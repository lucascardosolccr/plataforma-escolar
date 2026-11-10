"""Saúde e emergência do estudante; quem pode buscá-lo na escola e o registro de cada retirada.

Ficha de saúde (LGPD, art. 11 e art. 14): dado sensível de criança e adolescente, informado pela família com
consentimento registrado, usado só para o cuidado do estudante na escola (alergia, crise, emergência). Quem vê
o quê está em ``access``; toda consulta da equipe fica na auditoria.

Retirada: a família mantém a lista de pessoas autorizadas e avisa saídas antecipadas; a portaria (ou a
secretaria) registra quem levou o estudante e a que horas. Retirada por pessoa fora da lista exige a
confirmação com um responsável e avisa a família como importante.
"""

from django.conf import settings
from django.db import models

from apps.core.models import School


class HealthRecord(models.Model):
    class Diet(models.TextChoices):
        NONE = "", "Nenhuma"
        LACTOSE = "sem_lactose", "Sem lactose"
        GLUTEN = "sem_gluten", "Sem glúten (doença celíaca)"
        VEGETARIAN = "vegetariana", "Vegetariana"
        OTHER = "outra", "Outra (descrever)"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="health_records")
    student = models.OneToOneField("registry.Student", on_delete=models.CASCADE, related_name="health_record",
                                   verbose_name="estudante")
    allergies = models.TextField("alergias", blank=True,
                                 help_text="Alimentos, medicamentos, picadas de inseto, látex... e a reação que causa.")
    diet = models.CharField("restrição alimentar", max_length=16, choices=Diet.choices, blank=True, default="")
    diet_notes = models.CharField("detalhes da alimentação", max_length=300, blank=True,
                                  help_text="O que não pode comer ou o que substituir.")
    conditions = models.TextField("condições de saúde que a escola precisa saber", blank=True,
                                  help_text="Ex.: asma, diabetes, epilepsia, cardiopatia.")
    medications = models.TextField("medicamentos de uso contínuo", blank=True,
                                   help_text="Nome, dose e horário. A escola só dá remédio com receita e autorização "
                                             "por escrito, conforme as regras da escola.")
    crisis_plan = models.TextField("o que fazer numa crise", blank=True,
                                   help_text="Sinais a observar e o que a equipe deve fazer até a família chegar.")
    insurance = models.CharField("plano de saúde (opcional)", max_length=120, blank=True)
    emergency_transport = models.BooleanField(
        "autorizo a escola a levar o estudante ao pronto atendimento numa emergência, se não me encontrar",
        default=False)
    consent_at = models.DateTimeField("consentimento registrado em", null=True, blank=True)
    consent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ficha de saúde"
        verbose_name_plural = "fichas de saúde"

    def __str__(self):
        return f"Ficha de saúde de {self.student}"

    @property
    def has_alert(self):
        """Algo que o professor precisa saber em sala (alergia, restrição, condição ou plano de crise)."""
        return bool(self.allergies.strip() or self.diet or self.conditions.strip() or self.crisis_plan.strip())

    @property
    def has_food_alert(self):
        return bool(self.diet or self.allergies.strip())


class EmergencyContact(models.Model):
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="emergency_contacts",
                                verbose_name="estudante")
    name = models.CharField("nome", max_length=120)
    relationship = models.CharField("parentesco ou relação", max_length=60)
    phone = models.CharField("telefone", max_length=30)
    order = models.PositiveSmallIntegerField("ordem de contato", default=1)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "contato de emergência"
        verbose_name_plural = "contatos de emergência"

    def __str__(self):
        return f"{self.name} ({self.relationship})"


class AuthorizedPickup(models.Model):
    """Pessoa que pode buscar o estudante, além dos responsáveis com vínculo aprovado."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="authorized_pickups")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="authorized_pickups",
                                verbose_name="estudante")
    name = models.CharField("nome completo", max_length=120)
    relationship = models.CharField("parentesco ou relação", max_length=60,
                                    help_text="Ex.: avó, tio, transporte escolar, vizinha.")
    document_hint = models.CharField(
        "documento para conferência", max_length=40,
        help_text="Tipo e os 4 últimos dígitos, ex.: RG final 4821. A portaria confere o documento na hora; o número "
                  "completo não é guardado.")
    phone = models.CharField("telefone", max_length=30, blank=True)
    valid_until = models.DateField("válida até (opcional)", null=True, blank=True,
                                   help_text="Em branco, vale até ser retirada da lista.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField("retirada da lista em", null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        ordering = ["name"]
        verbose_name = "pessoa autorizada a buscar"
        verbose_name_plural = "pessoas autorizadas a buscar"

    def __str__(self):
        return f"{self.name} ({self.relationship})"

    def valid_on(self, day):
        return self.revoked_at is None and (self.valid_until is None or self.valid_until >= day)


class DepartureNotice(models.Model):
    """A família avisa que o estudante sai mais cedo num dia (consulta, viagem) e quem vai buscar."""

    class Status(models.TextChoices):
        PENDING = "aguardando", "Aguardando"
        DONE = "realizada", "Saída registrada"
        CANCELED = "cancelada", "Cancelada pela família"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="departure_notices")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="departure_notices",
                                verbose_name="estudante")
    day = models.DateField("dia")
    time = models.TimeField("horário previsto")
    pickup = models.ForeignKey(AuthorizedPickup, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="quem vai buscar")
    guardian_pickup = models.BooleanField("eu mesmo(a) vou buscar", default=False)
    reason = models.CharField("motivo (opcional)", max_length=200, blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["day", "time"]
        verbose_name = "aviso de saída antecipada"
        verbose_name_plural = "avisos de saída antecipada"

    def who(self):
        if self.guardian_pickup and self.created_by:
            return f"{self.created_by.get_full_name() or self.created_by.username} (responsável)"
        return str(self.pickup) if self.pickup else "não informado"


class PickupRecord(models.Model):
    """Retirada registrada: quem levou o estudante, a que horas e quem conferiu."""

    class Kind(models.TextChoices):
        GUARDIAN = "responsavel", "Responsável com vínculo"
        AUTHORIZED = "autorizada", "Pessoa da lista de autorizados"
        OTHER = "outra", "Pessoa fora da lista (confirmada com a família)"
        ALONE = "sozinho", "Saiu sozinho(a), com autorização assinada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="pickup_records")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="pickup_records",
                                verbose_name="estudante")
    at = models.DateTimeField("horário")
    kind = models.CharField("quem buscou", max_length=12, choices=Kind.choices)
    guardian = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+", verbose_name="responsável")
    pickup = models.ForeignKey(AuthorizedPickup, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
                               verbose_name="pessoa autorizada")
    person_name = models.CharField("nome de quem buscou", max_length=120)
    verification = models.CharField("confirmação com a família", max_length=300, blank=True,
                                    help_text="Obrigatória para pessoa fora da lista: com quem falou, por qual meio.")
    notice = models.ForeignKey(DepartureNotice, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "retirada do estudante"
        verbose_name_plural = "retiradas de estudantes"

    def __str__(self):
        return f"{self.student} com {self.person_name}"

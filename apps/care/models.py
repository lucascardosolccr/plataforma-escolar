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


class HealthIncident(models.Model):
    """Atendimento na escola: mal-estar, febre, machucado, reação alérgica ou crise. A família é avisada na hora e
    marca "ciente". Dado de saúde (LGPD, art. 11): vê quem vê a ficha completa e quem registrou."""

    class Kind(models.TextChoices):
        UNWELL = "mal_estar", "Mal-estar (dor, enjoo, tontura)"
        FEVER = "febre", "Febre"
        INJURY = "machucado", "Queda, batida ou machucado"
        ALLERGY = "alergia", "Reação alérgica"
        CRISIS = "crise", "Crise (asma, convulsão ou outra condição)"
        OTHER = "outro", "Outro"

    class Outcome(models.TextChoices):
        BACK = "voltou", "Voltou para a aula"
        WATCH = "observacao", "Ficou em observação na escola"
        PICKUP = "buscar", "Pedimos que a família venha buscar"
        HOSPITAL = "pronto_atendimento", "Levado(a) ao pronto atendimento"

    #: Desfechos em que a família precisa agir: o aviso diz isso no título.
    URGENT = (Outcome.PICKUP, Outcome.HOSPITAL)

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="health_incidents")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="health_incidents",
                                verbose_name="estudante")
    happened_at = models.DateTimeField("quando")
    kind = models.CharField("o que foi", max_length=20, choices=Kind.choices)
    place = models.CharField("onde", max_length=80, blank=True, help_text="Ex.: pátio, quadra, sala 3.")
    description = models.TextField("o que aconteceu", max_length=1000)
    head_hit = models.BooleanField("bateu a cabeça", default=False,
                                   help_text="A família recebe as orientações do que observar nas próximas horas.")
    care_given = models.TextField("o que a escola fez", max_length=1000,
                                  help_text="Ex.: repouso na secretaria, compressa de gelo, curativo, conferiu a "
                                            "ficha de saúde. Remédio só com receita e autorização por escrito.")
    phone_contact = models.CharField("contato por telefone", max_length=150, blank=True,
                                     help_text="Com quem falou e a que horas (ex.: mãe, 10h15).")
    outcome = models.CharField("desfecho", max_length=20, choices=Outcome.choices)
    registered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="+")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    family_note = models.CharField("recado da família", max_length=300, blank=True)

    class Meta:
        verbose_name = "atendimento de saúde"
        verbose_name_plural = "atendimentos de saúde"
        ordering = ["-happened_at"]

    def __str__(self):
        return f"{self.student} — {self.get_kind_display()} em {self.happened_at:%d/%m/%Y}"


class MedicationRequest(models.Model):
    """Pedido da família para a escola dar um remédio no horário de aula. A escola só dá depois de conferir a
    receita (a secretaria autoriza) e registra cada dose; a família recebe um aviso a cada uma."""

    class Status(models.TextChoices):
        PENDING = "pendente", "Aguardando a escola"
        APPROVED = "aprovado", "Autorizado"
        REFUSED = "recusado", "Não autorizado"
        ENDED = "encerrado", "Encerrado"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="medication_requests")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="medication_requests",
                                verbose_name="estudante")
    medicine = models.CharField("remédio", max_length=120, help_text="Nome e concentração, como na receita. "
                                                                    "Ex.: Amoxicilina 250 mg/5 ml.")
    dose = models.CharField("dose", max_length=80, help_text="Ex.: 5 ml, 1 comprimido, 2 jatos.")
    times = models.CharField("horários na escola", max_length=60,
                             help_text="Só os que caem no horário de aula. Ex.: 10:00 ou 10:00, 14:30.")
    start_date = models.DateField("a partir de")
    end_date = models.DateField("até", help_text="Último dia. Para uso contínuo, o fim do ano letivo.")
    reason = models.CharField("para quê (opcional)", max_length=150, blank=True, help_text="Ex.: infecção de garganta.")
    instructions = models.CharField("como dar (opcional)", max_length=300, blank=True,
                                    help_text="Ex.: depois do lanche; agitar antes; guardar na geladeira.")
    prescriber = models.CharField("quem receitou", max_length=120, help_text="Nome do médico ou dentista e o CRM/CRO.")
    prescription_date = models.DateField("data da receita")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField("observação da escola", max_length=300, blank=True)
    ended_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+")
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "pedido de medicação na escola"
        verbose_name_plural = "pedidos de medicação na escola"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"{self.medicine} para {self.student}"

    def time_list(self):
        return [t for t in (self.times or "").split(", ") if t]

    def active_on(self, day):
        return self.status == self.Status.APPROVED and self.start_date <= day <= self.end_date

    @property
    def state_label(self):
        """A situação como a família entende: autorizado com o prazo vencido já terminou."""
        from django.utils import timezone

        if self.status == self.Status.APPROVED and self.end_date < timezone.localdate():
            return "Terminou"
        return self.get_status_display()


class MedicationDose(models.Model):
    """Cada horário de um remédio autorizado: quem deu, quando, ou por que não foi dado."""

    class Result(models.TextChoices):
        GIVEN = "dado", "Tomou"
        REFUSED = "recusou", "Não quis tomar"
        ABSENT = "ausente", "Não estava na escola"
        NOT_GIVEN = "nao_dado", "Não foi dado (ver observação)"

    request = models.ForeignKey(MedicationRequest, on_delete=models.CASCADE, related_name="doses")
    day = models.DateField("dia")
    slot = models.CharField("horário", max_length=5)
    result = models.CharField("resultado", max_length=10, choices=Result.choices)
    note = models.CharField("observação", max_length=200, blank=True)
    given_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    given_at = models.DateTimeField("registrado em", auto_now_add=True)

    class Meta:
        verbose_name = "dose de medicação na escola"
        verbose_name_plural = "doses de medicação na escola"
        ordering = ["-day", "-slot"]
        constraints = [models.UniqueConstraint(fields=["request", "day", "slot"], name="uniq_medication_dose")]

    def __str__(self):
        return f"{self.request.medicine} {self.day:%d/%m} {self.slot}: {self.get_result_display()}"

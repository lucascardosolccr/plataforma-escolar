"""Necessidades específicas, documentação (laudos) e plano individualizado.

Princípios que o modelo materializa (ver ``docs/FLUXO_LAUDOS_E_INCLUSAO.md``):

- Distinção entre o que a família declarou, o documento que ela anexou, o
  documento recebido pela escola, o documento analisado, a informação
  validada pela escola e as necessidades identificadas pela equipe. Enviar
  um documento nunca valida nada sozinho.
- Necessidade de apoio e plano não dependem de laudo (Decreto nº 12.686/2025,
  art. 11, § 7º; Portaria MEC nº 421/2026, art. 7º, § 4º).
- Nada é apagado em silêncio: cada mudança vira um ``SupportEvent``; cada
  versão anterior do plano fica em ``SupportPlanVersion``; documento
  substituído continua guardado; descarte por retenção apaga o arquivo e
  mantém o registro de que existiu.
- Categoria nunca gera plano ou estratégia automaticamente.
"""

import uuid

from django.db import models
from django.utils import timezone

from apps.core.models import School, User

DEFAULT_CATEGORIES = [
    "Transtorno do Espectro Autista (TEA)",
    "Transtorno do Déficit de Atenção com Hiperatividade (TDAH)",
    "Dislexia",
    "Discalculia",
    "Outras condições relacionadas à aprendizagem",
    "Deficiência visual",
    "Deficiência auditiva",
    "Deficiência física",
    "Deficiência intelectual",
    "Altas habilidades ou superdotação",
    "Outras condições ou necessidades específicas",
]


class SupportSettings(models.Model):
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="support_settings")
    max_upload_mb = models.PositiveSmallIntegerField("tamanho máximo por arquivo (MB)", default=10)
    retention_years = models.PositiveSmallIntegerField(
        "guardar documentos por quantos anos após a saída do estudante", default=5,
        help_text="Depois desse prazo, a direção pode descartar o arquivo; o registro de que existiu é mantido.")
    contact = models.CharField("contato para dúvidas sobre os dados", max_length=200, blank=True,
                               help_text="Ex.: encarregado de dados ou secretaria, com e-mail ou telefone.")
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuração de apoio à inclusão"

    @classmethod
    def for_school(cls, school):
        return cls.objects.filter(school=school).first() or cls(school=school)


class SupportCategory(models.Model):
    """Lista configurável e não exaustiva de condições ou necessidades."""

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="support_categories")
    name = models.CharField("nome", max_length=120)
    order = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField("em uso", default=True)

    class Meta:
        ordering = ["order", "name"]
        constraints = [models.UniqueConstraint(fields=["school", "name"], name="uniq_support_category")]
        verbose_name = "categoria de necessidade específica"
        verbose_name_plural = "categorias de necessidade específica"

    def __str__(self):
        return self.name

    @classmethod
    def ensure_defaults(cls, school):
        if not cls.objects.filter(school=school).exists():
            cls.objects.bulk_create(cls(school=school, name=n, order=i) for i, n in enumerate(DEFAULT_CATEGORIES))
        return cls.objects.filter(school=school, active=True)


class SupportCase(models.Model):
    """Ficha de apoio do estudante (uma por estudante)."""

    class Status(models.TextChoices):
        NOT_INFORMED = "nao_informado", "Não informado"
        DECLARED = "informado", "Informado pela família"
        ATTACHED = "anexado", "Documento anexado"
        AWAITING = "aguardando", "Aguardando análise"
        RECEIVED = "recebido", "Documento recebido"
        NEEDS_MORE = "complementacao", "Necessita complementação"
        ANALYZED = "analisado", "Documentação analisada"
        UPDATED = "atualizado", "Registro atualizado"
        ARCHIVED = "arquivado", "Arquivado"

    class HasReport(models.TextChoices):
        UNKNOWN = "", "Não informado"
        YES = "sim", "Sim, possui laudo ou relatório"
        NO = "nao", "Não possui"
        PREFER_NOT = "nao_informar", "Prefere não informar agora"

    class LegalBasis(models.TextChoices):
        UNDEFINED = "", "A definir com o encarregado de dados"
        LEGAL_DUTY = "obrigacao_legal", "Cumprimento de obrigação legal ou regulatória (LGPD, art. 11, II, a)"
        PUBLIC_POLICY = "politica_publica", "Execução de política pública prevista em lei ou regulamento (art. 11, II, b)"
        CONSENT = "consentimento", "Consentimento específico e destacado do responsável (art. 11, I)"

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    student = models.OneToOneField("registry.Student", on_delete=models.CASCADE, related_name="support_case")
    status = models.CharField("situação", max_length=16, choices=Status.choices, default=Status.NOT_INFORMED)
    has_report = models.CharField("possui laudo?", max_length=14, choices=HasReport.choices, blank=True, default="")
    declared_categories = models.ManyToManyField(SupportCategory, blank=True, related_name="declared_in",
                                                 verbose_name="condições informadas pela família")
    family_notes = models.TextField("informações complementares da família", blank=True)
    declared_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    declared_at = models.DateTimeField(null=True, blank=True)
    validated_categories = models.ManyToManyField(
        SupportCategory, blank=True, related_name="validated_in",
        verbose_name="condições validadas conforme procedimento institucional")
    validation_basis = models.TextField("procedimento institucional e fundamento da validação", blank=True)
    validated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    validated_at = models.DateTimeField(null=True, blank=True)
    legal_basis = models.CharField("base legal registrada pela escola", max_length=20, choices=LegalBasis.choices,
                                   blank=True, default="")
    legal_basis_notes = models.TextField("observações sobre a base legal", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "ficha de apoio"
        verbose_name_plural = "fichas de apoio"

    def __str__(self):
        return f"Ficha de apoio — {self.student}"


def support_upload_path(instance, filename):
    """Nome imprevisível e sem dado do estudante; extensão já validada."""
    import os

    ext = os.path.splitext(filename)[1].lower()
    return f"inclusao/{timezone.now():%Y}/{uuid.uuid4().hex}{ext}"


class SupportDocument(models.Model):
    class Source(models.TextChoices):
        FAMILY = "familia", "Anexado pela família"
        SCHOOL = "escola", "Recebido pela escola"

    class Kind(models.TextChoices):
        REPORT = "laudo", "Laudo ou relatório de profissional"
        SCHOOL_REPORT = "relatorio_escolar", "Relatório escolar ou de outra escola"
        OTHER = "outro", "Outro documento"

    class Status(models.TextChoices):
        AWAITING = "aguardando", "Aguardando análise"
        RECEIVED = "recebido", "Recebido pela escola"
        ANALYZED = "analisado", "Analisado"
        REPLACED = "substituido", "Substituído por versão mais nova"
        ARCHIVED = "arquivado", "Arquivado"
        DISCARDED = "descartado", "Descartado (prazo de guarda)"

    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="documents")
    # Identificador do endereço de download: imprevisível, ao contrário do pk.
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    file = models.FileField(upload_to=support_upload_path, blank=True)
    original_name = models.CharField("nome do arquivo", max_length=200)
    content_type = models.CharField(max_length=60)
    size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    source = models.CharField("origem", max_length=10, choices=Source.choices)
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices, default=Kind.REPORT)
    issued_on = models.DateField("data de emissão", null=True, blank=True)
    issuer = models.CharField("profissional ou instituição emissora", max_length=200, blank=True)
    description = models.CharField("descrição", max_length=300, blank=True)
    status = models.CharField("situação", max_length=12, choices=Status.choices)
    replaces = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="replaced_by", verbose_name="substitui")
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField("registro da análise (interno)", blank=True)
    discarded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "documento de apoio"
        verbose_name_plural = "documentos de apoio"

    def __str__(self):
        return self.original_name

    @property
    def available(self):
        return bool(self.file) and self.status != self.Status.DISCARDED


class SupportRequest(models.Model):
    """Pedido de complementação ou esclarecimento feito pela escola à família."""

    class Status(models.TextChoices):
        OPEN = "aberta", "Aguardando a família"
        ANSWERED = "respondida", "Respondida pela família"
        CLOSED = "encerrada", "Encerrada pela escola"

    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="requests")
    message = models.TextField("o que a escola precisa")
    due_on = models.DateField("responder até", null=True, blank=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.OPEN)
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    response = models.TextField("resposta da família", blank=True)
    responded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "pedido de complementação"
        verbose_name_plural = "pedidos de complementação"


class SupportNeed(models.Model):
    """Necessidade pedagógica ou de acessibilidade identificada pela equipe.

    Pode existir sem laudo e sem categoria. ``share_with_teachers`` decide se
    entra nas orientações dos professores do estudante.
    """

    class Area(models.TextChoices):
        ACCESS = "acessibilidade", "Acessibilidade física e mobilidade"
        VISION = "visual", "Acesso visual (leitura, ampliação, contraste)"
        HEARING = "auditiva", "Acesso auditivo (Libras, legenda, posição na sala)"
        COMMUNICATION = "comunicacao", "Comunicação e interação"
        LEARNING = "aprendizagem", "Aprendizagem (leitura, escrita, cálculo, atenção)"
        ENRICHMENT = "enriquecimento", "Enriquecimento e aprofundamento"
        CARE = "cuidados", "Cuidados no ambiente escolar"
        OTHER = "outra", "Outra"

    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="needs")
    area = models.CharField("área", max_length=16, choices=Area.choices)
    description = models.TextField("necessidade observada")
    resources = models.TextField("recursos de acessibilidade e tecnologia assistiva", blank=True)
    classroom_strategies = models.TextField("estratégias recomendadas em sala", blank=True)
    care_notes = models.TextField("cuidados importantes no contexto escolar", blank=True)
    share_with_teachers = models.BooleanField("mostrar aos professores do estudante", default=True)
    active = models.BooleanField("vigente", default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-active", "area"]
        verbose_name = "necessidade de apoio"
        verbose_name_plural = "necessidades de apoio"


class SupportPlan(models.Model):
    """Plano individualizado em documento único (PAEE + PEI), derivado do
    estudo de caso (Decreto nº 12.686/2025; Portaria MEC nº 421/2026)."""

    class Status(models.TextChoices):
        DRAFT = "rascunho", "Em elaboração"
        ACTIVE = "vigente", "Vigente"
        REVIEW = "revisao", "Em revisão"
        CLOSED = "encerrado", "Encerrado"

    PLAN_FIELDS = [
        # Estudo de caso (Decreto nº 12.686/2025, art. 11, § 1º)
        ("barriers", "Levantamento inicial de demandas e barreiras"),
        ("context_analysis", "Análise das barreiras e do contexto escolar"),
        ("strengths", "Potencialidades do estudante"),
        ("support_needs", "Necessidades de apoio"),
        ("family_participation", "Participação do estudante e da família no estudo de caso"),
        # PAEE (Portaria MEC nº 421/2026, art. 10)
        ("materials_resources", "Materiais e recursos para eliminar ou minimizar barreiras"),
        ("assistive_tech", "Tecnologia assistiva e comunicação aumentativa e alternativa"),
        ("support_professional", "Profissional de apoio, intérprete de Libras ou guia-intérprete"),
        ("training_network", "Formação da equipe e acionamento da rede de proteção"),
        # PEI (Portaria MEC nº 421/2026, art. 11)
        ("aee_activities", "Atividades no AEE e articulação com o professor regente"),
        ("curricular_measures", "Medidas de acessibilidade curricular, didático-pedagógica e avaliativa"),
        ("objectives", "Objetivos pedagógicos"),
        ("strategies", "Estratégias de ensino"),
        ("reasonable_adjustments", "Adaptações razoáveis"),
        ("monitoring", "Estratégias de acompanhamento e monitoramento"),
        ("evidence", "Evidências de aprendizagem"),
        ("referrals", "Encaminhamentos pedagógicos"),
        # O que os professores veem
        ("teacher_summary", "Orientações para os professores"),
    ]
    TEACHER_FIELDS = ["teacher_summary", "curricular_measures", "strategies", "reasonable_adjustments",
                      "assistive_tech", "materials_resources", "objectives", "monitoring"]

    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="plans")
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DRAFT)
    starts_on = models.DateField("início da vigência")
    review_due = models.DateField("revisar até", help_text="No máximo um ano (Portaria MEC nº 421/2026, art. 7º, § 3º).")
    responsibles = models.ManyToManyField(User, blank=True, related_name="support_plans",
                                          verbose_name="responsáveis pelo acompanhamento")
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-starts_on", "-pk"]
        verbose_name = "plano individualizado"
        verbose_name_plural = "planos individualizados"

    def __str__(self):
        return f"Plano individualizado de {self.case.student} ({self.get_status_display()})"

    def snapshot(self):
        return {name: getattr(self, name) for name, _label in self.PLAN_FIELDS} | {
            "status": self.status, "starts_on": self.starts_on.isoformat(), "review_due": self.review_due.isoformat()}

    @property
    def review_overdue(self):
        return self.status in (self.Status.ACTIVE, self.Status.REVIEW) and self.review_due < timezone.localdate()


for _name, _label in SupportPlan.PLAN_FIELDS:
    SupportPlan.add_to_class(_name, models.TextField(_label, blank=True))


class SupportPlanVersion(models.Model):
    """Como o plano estava antes de cada alteração."""

    plan = models.ForeignKey(SupportPlan, on_delete=models.CASCADE, related_name="versions")
    version = models.PositiveIntegerField()
    data = models.JSONField()
    saved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-version"]


class SupportPlanReview(models.Model):
    class Kind(models.TextChoices):
        REVIEW = "revisao", "Revisão do plano"
        PROGRESS = "evolucao", "Registro de evolução"
        FAMILY = "devolutiva", "Devolutiva à família"
        REFERRAL = "encaminhamento", "Encaminhamento"

    plan = models.ForeignKey(SupportPlan, on_delete=models.CASCADE, related_name="reviews")
    kind = models.CharField("tipo", max_length=16, choices=Kind.choices)
    notes = models.TextField("registro")
    happened_on = models.DateField("data", default=timezone.localdate)
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-happened_on", "-pk"]

    @property
    def visible_to_family(self):
        return self.kind == self.Kind.FAMILY


class SupportEvent(models.Model):
    """Histórico da ficha. Só cresce: não há edição nem exclusão."""

    case = models.ForeignKey(SupportCase, on_delete=models.CASCADE, related_name="events")
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    at = models.DateTimeField(auto_now_add=True)
    action = models.CharField("ação", max_length=200)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, blank=True)
    note = models.TextField(blank=True)
    visible_to_family = models.BooleanField(default=True)

    class Meta:
        ordering = ["-at", "-pk"]

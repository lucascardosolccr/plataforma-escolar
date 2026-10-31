"""EIA-Cognitio: evidências individuais de aprendizagem por habilidade.

Unidade de análise: a habilidade curricular, sustentada por evidências concretas
produzidas pelo estudante (questões de avaliação, atividades, trabalhos,
observações do professor, produções escritas analisadas e revisadas).

Princípios fixos (ver ``docs/EIA_COGNITIO_MODELO_DE_EVIDENCIAS.md``):

- Ausência de resposta, falta ou entrega não registrada NÃO é evidência de
  dificuldade: fica registrada como "sem evidência" e não entra na média.
- Toda conclusão aponta para as evidências que a sustentam (``SkillEvidence``
  guarda a origem: tipo, registro e rótulo).
- Nada aqui reprova, classifica ou restringe direitos de estudante.
"""

from django.db import models
from django.utils import timezone

from apps.academics.models import ClassGroup, Subject
from apps.core.models import School, User


class MasteryScale(models.Model):
    """Critérios explícitos da escala de domínio, configuráveis pela escola.

    ``t1``, ``t2`` e ``t3`` são cortes da proporção de acerto ponderada (0 a 1):
    abaixo de ``t1`` → dificuldade observada; até ``t2`` → em desenvolvimento;
    até ``t3`` → em consolidação; a partir de ``t3`` → consolidada nas
    evidências observadas. Antes disso, é preciso ter pelo menos
    ``min_evidence`` evidências válidas e peso total ``min_weight``.
    """

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="mastery_scale")
    t1 = models.DecimalField("corte: dificuldade observada abaixo de", max_digits=3, decimal_places=2, default=0.40)
    t2 = models.DecimalField("corte: em desenvolvimento abaixo de", max_digits=3, decimal_places=2, default=0.60)
    t3 = models.DecimalField("corte: em consolidação abaixo de", max_digits=3, decimal_places=2, default=0.80)
    min_evidence = models.PositiveSmallIntegerField("mínimo de evidências válidas", default=2)
    min_weight = models.DecimalField("peso mínimo das evidências", max_digits=4, decimal_places=2, default=1.20)
    half_life_days = models.PositiveSmallIntegerField(
        "meia-vida das evidências (dias)", default=120,
        help_text="Evidências antigas pesam menos: com 120, uma evidência de 4 meses vale metade.")
    stale_days = models.PositiveSmallIntegerField("evidência deixa de ser recente após (dias)", default=60)
    share_with_family = models.BooleanField(
        "mostrar à família e ao estudante o resumo de aprendizagens", default=False,
        help_text="Lista de habilidades já demonstradas e em desenvolvimento, em linguagem própria, sem alertas, "
                  "porcentagens nem comparação com colegas.")
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "escala de domínio"

    @classmethod
    def for_school(cls, school):
        return cls.objects.filter(school=school).first() or cls(school=school)


class Question(models.Model):
    """Questão (item) de uma avaliação, ligada a uma ou mais habilidades."""

    class Complexity(models.IntegerChoices):
        BASIC = 1, "Básica"
        MEDIUM = 2, "Intermediária"
        ADVANCED = 3, "Avançada"

    class EvidenceType(models.TextChoices):
        OBJECTIVE = "objetiva", "Objetiva (múltipla escolha, verdadeiro ou falso)"
        OPEN = "discursiva", "Discursiva (resposta escrita)"
        TEXT = "producao", "Produção textual"
        PROCEDURE = "procedimento", "Resolução com procedimento"
        ORAL = "oral", "Oral"
        PRACTICE = "pratica", "Prática ou experimental"
        PROJECT = "projeto", "Projeto"

    evaluation = models.ForeignKey("pedagogy.Evaluation", on_delete=models.CASCADE, related_name="questions")
    number = models.PositiveSmallIntegerField("número")
    label = models.CharField("enunciado resumido", max_length=200)
    max_points = models.DecimalField("pontuação máxima", max_digits=5, decimal_places=2, default=1)
    complexity = models.PositiveSmallIntegerField("complexidade", choices=Complexity.choices, default=Complexity.MEDIUM)
    evidence_type = models.CharField("tipo de evidência", max_length=14, choices=EvidenceType.choices,
                                     default=EvidenceType.OBJECTIVE)
    criteria = models.TextField("critérios de avaliação e indicadores observáveis", blank=True)
    expected_concepts = models.CharField(
        "conceitos esperados na resposta", max_length=300, blank=True,
        help_text="Separados por vírgula. Usados só como apoio na análise de respostas escritas.")
    skills = models.ManyToManyField("curriculum.CurriculumItem", through="QuestionSkill", related_name="questions")

    class Meta:
        ordering = ["evaluation", "number"]
        constraints = [models.UniqueConstraint(fields=["evaluation", "number"], name="uniq_question_number")]
        verbose_name = "questão"
        verbose_name_plural = "questões"

    def __str__(self):
        return f"Q{self.number}. {self.label}"


class QuestionSkill(models.Model):
    class Role(models.TextChoices):
        MAIN = "principal", "Habilidade principal"
        SECONDARY = "secundaria", "Habilidade secundária"

    question = models.ForeignKey(Question, on_delete=models.CASCADE)
    item = models.ForeignKey("curriculum.CurriculumItem", on_delete=models.PROTECT)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MAIN)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["question", "item"], name="uniq_question_skill")]


class QuestionResponse(models.Model):
    """Resultado de um estudante numa questão."""

    class Status(models.TextChoices):
        ANSWERED = "respondida", "Respondida"
        BLANK = "em_branco", "Em branco"
        ABSENT = "ausente", "Ausente"
        NOT_APPLIED = "nao_aplicada", "Não aplicada"

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="responses")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="question_responses")
    status = models.CharField("situação", max_length=12, choices=Status.choices, default=Status.ANSWERED)
    points = models.DecimalField("pontos", max_digits=5, decimal_places=2, null=True, blank=True)
    error_type = models.CharField("tipo de erro observado", max_length=20, blank=True)
    answer_text = models.TextField("resposta escrita (transcrição)", blank=True)
    note = models.CharField("observação", max_length=300, blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["question", "student"], name="uniq_question_response")]


class SkillObservation(models.Model):
    """Observação direta do professor sobre um estudante numa habilidade."""

    class Level(models.IntegerChoices):
        DIFFICULTY = 1, "Dificuldade observada"
        INITIAL = 2, "Em desenvolvimento inicial"
        DEVELOPING = 3, "Em desenvolvimento"
        CONSOLIDATING = 4, "Em consolidação"
        CONSOLIDATED = 5, "Consolidada na situação observada"

    RATIO = {1: 0.2, 2: 0.4, 3: 0.55, 4: 0.75, 5: 0.92}

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="skill_observations")
    item = models.ForeignKey("curriculum.CurriculumItem", on_delete=models.PROTECT, verbose_name="habilidade")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, verbose_name="turma")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    observed_on = models.DateField("data", default=timezone.localdate)
    level = models.PositiveSmallIntegerField("o que foi observado", choices=Level.choices)
    context = models.CharField("situação observada", max_length=200,
                               help_text="Ex.: leitura compartilhada, resolução no quadro, experimento em grupo.")
    note = models.TextField("registro", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_on", "-pk"]


class SkillEvidence(models.Model):
    """Repositório histórico de evidências por estudante e habilidade.

    Gerado a partir dos registros que o professor já faz (questões, notas de
    avaliação ligada a habilidades, atividades, trabalhos, observações). Cada
    linha aponta para a origem. ``ratio`` vazio = registro sem evidência de
    desempenho (ausente, em branco, não entregue), que não entra no cálculo.
    """

    class Source(models.TextChoices):
        QUESTION = "questao", "Questão de avaliação"
        EVALUATION = "avaliacao", "Nota de avaliação ligada à habilidade"
        ACTIVITY = "atividade", "Atividade de casa"
        GROUP_WORK = "trabalho", "Trabalho em grupo"
        OBSERVATION = "observacao", "Observação do professor"
        TEXT = "texto", "Produção escrita (análise revisada pelo professor)"

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="skill_evidence")
    item = models.ForeignKey("curriculum.CurriculumItem", on_delete=models.CASCADE, related_name="evidence")
    source_type = models.CharField(max_length=12, choices=Source.choices)
    source_id = models.PositiveIntegerField()
    source_label = models.CharField(max_length=200)
    class_group = models.ForeignKey(ClassGroup, on_delete=models.SET_NULL, null=True)
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True)
    observed_on = models.DateField()
    ratio = models.FloatField(null=True, blank=True)
    weight = models.FloatField(default=1.0)
    error_type = models.CharField(max_length=20, blank=True)
    no_evidence_reason = models.CharField(max_length=40, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["observed_on", "pk"]
        indexes = [models.Index(fields=["student", "item"]), models.Index(fields=["class_group", "item"])]
        constraints = [models.UniqueConstraint(fields=["student", "item", "source_type", "source_id"],
                                               name="uniq_skill_evidence")]


class TextAnalysis(models.Model):
    """Produção escrita de um estudante analisada por regras explícitas (PLN sem IA paga).

    A análise automática só aponta indícios, com o trecho que os sustenta e o grau
    de confiança. Vira evidência apenas depois que o professor revisa e registra
    o nível observado (``teacher_level``). Nunca gera nota.
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="text_analyses")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, verbose_name="turma")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    title = models.CharField("produção", max_length=200, help_text="Ex.: Resposta da questão 3, relatório do experimento.")
    prompt_text = models.TextField("enunciado ou proposta", blank=True)
    text = models.TextField("texto do estudante")
    expected_concepts = models.CharField("conceitos esperados", max_length=300, blank=True)
    genre = models.CharField("gênero ou tipo de texto", max_length=60, blank=True)
    produced_on = models.DateField("data", default=timezone.localdate)
    items = models.ManyToManyField("curriculum.CurriculumItem", blank=True, verbose_name="habilidades")
    question_response = models.ForeignKey(QuestionResponse, on_delete=models.SET_NULL, null=True, blank=True)
    result = models.JSONField("resultado da análise", default=dict)
    engine_version = models.CharField(max_length=20, blank=True)
    reviewed = models.BooleanField("revisada pelo professor", default=False)
    teacher_level = models.PositiveSmallIntegerField("nível observado pelo professor", null=True, blank=True,
                                                     choices=SkillObservation.Level.choices)
    teacher_feedback = models.TextField("devolutiva ao estudante", blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-produced_on", "-pk"]


class AnalysisFeedback(models.Model):
    """O professor concorda ou discorda de cada indício da análise automática.

    Alimenta o monitoramento da qualidade do analisador (taxa de concordância).
    """

    analysis = models.ForeignKey(TextAnalysis, on_delete=models.CASCADE, related_name="feedback")
    signal = models.CharField(max_length=60)
    agrees = models.BooleanField()
    comment = models.CharField(max_length=300, blank=True)
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["analysis", "signal"], name="uniq_feedback_signal")]


class SkillRelation(models.Model):
    """Relação pedagógica entre habilidades (pré-requisito → habilidade que pode depender dele).

    Nunca é lei determinística. O tipo diz de onde vem a relação; o status diz se
    um profissional já a validou. Relações automáticas nascem "propostas".
    """

    class Kind(models.TextChoices):
        PROGRESSION = "progressao", "Progressão curricular (mesma unidade, ano seguinte)"
        CONCEPTUAL = "conceitual", "Relação conceitual"
        HYPOTHESIS = "hipotese", "Hipótese de dependência"
        STATISTICAL = "estatistica", "Associação estatística observada"

    class Status(models.TextChoices):
        PROPOSED = "proposta", "Proposta (a validar)"
        VALIDATED = "validada", "Validada por profissional"
        REJECTED = "rejeitada", "Rejeitada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, null=True, blank=True)
    source = models.ForeignKey("curriculum.CurriculumItem", on_delete=models.CASCADE, related_name="dependents_rel",
                               verbose_name="pré-requisito")
    target = models.ForeignKey("curriculum.CurriculumItem", on_delete=models.CASCADE, related_name="prerequisites_rel",
                               verbose_name="habilidade que pode depender")
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices)
    confidence = models.CharField("confiança", max_length=6, default="baixa",
                                  choices=[("alta", "Alta"), ("media", "Média"), ("baixa", "Baixa")])
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.PROPOSED)
    origin = models.CharField("origem", max_length=12, default="automatica")
    rationale = models.CharField("justificativa", max_length=400, blank=True)
    validated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["school", "source", "target"], name="uniq_skill_relation")]
        verbose_name = "relação entre habilidades"
        verbose_name_plural = "relações entre habilidades"


class LearningAlert(models.Model):
    """Alerta pedagógico precoce, gerado por regra explícita e revisável pelo professor.

    Sinalização exploratória: não é previsão validada, não reprova, não classifica.
    """

    class Status(models.TextChoices):
        NEW = "novo", "Novo"
        REVIEW = "analise", "Em análise"
        ACTION = "intervencao", "Com intervenção"
        DISMISSED = "descartado", "Descartado pelo professor"
        RESOLVED = "resolvido", "Resolvido"

    class Level(models.TextChoices):
        INFO = "atencao", "Atenção"
        HIGH = "importante", "Importante"

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, null=True, blank=True,
                                related_name="learning_alerts")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, null=True, blank=True)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, null=True, blank=True)
    item = models.ForeignKey("curriculum.CurriculumItem", on_delete=models.CASCADE, null=True, blank=True)
    rule = models.CharField("regra", max_length=40)
    level = models.CharField("nível", max_length=10, choices=Level.choices, default=Level.INFO)
    title = models.CharField(max_length=200)
    explanation = models.TextField("por que o alerta foi gerado")
    factors = models.JSONField("fatores", default=list)
    evidence_ids = models.JSONField(default=list)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    method = models.CharField("modelo ou regra", max_length=200)
    uncertainty = models.CharField("incerteza", max_length=200, blank=True)
    limitations = models.TextField("limitações")
    next_action = models.TextField("próxima ação sugerida")
    fingerprint = models.CharField(max_length=120)
    active = models.BooleanField("condição ainda presente", default=True)
    status = models.CharField("situação", max_length=12, choices=Status.choices, default=Status.NEW)
    status_note = models.CharField("registro do professor", max_length=400, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-active", "-level", "-updated_at"]
        constraints = [models.UniqueConstraint(fields=["school", "fingerprint"], name="uniq_alert_fingerprint")]
        verbose_name = "alerta pedagógico"
        verbose_name_plural = "alertas pedagógicos"


class ModelRun(models.Model):
    """Registro de cada treino/validação de modelo preditivo (auditoria e monitoramento)."""

    class Status(models.TextChoices):
        INSUFFICIENT = "insuficiente", "Dados insuficientes — modo exploratório"
        EXPERIMENTAL = "experimental", "Experimental — validado tecnicamente, sem aprovação pedagógica"
        APPROVED = "aprovado", "Aprovado para uso (decisão humana registrada)"
        DISABLED = "desativado", "Desativado"

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    version = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    cutoff = models.DateField("corte temporal treino/teste", null=True, blank=True)
    n_train = models.PositiveIntegerField(default=0)
    n_test = models.PositiveIntegerField(default=0)
    positives = models.PositiveIntegerField(default=0)
    metrics = models.JSONField(default=dict)
    baseline = models.JSONField(default=dict)
    coefficients = models.JSONField(default=dict)
    status = models.CharField(max_length=14, choices=Status.choices)
    notes = models.TextField(blank=True)
    decided_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class InterventionStrategy(models.Model):
    """Estratégia pedagógica do banco de intervenções, com o nível de respaldo declarado."""

    class Evidence(models.TextChoices):
        RESEARCH = "pesquisa", "Com respaldo em pesquisa publicada (não garante efeito em toda turma)"
        PRACTICE = "pratica", "Prática pedagógica recomendada"
        EXPERIMENTAL = "experimental", "Sugestão experimental, a avaliar"

    school = models.ForeignKey(School, on_delete=models.CASCADE, null=True, blank=True)
    title = models.CharField("estratégia", max_length=160)
    component = models.CharField("componente", max_length=80, blank=True, help_text="Vazio: serve a qualquer componente.")
    dimension = models.ForeignKey("curriculum.SkillDimension", on_delete=models.SET_NULL, null=True, blank=True,
                                  verbose_name="dimensão analítica")
    error_types = models.CharField("tipos de erro a que responde", max_length=120, blank=True)
    objective = models.TextField("objetivo")
    procedures = models.TextField("procedimentos")
    materials = models.TextField("materiais", blank=True)
    minutes = models.PositiveSmallIntegerField("tempo estimado (min)", default=30)
    follow_up = models.TextField("critérios de acompanhamento", blank=True)
    expected_evidence = models.TextField("evidência esperada", blank=True)
    evidence_level = models.CharField("respaldo", max_length=12, choices=Evidence.choices)
    references = models.TextField("referências", blank=True)
    stages = models.CharField("etapa e anos", max_length=80, default="Ensino Fundamental")
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        ordering = ["component", "title"]
        verbose_name = "estratégia de intervenção"
        verbose_name_plural = "estratégias de intervenção"

    def __str__(self):
        return self.title


class LearningTrail(models.Model):
    """Trilha de aprendizagem: sequência de intervenções para um estudante ou grupo."""

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    title = models.CharField("trilha", max_length=200)
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    students = models.ManyToManyField("registry.Student", related_name="learning_trails")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class LearningIntervention(models.Model):
    """Intervenção pedagógica planejada pelo professor (aceita, editada ou criada por ele).

    O resultado posterior é calculado das evidências antes e depois do início:
    associação no tempo, não prova de efeito causal.
    """

    class Status(models.TextChoices):
        PROPOSED = "proposta", "Sugerida (aguardando o professor)"
        ACCEPTED = "aceita", "Aceita"
        RUNNING = "andamento", "Em andamento"
        DONE = "concluida", "Concluída"
        REJECTED = "rejeitada", "Rejeitada pelo professor"

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, verbose_name="turma")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    item = models.ForeignKey("curriculum.CurriculumItem", on_delete=models.PROTECT, verbose_name="habilidade a desenvolver")
    students = models.ManyToManyField("registry.Student", related_name="learning_interventions", verbose_name="estudantes")
    strategy = models.ForeignKey(InterventionStrategy, on_delete=models.SET_NULL, null=True, blank=True,
                                 verbose_name="estratégia")
    alert = models.ForeignKey(LearningAlert, on_delete=models.SET_NULL, null=True, blank=True, related_name="interventions")
    trail = models.ForeignKey(LearningTrail, on_delete=models.CASCADE, null=True, blank=True, related_name="steps")
    order = models.PositiveSmallIntegerField(default=1)
    title = models.CharField("título", max_length=200)
    objective = models.TextField("objetivo")
    activity = models.TextField("atividade recomendada")
    complexity = models.PositiveSmallIntegerField("nível de complexidade", default=2,
                                                  choices=[(1, "Básico"), (2, "Intermediário"), (3, "Avançado")])
    materials = models.TextField("materiais necessários", blank=True)
    minutes = models.PositiveSmallIntegerField("tempo estimado (min)", default=30)
    methodology = models.TextField("estratégia metodológica", blank=True)
    criteria = models.TextField("critérios de avaliação", blank=True)
    expected_evidence = models.TextField("evidência esperada", blank=True)
    starts_on = models.DateField("início", default=timezone.localdate)
    review_on = models.DateField("data de revisão")
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.ACCEPTED)
    teacher_note = models.TextField("registro do professor", blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "intervenção pedagógica"
        verbose_name_plural = "intervenções pedagógicas"

"""Conteúdos da prova (Prompt 18 §10).

Um ``ExamGuide`` é a preparação de UMA prova de uma turma e disciplina:
tópicos (com habilidades), materiais (arquivos protegidos, links, vídeos,
leituras), orientações e um histórico de atualizações. Como as atividades de
casa, pertence à turma: o alcance vem das matrículas (``pedagogy.access.reaches``),
nada é copiado por estudante.

O que o estudante registra é dele e tem natureza declarada:
- ``TopicCheck`` é AUTORRELATO ("entendi", "preciso praticar", "tenho
  dúvidas"), nunca evidência de domínio (Dunning, Heath & Suls, 2004);
- ``StudyQuestion`` é uma dúvida endereçada ao professor.

Não há registro de quem abriu qual material: acesso não é estudo, e estudo
declarado não é aprendizagem (§10.9). Ver docs/ESPECIFICACAO_CONTEUDOS_DA_PROVA.md.
"""

from urllib.parse import urlparse

from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.functional import cached_property

from apps.academics.models import ClassGroup, Subject
from apps.core.models import School, User
from apps.core.uploads import validate_attachment
from apps.registry.models import Student

# Plataformas reconhecidas pelo endereço, só para rotular o link.
PLATFORMS = (
    (("youtube.com", "youtu.be"), "YouTube"),
    (("vimeo.com",), "Vimeo"),
    (("khanacademy.org",), "Khan Academy"),
    (("novaescola.org.br",), "Nova Escola"),
    (("gov.br", "mec.gov.br"), "Governo federal"),
    (("se.df.gov.br", "educacao.df.gov.br"), "SEEDF"),
    (("wikipedia.org",), "Wikipédia"),
)


def platform_of(url):
    host = (urlparse(url or "").hostname or "").lower()
    for domains, label in PLATFORMS:
        if any(host == d or host.endswith("." + d) for d in domains):
            return label
    return host.removeprefix("www.")


def study_upload_path(instance, filename):
    from apps.core.uploads import safe_attachment_path

    return "study/" + safe_attachment_path(instance, filename).split("/", 1)[1]


class ExamGuide(models.Model):
    class Status(models.TextChoices):
        DRAFT = "rascunho", "Rascunho"
        PUBLISHED = "publicado", "Publicado"
        ARCHIVED = "arquivado", "Arquivado"

    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name="escola")
    class_group = models.ForeignKey(ClassGroup, on_delete=models.PROTECT, verbose_name="turma")
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, verbose_name="disciplina")
    evaluation = models.ForeignKey(
        "pedagogy.Evaluation", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="study_guides", verbose_name="avaliação",
        help_text="Opcional. Com avaliação, a data da prova acompanha a dela.",
    )
    title = models.CharField("título", max_length=200)
    exam_date = models.DateField("data da prova")
    description = models.TextField("o que o estudante precisa aprender", blank=True)
    guidance = models.TextField("orientações de estudo", blank=True)
    criteria = models.TextField("critérios de avaliação", blank=True)
    prep_time = models.CharField(
        "tempo sugerido de estudo", max_length=120, blank=True,
        help_text="Opcional, só com justificativa (ex.: “20 minutos por dia na semana da prova”).",
    )
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.DRAFT)
    published_date = models.DateField("visível a partir de", default=timezone.localdate)
    available_until = models.DateField("visível até", null=True, blank=True)
    curriculum = models.ManyToManyField(
        "curriculum.CurriculumItem", blank=True, related_name="study_guides",
        verbose_name="habilidades e objetivos curriculares",
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notified_at = models.DateTimeField(null=True, blank=True, editable=False)
    # Controle de edição simultânea: quem salva com versão antiga é avisado.
    version = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["-exam_date", "-pk"]
        indexes = [models.Index(fields=["school", "class_group", "status", "exam_date"])]
        verbose_name = "conteúdos da prova"
        verbose_name_plural = "conteúdos das provas"

    def __str__(self):
        return f"{self.title} — {self.class_group}"

    # Compatível com pedagogy.access.reaches (usa published_date e deadline).
    @property
    def deadline(self):
        return self.exam_date

    @classmethod
    def family_visible_q(cls, today=None):
        today = today or timezone.localdate()
        return Q(status=cls.Status.PUBLISHED, published_date__lte=today) & (
            Q(available_until__isnull=True) | Q(available_until__gte=today))

    @property
    def is_visible_to_family(self):
        today = timezone.localdate()
        return (self.status == self.Status.PUBLISHED and self.published_date <= today
                and (self.available_until is None or self.available_until >= today))

    @property
    def is_past(self):
        return self.exam_date < timezone.localdate()

    @cached_property
    def active_materials(self):
        """Materiais em uso (sem os retirados), com as habilidades já carregadas."""
        return list(self.materials.filter(removed_at__isnull=True).select_related("topic")
                    .prefetch_related("curriculum"))


class ExamTopic(models.Model):
    class Priority(models.TextChoices):
        HIGH = "alta", "Alta"
        MEDIUM = "media", "Média"
        LOW = "baixa", "Baixa"

    PRIORITY_ORDER = {"alta": 0, "media": 1, "baixa": 2}

    class Level(models.TextChoices):
        NONE = "", "Não informado"
        BASIC = "basico", "Básico"
        INTERMEDIATE = "intermediario", "Intermediário"
        ADVANCED = "avancado", "Avançado"

    guide = models.ForeignKey(ExamGuide, on_delete=models.CASCADE, related_name="topics", verbose_name="prova")
    title = models.CharField("tópico", max_length=200)
    description = models.TextField("o que estudar neste tópico", blank=True)
    priority = models.CharField("prioridade", max_length=6, choices=Priority.choices, default=Priority.MEDIUM)
    level = models.CharField("nível", max_length=14, choices=Level.choices, blank=True, default="")
    prerequisite_notes = models.TextField(
        "pré-requisitos (o que é bom saber antes)", blank=True,
        help_text="Os pré-requisitos cadastrados no grafo de habilidades já aparecem sozinhos.",
    )
    curriculum = models.ManyToManyField(
        "curriculum.CurriculumItem", blank=True, related_name="exam_topics",
        verbose_name="habilidades e objetivos curriculares",
    )
    order = models.PositiveSmallIntegerField("ordem", default=0)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "tópico da prova"
        verbose_name_plural = "tópicos da prova"

    def __str__(self):
        return self.title


class StudyMaterial(models.Model):
    class Kind(models.TextChoices):
        FILE = "arquivo", "Arquivo (PDF, documento, apresentação, imagem)"
        LINK = "link", "Link para página educacional"
        VIDEO = "video", "Vídeo"
        READING = "leitura", "Livro ou leitura (bibliografia)"
        EXERCISES = "exercicios", "Lista de exercícios"
        EXAMPLE = "exemplo", "Exemplo resolvido"
        SUMMARY = "resumo", "Resumo ou mapa conceitual"
        GUIDE = "roteiro", "Roteiro de estudo"

    class Access(models.TextChoices):
        NONE = "", "Não informado"
        FREE = "livre", "Acesso livre (link conferido)"
        SCHOOL = "institucional", "Disponível na escola (biblioteca, sala de leitura)"
        PRINT = "fisico", "Livro físico (o estudante precisa ter acesso)"

    guide = models.ForeignKey(ExamGuide, on_delete=models.CASCADE, related_name="materials", verbose_name="prova")
    topic = models.ForeignKey(ExamTopic, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="materials", verbose_name="tópico")
    kind = models.CharField("tipo", max_length=10, choices=Kind.choices, default=Kind.FILE)
    title = models.CharField("título", max_length=200)
    description = models.TextField("descrição ou texto", blank=True)
    why = models.CharField("por que este material", max_length=300, blank=True,
                           help_text="Aparece ao estudante: o que ele ganha estudando isto.")
    file = models.FileField("arquivo", upload_to=study_upload_path, blank=True, validators=[validate_attachment])
    original_name = models.CharField(max_length=255, blank=True)
    url = models.URLField("endereço (link)", max_length=500, blank=True)
    platform = models.CharField("plataforma", max_length=80, blank=True)
    author = models.CharField("autor, canal ou instituição", max_length=200, blank=True)
    duration = models.CharField("duração", max_length=40, blank=True,
                                help_text="Só se você conferiu (ex.: 8 min).")
    segment = models.CharField("trecho importante", max_length=120, blank=True,
                               help_text="Ex.: de 2:10 a 5:30.")
    guiding_questions = models.TextField("perguntas para guiar o estudo", blank=True)
    follow_up = models.TextField("o que fazer depois", blank=True)
    accessibility = models.CharField("acessibilidade (legendas, transcrição, alternativa)", max_length=300,
                                     blank=True)
    publisher = models.CharField("editora ou fonte", max_length=200, blank=True)
    edition_year = models.CharField("edição ou ano", max_length=40, blank=True)
    pages = models.CharField("capítulo ou páginas", max_length=80, blank=True)
    access_type = models.CharField("tipo de acesso", max_length=14, choices=Access.choices, blank=True, default="")
    alternative = models.CharField("alternativa para quem não tem o material", max_length=300, blank=True)
    curriculum = models.ManyToManyField(
        "curriculum.CurriculumItem", blank=True, related_name="study_materials",
        verbose_name="habilidades relacionadas",
    )
    order = models.PositiveSmallIntegerField("ordem", default=0)
    # Biblioteca da escola (Prompt 9 §8.7): colegas encontram e reaproveitam.
    shared = models.BooleanField("compartilhar na biblioteca da escola", default=False,
                                 help_text="Professores, coordenação e direção da escola poderão usar este material.")
    tags = models.CharField("etiquetas", max_length=200, blank=True,
                            help_text="Separadas por vírgula. Ex.: frações, revisão, 6º ano.")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    # Remoção lógica: o histórico guarda o que foi tirado ou trocado.
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    replaced_by = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    broken_reports = models.PositiveSmallIntegerField("avisos de link que não abre", default=0)
    broken_reported_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "material de estudo"
        verbose_name_plural = "materiais de estudo"

    def __str__(self):
        return self.title

    @property
    def is_external(self):
        return bool(self.url)

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class LibraryFavorite(models.Model):
    """Material da biblioteca marcado como favorito por um profissional."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="library_favorites")
    material = models.ForeignKey(StudyMaterial, on_delete=models.CASCADE, related_name="favorites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "material"], name="uniq_library_favorite")]


class GuideUpdate(models.Model):
    """O que mudou desde a publicação, na linguagem do estudante."""

    class Kind(models.TextChoices):
        PUBLISHED = "publicado", "Publicado"
        DATE = "data", "Data da prova alterada"
        MATERIAL_ADDED = "material_incluido", "Material incluído"
        MATERIAL_REMOVED = "material_removido", "Material retirado"
        MATERIAL_REPLACED = "material_trocado", "Material substituído"
        TOPIC = "topico", "Tópicos alterados"
        EDITED = "editado", "Orientações alteradas"

    guide = models.ForeignKey(ExamGuide, on_delete=models.CASCADE, related_name="updates")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    text = models.CharField(max_length=300)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]


class TopicCheck(models.Model):
    """Autorrelato do estudante sobre um tópico. Não é evidência de domínio."""

    class Status(models.TextChoices):
        UNDERSTOOD = "entendi", "Entendi"
        PRACTICE = "praticar", "Preciso praticar"
        DOUBT = "duvida", "Ainda tenho dúvidas"

    topic = models.ForeignKey(ExamTopic, on_delete=models.CASCADE, related_name="checks")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="topic_checks")
    status = models.CharField(max_length=10, choices=Status.choices)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["topic", "student"], name="uniq_topic_check")]


class StudyQuestion(models.Model):
    """Dúvida do estudante para o professor, sobre a prova ou um tópico."""

    guide = models.ForeignKey(ExamGuide, on_delete=models.CASCADE, related_name="questions")
    topic = models.ForeignKey(ExamTopic, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="study_questions")
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    text = models.TextField("dúvida", max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)
    answer = models.TextField("resposta", blank=True)
    answered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_open(self):
        return not self.answer


class PracticeQuestion(models.Model):
    """Exercício de prática com correção automática (Prompt 18 §10.8).

    É escrito pelo professor AQUI, para preparação: não é questão da prova
    (``cognitio.Question``) e o gabarito aparece ao estudante depois que ele
    responde. Por isso não vira evidência de domínio: o estudante pode tentar
    de novo e consultar a explicação. O professor vê quantos acertaram na
    primeira tentativa, para saber o que retomar.
    """

    guide = models.ForeignKey(ExamGuide, on_delete=models.CASCADE, related_name="practice", verbose_name="prova")
    topic = models.ForeignKey(ExamTopic, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="practice", verbose_name="tópico")
    statement = models.TextField("enunciado")
    options = models.JSONField("alternativas", default=list)
    correct = models.PositiveSmallIntegerField("alternativa correta")  # índice em ``options``
    explanation = models.TextField(
        "explicação", blank=True,
        help_text="Aparece depois da resposta, certa ou errada: por que a correta é a correta.")
    curriculum = models.ManyToManyField("curriculum.CurriculumItem", blank=True, related_name="practice_questions",
                                        verbose_name="habilidades")
    order = models.PositiveSmallIntegerField("ordem", default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "exercício de prática"
        verbose_name_plural = "exercícios de prática"

    def __str__(self):
        return self.statement[:60]


class PracticeAttempt(models.Model):
    """Uma resposta do estudante a um exercício de prática. Várias tentativas ficam guardadas."""

    question = models.ForeignKey(PracticeQuestion, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="practice_attempts")
    chosen = models.PositiveSmallIntegerField()
    is_correct = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["question", "student", "created_at"])]

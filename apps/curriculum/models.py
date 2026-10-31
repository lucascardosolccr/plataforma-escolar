"""Itens curriculares, evidências de aprendizagem da turma e referências normativas.

Origem dos dados (ver ``docs/INTEGRACAO_BNCC_LDB_CURRICULO_DF.md``):

- competências gerais e habilidades do Ensino Fundamental vêm do texto do
  PDF oficial da BNCC (MEC, versão final de 2018), extraído sem reescrita e
  carregado pela migração ``0002``. São itens comuns a todas as escolas
  (``school`` vazio).
- objetivos e conteúdos do Currículo em Movimento do DF, e objetivos
  próprios, são cadastrados ou importados pela escola (``school``
  preenchido), com a fonte de cada linha.
"""

import re

from django.db import models
from django.db.models import Q

from apps.academics.models import ClassGroup, Subject
from apps.core.models import School, User


class CurriculumItem(models.Model):
    class Kind(models.TextChoices):
        GENERAL = "competencia_geral", "Competência geral (BNCC)"
        SKILL = "habilidade", "Habilidade (BNCC)"
        DF_OBJECTIVE = "objetivo_df", "Objetivo de aprendizagem (Currículo em Movimento do DF)"
        DF_CONTENT = "conteudo_df", "Conteúdo (Currículo em Movimento do DF)"
        OWN = "proprio", "Objetivo próprio da escola"

    school = models.ForeignKey(School, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="curriculum_items",
                               help_text="Vazio: referência nacional comum a todas as escolas.")
    kind = models.CharField("tipo", max_length=20, choices=Kind.choices)
    code = models.CharField("código", max_length=30)
    text = models.TextField("texto")
    stage = models.CharField("etapa", max_length=40, default="Ensino Fundamental")
    component = models.CharField("componente curricular", max_length=80, blank=True)
    years = models.CharField("anos", max_length=40, blank=True, help_text="Ex.: 6 ou 6,7")
    bncc = models.ManyToManyField("self", symmetrical=False, blank=True, related_name="local_items",
                                  verbose_name="habilidades da BNCC relacionadas")
    source = models.CharField("fonte", max_length=250)
    source_url = models.URLField("endereço da fonte", blank=True)
    verified_on = models.DateField("conferido em", null=True, blank=True)
    needs_review = models.BooleanField("texto a conferir", default=False,
                                       help_text="A extração automática não garantiu o texto completo.")
    active = models.BooleanField("ativo", default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "code"]
        indexes = [models.Index(fields=["component", "kind"]), models.Index(fields=["code"])]
        constraints = [models.UniqueConstraint(fields=["school", "kind", "code"], name="uniq_curriculum_code")]
        verbose_name = "item curricular"
        verbose_name_plural = "itens curriculares"

    def __str__(self):
        return f"{self.code} — {self.text[:80]}"

    @property
    def year_list(self):
        return [int(y) for y in self.years.split(",") if y.strip().isdigit()]

    @property
    def is_local(self):
        return self.school_id is not None

    @classmethod
    def visible_q(cls, school):
        """Itens nacionais e os da própria escola."""
        return Q(school__isnull=True) | Q(school=school)

    @classmethod
    def for_pair(cls, school, component, year):
        """Habilidades e objetivos do componente e do ano (sem as competências gerais)."""
        qs = cls.objects.filter(cls.visible_q(school), active=True, component=component).exclude(
            kind=cls.Kind.GENERAL)
        if year:
            ids = [i.pk for i in qs if year in i.year_list or not i.year_list]
            qs = qs.filter(pk__in=ids)
        return qs


COMPONENTS = ["Língua Portuguesa", "Matemática", "Ciências", "Geografia", "História", "Arte", "Educação Física",
              "Língua Inglesa", "Ensino Religioso"]
_ALIASES = {
    "portugues": "Língua Portuguesa", "lingua portuguesa": "Língua Portuguesa",
    "matematica": "Matemática", "ciencias": "Ciências", "geografia": "Geografia",
    "historia": "História", "arte": "Arte", "artes": "Arte", "educacao fisica": "Educação Física",
    "ingles": "Língua Inglesa", "lingua inglesa": "Língua Inglesa", "ensino religioso": "Ensino Religioso",
}


def _plain(text):
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn").strip()


def component_for(subject):
    """Componente da BNCC de uma disciplina: o informado no cadastro ou o
    deduzido pelo nome ("Matemática" → Matemática). ``""`` se não houver."""
    if getattr(subject, "curriculum_component", ""):
        return subject.curriculum_component
    name = _plain(subject.name)
    if name in _ALIASES:
        return _ALIASES[name]
    for alias, comp in _ALIASES.items():
        if name.startswith(alias):
            return comp
    return ""


def year_for(class_group):
    """Ano do Ensino Fundamental pela série ou pelo nome da turma ("6º Ano A" → 6)."""
    for text in (class_group.grade, class_group.name):
        m = re.search(r"(\d)\s*[ºo°]?\s*ano", _plain(text or ""))
        if m:
            return int(m.group(1))
    return None


class LearningEvidence(models.Model):
    """Evidência de aprendizagem registrada pelo professor para a TURMA.

    É um registro de reflexão pedagógica sobre a turma, não uma nota nem uma
    classificação individual de estudante.
    """

    class Judgement(models.TextChoices):
        CONSOLIDATED = "consolidada", "Consolidada pela maioria da turma"
        DEVELOPING = "desenvolvimento", "Em desenvolvimento"
        RETAKE = "retomada", "Precisa de retomada"

    school = models.ForeignKey(School, on_delete=models.CASCADE)
    class_group = models.ForeignKey(ClassGroup, on_delete=models.CASCADE, verbose_name="turma")
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, verbose_name="disciplina")
    item = models.ForeignKey(CurriculumItem, on_delete=models.PROTECT, verbose_name="habilidade ou objetivo")
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="learning_evidence",
                                verbose_name="registrada por")
    observed_on = models.DateField("data")
    judgement = models.CharField("situação da turma", max_length=20, choices=Judgement.choices)
    description = models.TextField("o que foi observado",
                                   help_text="Produções, falas, resultados da atividade ou da avaliação.")
    activity = models.ForeignKey("pedagogy.Activity", on_delete=models.SET_NULL, null=True, blank=True,
                                 verbose_name="atividade relacionada")
    evaluation = models.ForeignKey("pedagogy.Evaluation", on_delete=models.SET_NULL, null=True, blank=True,
                                   verbose_name="avaliação relacionada")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observed_on", "-created_at"]
        indexes = [models.Index(fields=["class_group", "subject"])]
        verbose_name = "evidência de aprendizagem"
        verbose_name_plural = "evidências de aprendizagem"


class NormativeReference(models.Model):
    """Norma ou documento de referência, com a natureza da exigência.

    ``nature`` separa o que é obrigação legal do que é orientação curricular
    ou boa prática: a plataforma não transforma recomendação em obrigação.
    """

    class Nature(models.TextChoices):
        LAW = "legal", "Exigência legal"
        REGULATION = "regulamento", "Regulamentação (decreto, portaria, resolução)"
        CURRICULUM = "curricular", "Orientação curricular"
        GUIDANCE = "orientacao", "Orientação técnica"
        PRACTICE = "boa_pratica", "Boa prática"

    class Validity(models.TextChoices):
        IN_FORCE = "vigente", "Vigente"
        AMENDED = "alterada", "Vigente, com alterações"
        TO_CHECK = "a_verificar", "Vigência a verificar"
        REVOKED = "revogada", "Revogada"

    name = models.CharField("norma ou documento", max_length=200)
    authority = models.CharField("órgão responsável", max_length=120)
    provision = models.CharField("dispositivo", max_length=200, blank=True)
    excerpt = models.TextField("trecho ou síntese", blank=True)
    excerpt_is_literal = models.BooleanField("trecho literal", default=False)
    topic = models.CharField("assunto", max_length=120)
    stage = models.CharField("etapa", max_length=120, default="Educação básica")
    nature = models.CharField("natureza", max_length=12, choices=Nature.choices)
    validity = models.CharField("vigência", max_length=12, choices=Validity.choices, default=Validity.TO_CHECK)
    url = models.URLField("fonte oficial", max_length=300)
    verified_on = models.DateField("última verificação", null=True, blank=True)
    platform_use = models.TextField("como a plataforma aplica", blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name", "provision"]
        verbose_name = "referência normativa"
        verbose_name_plural = "referências normativas"

    def __str__(self):
        return f"{self.name} — {self.provision}" if self.provision else self.name

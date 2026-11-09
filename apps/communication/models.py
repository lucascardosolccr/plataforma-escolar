from django.db import models
from django.utils import timezone

from apps.core.models import School, User
from apps.core.params import digits
from apps.core.uploads import safe_message_attachment_path, validate_attachment


class Notification(models.Model):
    """Notificação interna da central de comunicação. 100% dentro da plataforma,
    sem depender de serviços externos (requisito seção 10 do Prompt 1)."""

    class Kind(models.TextChoices):
        EVALUATION = "avaliacao", "Avaliação/nota publicada"
        ACTIVITY = "atividade", "Atividade/prazo"
        ANNOUNCEMENT = "comunicado", "Comunicado da escola"
        JUSTIFICATION = "justificativa", "Justificativa de falta"
        MESSAGE = "mensagem", "Nova mensagem"
        REQUEST = "solicitacao", "Solicitação"
        ATTENDANCE = "frequencia", "Frequência/pendência"
        OCCURRENCE = "ocorrencia", "Ocorrência registrada"
        LINK = "vinculo", "Vínculo analisado"
        REGISTRATION = "cadastro", "Cadastro de estudante"
        PRINT = "impressao", "Impressão de atividade"
        MENU = "cardapio", "Cardápio"
        CALENDAR = "calendario", "Calendário escolar"
        OBSERVATION = "observacao", "Observação pedagógica"
        GRADE = "nota", "Nota lançada ou alterada"
        PHOTO = "foto", "Fotografia pendente"
        PLANNING = "planejamento", "Planejamento docente"
        EXAM = "prova", "Prova ou avaliação marcada"
        SUPPORT = "apoio", "Apoio à inclusão"
        MEETING = "reuniao", "Reunião ou atendimento"
        EIA = "eia", "Resumo semanal de sinais do EIA-Cognitio"
        GATE = "portaria", "Entrada e saída na escola"

    class Priority(models.TextChoices):
        NORMAL = "normal", "Informativo"
        HIGH = "importante", "Importante"

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="notifications", verbose_name="escola"
    )
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications", verbose_name="destinatário"
    )
    kind = models.CharField(
        "tipo", max_length=15, choices=Kind.choices, default=Kind.ANNOUNCEMENT
    )
    title = models.CharField("título", max_length=200)
    body = models.TextField("texto", blank=True)
    url = models.CharField("destino", max_length=300, blank=True)
    # Estudante a que o aviso se refere (filtro "por filho" da central).
    student = models.ForeignKey(
        "registry.Student", on_delete=models.CASCADE, null=True, blank=True,
        related_name="notifications", verbose_name="estudante",
    )
    # Chave de evento: o mesmo evento não gera dois avisos à mesma pessoa.
    dedupe_key = models.CharField("chave do evento", max_length=120, blank=True, db_index=True)
    priority = models.CharField("prioridade", max_length=10, choices=Priority.choices, default=Priority.NORMAL)
    # Compromisso a que o aviso se refere ("atividade:12", "avaliacao:5"):
    # permite marcar como resolvidos os lembretes quando a entrega é
    # registrada, a atividade é cancelada ou a data muda.
    ref = models.CharField("compromisso", max_length=40, blank=True, db_index=True)
    due_on = models.DateField("data do compromisso", null=True, blank=True)
    resolved_at = models.DateTimeField("resolvida em", null=True, blank=True)
    resolution = models.CharField("como foi resolvida", max_length=80, blank=True)
    is_read = models.BooleanField("lida", default=False)
    read_at = models.DateTimeField("lida em", null=True, blank=True)
    created_at = models.DateTimeField("criada em", auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "is_read"])]
        verbose_name = "notificação"
        verbose_name_plural = "notificações"

    def __str__(self):
        return f"[{self.get_kind_display()}] {self.title} → {self.user}"

    def state(self, today=None):
        """(código, rótulo) do compromisso: resolvido, vencido ou a vencer."""
        if self.resolved_at:
            return "resolvida", self.resolution or "Resolvido"
        if self.due_on:
            today = today or timezone.localdate()
            if self.due_on < today:
                return "vencida", "Data passada"
            if self.due_on == today:
                return "hoje", "É hoje"
            return "futura", f"Para {self.due_on:%d/%m}"
        return "", ""

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])


class Thread(models.Model):
    """Conversa entre um responsável e um profissional autorizado.

    A permissão de participar é validada no servidor (apps/communication/access.py):
    toda conversa tem exatamente um responsável e um profissional da mesma escola.
    """

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="threads", verbose_name="escola"
    )
    student = models.ForeignKey(
        "registry.Student",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="threads",
        verbose_name="estudante (assunto)",
    )
    title = models.CharField("assunto", max_length=200)
    participants = models.ManyToManyField(User, related_name="threads", verbose_name="participantes")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="threads_created"
    )
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "conversa"
        verbose_name_plural = "conversas"

    def __str__(self):
        return f"{self.title} ({', '.join(p.username for p in self.participants.all())})"


class Message(models.Model):
    """Mensagem dentro de uma conversa, com confirmação de leitura (read_at)."""

    thread = models.ForeignKey(
        Thread, on_delete=models.CASCADE, related_name="messages", verbose_name="conversa"
    )
    sender = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="messages_sent", verbose_name="remetente"
    )
    body = models.TextField("mensagem")
    # Um anexo por mensagem (Prompt 15 §6.3). Só é baixado pela view que confere
    # a participação na conversa; o nome no disco é aleatório.
    attachment = models.FileField(
        "anexo", upload_to=safe_message_attachment_path, validators=[validate_attachment], blank=True
    )
    attachment_name = models.CharField("nome do anexo", max_length=255, blank=True)
    created_at = models.DateTimeField("enviada em", auto_now_add=True)
    read_at = models.DateTimeField("lida em", null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        verbose_name = "mensagem"
        verbose_name_plural = "mensagens"

    def __str__(self):
        return f"{self.sender} → {self.thread}: {self.body[:40]}"


class Announcement(models.Model):
    """Comunicado da escola: institucional, por turma ou individual.

    A visibilidade por perfil é calculada no servidor combinando `scope`
    (institucional/turma/individual) e `audience` (família/equipe/todos).
    """

    class Scope(models.TextChoices):
        INSTITUCIONAL = "institucional", "Institucional"
        TURMA = "turma", "Por turma"
        INDIVIDUAL = "individual", "Individual"

    class Audience(models.TextChoices):
        FAMILIA = "familia", "Famílias"
        EQUIPE = "equipe", "Equipe escolar"
        TODOS = "todos", "Todos"

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="announcements", verbose_name="escola"
    )
    scope = models.CharField(
        "abrangência", max_length=15, choices=Scope.choices, default=Scope.INSTITUCIONAL
    )
    audience = models.CharField(
        "público", max_length=10, choices=Audience.choices, default=Audience.FAMILIA
    )
    class_group = models.ForeignKey(
        "academics.ClassGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="announcements",
        verbose_name="turma",
    )
    student = models.ForeignKey(
        "registry.Student",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="announcements",
        verbose_name="estudante",
    )
    title = models.CharField("título", max_length=200)
    body = models.TextField("texto")
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="announcements_created"
    )
    created_at = models.DateTimeField("criado em", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["school", "scope", "audience"])]
        verbose_name = "comunicado"
        verbose_name_plural = "comunicados"

    def __str__(self):
        return f"{self.title} ({self.get_scope_display()})"

    def is_read_by(self, user):
        return self.reads.filter(user=user).exists()


class AnnouncementRead(models.Model):
    """Confirmação de leitura de um comunicado por um usuário."""

    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name="reads", verbose_name="comunicado"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, verbose_name="usuário")
    read_at = models.DateTimeField("lida em", auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["announcement", "user"], name="uniq_announcement_read"
            )
        ]
        verbose_name = "confirmação de leitura"
        verbose_name_plural = "confirmações de leitura"


class ServiceRequest(models.Model):
    """Solicitação da família com status de atendimento (histórico auditado).

    O responsável acompanha o andamento; a secretaria (e a gestão) analisa e
    responde. Os estados seguem o requisito da seção 5 do Prompt 1.
    """

    class Category(models.TextChoices):
        CADASTRO = "cadastro", "Atualização cadastral"
        DOCUMENTO = "documento", "Documento/atestado"
        MATRICULA = "matricula", "Matrícula/transferência"
        DUVIDA = "duvida", "Dúvida"
        CONTATO = "contato", "Solicitar reunião/contato"
        LGPD = "lgpd", "Dados pessoais (LGPD)"
        OUTRO = "outro", "Outro"

    class DataRight(models.TextChoices):
        """Direitos do titular (LGPD, art. 18). Para criança e adolescente, quem pede é o responsável."""

        CONFIRM = "confirmacao", "Confirmar se a escola trata os dados (art. 18, I)"
        ACCESS = "acesso", "Receber os dados que a escola guarda (art. 18, II)"
        CORRECT = "correcao", "Corrigir dados incompletos, inexatos ou desatualizados (art. 18, III)"
        ERASE = "eliminacao", "Anonimizar, bloquear ou eliminar dados (art. 18, IV e VI)"
        PORTABILITY = "portabilidade", "Levar os dados a outra instituição (art. 18, V)"
        SHARING = "compartilhamento", "Saber com quem os dados são compartilhados (art. 18, VII)"
        CONSENT = "consentimento", "Consentimento: consequências de negar ou revogar (art. 18, VIII e IX)"

    LGPD_DAYS = 15  # art. 19, II: declaração completa em até 15 dias do requerimento (acesso e confirmação)

    class Status(models.TextChoices):
        RECEIVED = "recebida", "Recebida"
        UNDER_REVIEW = "em_analise", "Em análise"
        APPROVED = "aprovada", "Aprovada"
        REJECTED = "recusada", "Recusada"
        RESPONDED = "respondida", "Respondida"
        DONE = "concluida", "Concluída"

    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="service_requests", verbose_name="escola"
    )
    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="service_requests",
        verbose_name="solicitante",
    )
    student = models.ForeignKey(
        "registry.Student",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="service_requests",
        verbose_name="estudante",
    )
    category = models.CharField(
        "categoria", max_length=15, choices=Category.choices, default=Category.OUTRO
    )
    data_right = models.CharField("direito pedido (LGPD)", max_length=20, choices=DataRight.choices, blank=True)
    title = models.CharField("assunto", max_length=200)
    description = models.TextField("detalhes")
    status = models.CharField(
        "situação", max_length=12, choices=Status.choices, default=Status.RECEIVED
    )
    response = models.TextField("resposta da equipe", blank=True)
    responded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="requests_responded"
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField("criada em", auto_now_add=True)
    updated_at = models.DateTimeField("atualizada em", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["school", "status"])]
        verbose_name = "solicitação"
        verbose_name_plural = "solicitações"

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def is_lgpd(self):
        return self.category == self.Category.LGPD

    @property
    def due_on(self):
        """Prazo de referência do pedido sobre dados pessoais (15 dias corridos do pedido)."""
        from datetime import timedelta

        from django.utils import timezone

        if not self.is_lgpd or not self.created_at:
            return None
        return timezone.localdate(self.created_at) + timedelta(days=self.LGPD_DAYS)

    @property
    def overdue(self):
        from django.utils import timezone

        return bool(self.due_on and self.status in (self.Status.RECEIVED, self.Status.UNDER_REVIEW)
                    and timezone.localdate() > self.due_on)

class NotificationRule(models.Model):
    """Liga ou desliga um tipo de aviso automático para a escola inteira.

    Sem linha para o evento, vale o padrão de ``family_events.EVENTS``.
    Configurado pela direção e pela administração.
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="notification_rules")
    event = models.CharField("evento", max_length=40)
    enabled = models.BooleanField("ativo", default=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "regra de notificação"
        verbose_name_plural = "regras de notificação"
        constraints = [models.UniqueConstraint(fields=["school", "event"], name="uniq_rule_per_event")]


class NotificationMute(models.Model):
    """Tipo de aviso que a própria pessoa preferiu não receber."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification_mutes")
    kind = models.CharField("tipo", max_length=15)

    class Meta:
        verbose_name = "preferência de notificação"
        verbose_name_plural = "preferências de notificação"
        constraints = [models.UniqueConstraint(fields=["user", "kind"], name="uniq_mute_per_kind")]


class ReminderPolicy(models.Model):
    """Antecedência dos lembretes automáticos, definida pela escola.

    Os números são dias em relação à data do compromisso: ``7,3,1,0`` avisa
    sete dias antes, três, na véspera e no dia. ``overdue_days`` são dias
    depois do vencimento, enquanto a atividade continuar pendente.
    """

    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name="reminder_policy")
    activity_days = models.CharField("atividades e trabalhos: dias antes da entrega", max_length=40,
                                     default="3,1,0")
    overdue_days = models.CharField("atividades pendentes: dias depois do vencimento", max_length=40,
                                    default="1", blank=True)
    exam_days = models.CharField("provas: dias antes da data", max_length=40, default="7,1,0")
    include_guardians = models.BooleanField(
        "avisar também os responsáveis", default=True,
        help_text="Desligado, os lembretes vão só para o estudante com acesso. Estudante sem acesso "
                  "continua com os lembretes enviados aos responsáveis.")
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "antecedência dos lembretes"
        verbose_name_plural = "antecedências dos lembretes"

    @staticmethod
    def parse(text, limit=60):
        """``"7, 3,1"`` → ``[7, 3, 1]`` (sem repetição, do maior para o menor)."""
        days = set()
        for part in (text or "").replace(";", ",").split(","):
            part = part.strip()
            if digits(part) and int(part) <= limit:
                days.add(int(part))
        return sorted(days, reverse=True)

    @classmethod
    def for_school(cls, school):
        return cls.objects.filter(school=school).first() or cls(school=school)


class ReminderRun(models.Model):
    """Registro de cada processamento diário dos lembretes.

    Sem agendador, o processamento roda na primeira requisição do dia. Uma
    execução com erro fica registrada e é tentada de novo mais tarde; como
    cada aviso tem chave de evento, repetir nunca duplica aviso.
    """

    class Status(models.TextChoices):
        RUNNING = "processando", "Processando"
        OK = "ok", "Concluído"
        ERROR = "erro", "Falhou"

    day = models.DateField("dia de referência", db_index=True)
    started_at = models.DateTimeField("início", auto_now_add=True)
    finished_at = models.DateTimeField("fim", null=True, blank=True)
    status = models.CharField("situação", max_length=12, choices=Status.choices, default=Status.RUNNING)
    sent = models.PositiveIntegerField("avisos criados", default=0)
    detail = models.TextField("detalhes", blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "processamento de lembretes"
        verbose_name_plural = "processamentos de lembretes"


class Authorization(models.Model):
    """Autorização da família para passeio ou atividade fora da rotina (substitui o bilhete de papel).

    A equipe cria para uma ou mais turmas; cada responsável com vínculo aprovado responde por filho até o
    prazo. A escola acompanha quem autorizou, quem não autorizou e quem não respondeu, e imprime a lista
    de autorizados para levar no dia. Nada é apagado: cancelar exige motivo e avisa as famílias.
    """

    class Status(models.TextChoices):
        OPEN = "aberta", "Aberta"
        CLOSED = "encerrada", "Encerrada"
        CANCELED = "cancelada", "Cancelada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="authorizations")
    title = models.CharField("atividade", max_length=200)
    description = models.TextField("detalhes para a família",
                                   help_text="Local, horário de saída e de volta, transporte, o que levar, contato.")
    event_date = models.DateField("data da atividade")
    deadline = models.DateField("responder até")
    class_groups = models.ManyToManyField("academics.ClassGroup", related_name="authorizations",
                                          verbose_name="turmas")
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.OPEN)
    cancel_reason = models.CharField("motivo do cancelamento", max_length=300, blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="authorizations_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_date", "-pk"]
        verbose_name = "autorização"
        verbose_name_plural = "autorizações"

    def __str__(self):
        return self.title

    def accepts_answers(self, today=None):
        return self.status == self.Status.OPEN and (today or timezone.localdate()) <= self.deadline

    def document_text(self):
        """O texto que a família assina: muda qualquer parte, muda o resumo, e as assinaturas anteriores deixam
        de valer para a versão nova."""
        classes = ", ".join(sorted(c.name for c in self.class_groups.all()))
        return (f"{self.school.name}\nAutorização: {self.title}\nTurmas: {classes}\n"
                f"Data da atividade: {self.event_date:%d/%m/%Y}\nResponder até: {self.deadline:%d/%m/%Y}\n\n"
                f"{self.description.strip()}")

    def document_hash(self):
        import hashlib

        return hashlib.sha256(self.document_text().encode("utf-8")).hexdigest()


class AuthorizationResponse(models.Model):
    """Resposta de um responsável por um estudante (a última vale; o histórico fica na auditoria)."""

    class Answer(models.TextChoices):
        YES = "autorizo", "Autorizo"
        NO = "nao_autorizo", "Não autorizo"

    authorization = models.ForeignKey(Authorization, on_delete=models.CASCADE, related_name="responses")
    student = models.ForeignKey("registry.Student", on_delete=models.CASCADE, related_name="authorization_responses")
    answer = models.CharField("resposta", max_length=12, choices=Answer.choices)
    note = models.CharField("observação para a escola", max_length=300, blank=True,
                            help_text="Ex.: cuidados, quem busca, restrição alimentar para o lanche do passeio.")
    answered_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="+")
    answered_at = models.DateTimeField(auto_now=True)
    # Assinatura que deu origem a esta resposta. Respostas de antes da assinatura eletrônica ficam sem ela.
    signature = models.ForeignKey("AuthorizationSignature", on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["authorization", "student"], name="uniq_authorization_student")]
        verbose_name = "resposta de autorização"
        verbose_name_plural = "respostas de autorização"


class AuthorizationSignature(models.Model):
    """Assinatura eletrônica de uma resposta (nunca alterada nem apagada; mudar de ideia gera outra).

    Cada assinatura guarda o resumo (SHA-256) do texto que o responsável viu, o resumo da assinatura anterior
    da mesma autorização (encadeamento) e um selo HMAC calculado com a chave secreta do servidor sobre tudo isso.
    Mudar qualquer campo no banco, apagar ou inserir uma assinatura no meio, ou alterar o texto da autorização
    depois de assinada aparece na conferência (``communication.signatures.verify``).
    """

    authorization = models.ForeignKey(Authorization, on_delete=models.PROTECT, related_name="signatures")
    student = models.ForeignKey("registry.Student", on_delete=models.PROTECT, related_name="authorization_signatures")
    answer = models.CharField("resposta", max_length=12, choices=AuthorizationResponse.Answer.choices)
    note = models.CharField("observação para a escola", max_length=300, blank=True)
    signer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="+")
    signer_name = models.CharField("nome digitado por quem assinou", max_length=150)
    signed_at = models.DateTimeField("assinada em")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=200, blank=True)
    document = models.TextField("texto assinado", help_text="Cópia do texto que o responsável leu ao assinar.")
    doc_hash = models.CharField("resumo do texto assinado", max_length=64)
    prev_hash = models.CharField("selo da assinatura anterior", max_length=64, blank=True)
    seal = models.CharField("selo", max_length=64)
    code = models.CharField("código do comprovante", max_length=10, unique=True)
    nonce = models.CharField(max_length=32, unique=True)

    class Meta:
        ordering = ["pk"]
        verbose_name = "assinatura de autorização"
        verbose_name_plural = "assinaturas de autorização"

    def __str__(self):
        return f"{self.display_code} · {self.student} · {self.get_answer_display()}"

    @property
    def display_code(self):
        return f"{self.code[:5]}-{self.code[5:]}"


class Poll(models.Model):
    """Consulta às famílias: uma pergunta com opções (horário de reunião, data de evento, interesse).

    Um voto por responsável. A equipe vê só os totais, nunca quem votou em quê: o voto guarda a pessoa
    apenas para impedir voto duplo e permitir mudar até o prazo.
    """

    class Status(models.TextChoices):
        OPEN = "aberta", "Aberta"
        CLOSED = "encerrada", "Encerrada"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="polls")
    question = models.CharField("pergunta", max_length=200)
    description = models.TextField("explicação (opcional)", blank=True)
    options = models.JSONField("opções", default=list)
    class_groups = models.ManyToManyField("academics.ClassGroup", blank=True, related_name="polls",
                                          verbose_name="turmas (vazio: escola toda)")
    deadline = models.DateField("responder até")
    show_results = models.BooleanField("mostrar o resultado às famílias depois de encerrar", default=True)
    status = models.CharField("situação", max_length=10, choices=Status.choices, default=Status.OPEN)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="polls_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "consulta às famílias"
        verbose_name_plural = "consultas às famílias"

    def __str__(self):
        return self.question

    def accepts_votes(self, today=None):
        return self.status == self.Status.OPEN and (today or timezone.localdate()) <= self.deadline


class PollVote(models.Model):
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    option = models.PositiveSmallIntegerField()
    voted_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["poll", "user"], name="uniq_poll_vote")]

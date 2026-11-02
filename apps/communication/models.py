from django.db import models
from django.utils import timezone

from apps.core.models import School, User
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
        OUTRO = "outro", "Outro"

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
            if part.isdigit() and int(part) <= limit:
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

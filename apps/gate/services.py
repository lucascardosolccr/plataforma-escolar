"""Códigos da carteirinha e registro de entrada e saída.

**Código único:** 8 símbolos aleatórios (``secrets``) do alfabeto Base32 de Crockford, sem I, L, O e U
para não confundir com 1 e 0, mais 1 dígito verificador (Luhn mod 32). São 32⁸ ≈ 1,1 trilhão de
combinações. O verificador recusa quase todo erro de digitação (troca de um símbolo ou inversão de dois
vizinhos) antes de consultar o banco. O mesmo código vai no código de barras.

**QR Code:** ``EC1:<código>:<assinatura>``, em que a assinatura é um HMAC-SHA256 com a chave secreta do
servidor. Quem não tem a chave não consegue gerar um QR válido para outro código.

**Leitura na portaria:** a tela mostra a foto e o nome a cada leitura, para a equipe conferir quem está
com o cartão (carteirinha emprestada é o risco real; nenhum código o evita sozinho).
"""

import datetime
import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from .models import GateEvent, GateSettings, StudentCard

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ALIASES = {"O": "0", "I": "1", "L": "1"}
QR_PREFIX = "EC1"


# --------------------------------------------------------------------------- códigos


def _luhn32(body):
    """Dígito verificador Luhn mod 32 sobre o alfabeto de Crockford."""
    factor, total, n = 2, 0, len(ALPHABET)
    for ch in reversed(body):
        addend = factor * ALPHABET.index(ch)
        factor = 1 if factor == 2 else 2
        total += addend // n + addend % n
    return ALPHABET[(n - total % n) % n]


def new_code():
    while True:
        body = "".join(secrets.choice(ALPHABET) for _ in range(8))
        code = body + _luhn32(body)
        if not StudentCard.objects.filter(code=code).exists():
            return code


def normalize(text):
    """Maiúsculas, sem hífen nem espaço, com O→0 e I/L→1 (Crockford)."""
    t = "".join(ch for ch in (text or "").upper() if ch not in "- \t")
    return "".join(ALIASES.get(ch, ch) for ch in t)


def valid_shape(code):
    return len(code) == 9 and all(ch in ALPHABET for ch in code) and _luhn32(code[:8]) == code[8]


def _signature(code):
    mac = hmac.new(settings.SECRET_KEY.encode(), f"carteirinha:{code}".encode(), hashlib.sha256).digest()
    out, bits, value = [], 0, 0
    for byte in mac[:7]:
        value, bits = (value << 8) | byte, bits + 8
        while bits >= 5:
            bits -= 5
            out.append(ALPHABET[(value >> bits) & 31])
    return "".join(out[:10])


def qr_payload(card):
    return f"{QR_PREFIX}:{card.code}:{_signature(card.code)}"


QR_LENGTH = len(QR_PREFIX) + 9 + 10  # prefixo, código e assinatura, sem os separadores


def _compact(raw):
    """Só letras e algarismos ASCII, em maiúsculas.

    Tolera o que leitores reais mandam além do conteúdo: identificador de simbologia AIM no início
    (``]Q1``, ``]C0``), espaços, caracteres de controle e separadores trocados pelo layout do teclado. Leitor
    configurado como teclado americano num Windows ABNT2 digita ``Ç`` no lugar de ``:`` (mesma tecla física).
    """
    raw = "".join(ch for ch in (raw or "") if ch.isprintable()).strip()
    if raw.startswith("]") and len(raw) > 3:
        raw = raw[3:]
    return "".join(ch for ch in raw.upper() if ch.isascii() and ch.isalnum())


def parse(raw):
    """(código, forma) do que a portaria recebeu, ou (None, motivo do erro)."""
    compact = _compact(raw)
    if compact.startswith(QR_PREFIX) and len(compact) != 9:
        if len(compact) != QR_LENGTH:
            return None, "QR Code em formato desconhecido."
        code = normalize(compact[3:12])
        signature = normalize(compact[12:])
        if not valid_shape(code) or not hmac.compare_digest(signature, _signature(code)):
            return None, "QR Code com assinatura inválida: não foi gerado por esta plataforma."
        return code, GateEvent.Method.QR
    code = normalize(compact)
    if not valid_shape(code):
        return None, "Código inválido: confira os 9 caracteres (o último é o verificador)."
    return code, None  # código de barras ou digitado: a tela informa qual


# --------------------------------------------------------------------------- carteirinhas


def valid_until(student):
    from apps.registry.models import Enrollment

    enr = Enrollment.objects.filter(student=student, status="ativo").select_related("school_year").first()
    year = enr.school_year if enr else None
    if year and year.end_date:
        return year.end_date
    return datetime.date(timezone.localdate().year, 12, 31)


def active_card(student):
    return StudentCard.objects.filter(student=student, revoked_at__isnull=True).first()


@transaction.atomic
def issue(student, user, reason=""):
    """Emite a carteirinha; se já existe uma ativa, cancela a anterior (segunda via)."""
    old = active_card(student)
    if old:
        old.revoked_at = timezone.now()
        old.revoked_reason = (reason or "Segunda via emitida")[:200]
        old.save(update_fields=["revoked_at", "revoked_reason"])
    return StudentCard.objects.create(school=student.school, student=student, code=new_code(), issued_by=user,
                                      valid_until=valid_until(student))


# --------------------------------------------------------------------------- portaria


def now():
    """Relógio da portaria (separado para os testes fixarem o horário sem mexer na sessão)."""
    return timezone.now()


def active_class(student):
    from apps.registry.models import Enrollment

    enr = Enrollment.objects.filter(student=student, status="ativo").select_related("class_group").first()
    return enr.class_group if enr else None


def is_school_day(school, day):
    """Dia letivo pelo calendário oficial publicado; sem calendário, de segunda a sexta dentro do ano letivo
    (nas férias, o aviso "ainda sem entrada" ia às famílias de todos os estudantes)."""
    from apps.school_calendar.services import current_year, in_school_year, is_published, school_days

    year = current_year(school)
    if is_published(year):
        return day in (school_days(year, day, day) or [])
    return day.weekday() < 5 and in_school_year(school, day)


def lateness(school, class_group, when):
    """(horário esperado, minutos de atraso ou None se dentro da tolerância ou fora de dia letivo)."""
    if not is_school_day(school, when.date()):
        return None, None  # evento em sábado, recesso etc.: registra a entrada, sem atraso
    cfg = GateSettings.for_school(school)
    expected = cfg.entry_for(class_group.turn if class_group else "manha")
    start = datetime.datetime.combine(when.date(), expected, tzinfo=when.tzinfo)
    minutes = int((when - start).total_seconds() // 60)
    return expected, (minutes if minutes > cfg.tolerance else None)


def _fill_attendance(event, user):
    """Leva a chegada para a chamada do dia, sem desfazer o que o professor registrou."""
    from apps.core.models import create_audit_log
    from apps.pedagogy.models import AttendanceRecord

    if not event.class_group or not GateSettings.for_school(event.school).fill_attendance:
        return None
    status = AttendanceRecord.Status.LATE if event.late else AttendanceRecord.Status.PRESENT
    rec, created = AttendanceRecord.objects.get_or_create(
        class_group=event.class_group, student=event.student, date=event.day,
        defaults={"school": event.school, "status": status, "recorded_by": user})
    if not created and rec.status == AttendanceRecord.Status.ABSENT:
        rec.status = AttendanceRecord.Status.LATE
        rec.save(update_fields=["status"])
        create_audit_log(user=user, action="update", target=rec, school=event.school,
                         detail=f"Portaria: {event.student.first_name} chegou às {timezone.localtime(event.at):%H:%M}; "
                                "a falta do dia virou atraso")
    return rec


def _notify(event):
    from apps.communication.family_events import notify_family

    st, hour = event.student, f"{timezone.localtime(event.at):%H:%M}"
    url = reverse("gate:history", args=[st.pk])
    key = f"portaria:{event.kind}:{st.pk}:{event.day.isoformat()}"
    if event.kind == GateEvent.Kind.EXIT:
        return notify_family(st, "saida_escola", f"{st.first_name} saiu da escola às {hour}", url=url,
                             dedupe_key=key)
    if event.late:
        return notify_family(st, "atraso_entrada",
                             f"{st.first_name} chegou à escola às {hour}, com {event.minutes_late} minutos de atraso",
                             body=f"Horário de entrada do turno: {event.expected:%H:%M}.", url=url, dedupe_key=key)
    return notify_family(st, "entrada_escola", f"{st.first_name} chegou à escola às {hour}", url=url,
                         dedupe_key=key)


AUTO_EXIT_AFTER = datetime.timedelta(minutes=30)
OFFLINE_MAX_AGE = datetime.timedelta(hours=24)


def auto_kind(student, when=None):
    """Modo automático da portaria: a primeira leitura do dia é a entrada; uma leitura 30 minutos ou mais
    depois da entrada é a saída. Antes disso, a leitura repetida devolve a própria entrada (nada muda)."""
    when = timezone.localtime(when or now())
    kinds = {e.kind: e for e in GateEvent.objects.filter(student=student, day=when.date())}
    entry = kinds.get(GateEvent.Kind.ENTRY)
    if entry is None:
        return GateEvent.Kind.ENTRY
    if GateEvent.Kind.EXIT in kinds or when - entry.at >= AUTO_EXIT_AFTER:
        return GateEvent.Kind.EXIT
    return GateEvent.Kind.ENTRY


def offline_moment(text, reference=None):
    """Horário de uma leitura guardada sem internet e enviada depois, ou None se for inaceitável.

    Vale só para as últimas 24 horas e nunca no futuro (2 minutos de folga para o relógio do computador)."""
    try:
        moment = datetime.datetime.fromisoformat((text or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(moment):
        return None
    reference = reference or now()
    if moment > reference + datetime.timedelta(minutes=2) or moment < reference - OFFLINE_MAX_AGE:
        return None
    return moment


def register(student, kind, method, user, card=None, when=None, offline=False):
    """Registra entrada ou saída. Devolve (evento, já existia). Uma de cada por dia: repetir a leitura não
    cria outro registro nem outro aviso. ``offline``: lida sem internet e enviada depois, com o horário da
    leitura."""
    when = timezone.localtime(when or now())
    day = when.date()
    existing = GateEvent.objects.filter(student=student, day=day, kind=kind).first()
    if existing:
        return existing, True
    cg = active_class(student)
    expected, late = (lateness(student.school, cg, when) if kind == GateEvent.Kind.ENTRY else (None, None))
    try:
        with transaction.atomic():
            event = GateEvent.objects.create(
                school=student.school, student=student, card=card, class_group=cg, kind=kind, method=method,
                day=day, at=when, expected=expected, late=late is not None, minutes_late=late, recorded_by=user,
                offline=offline)
            if kind == GateEvent.Kind.ENTRY:
                _fill_attendance(event, user)
    except IntegrityError:
        # Duas leituras ao mesmo tempo (dois leitores, Enter duplo): a outra gravou primeiro. Sem erro 500 e
        # sem segundo aviso.
        return GateEvent.objects.get(student=student, day=day, kind=kind), True
    _notify(event)
    return event, False


def entered_but_absent(school, day, class_ids=None):
    """Estudantes que passaram pela portaria no dia e estão com falta na chamada da turma.

    Entrou na escola e não estava na sala: sinal de segurança (e de evasão dentro da escola) que a equipe
    precisa ver no mesmo dia. A chegada nunca grava falta; só aparece aqui quem o professor marcou como falta
    depois. Quem teve a saída registrada aparece com o horário, para a equipe julgar."""
    from apps.pedagogy.models import AttendanceRecord

    entries = GateEvent.objects.filter(school=school, day=day, kind=GateEvent.Kind.ENTRY, class_group__isnull=False)
    if class_ids is not None:
        entries = entries.filter(class_group_id__in=class_ids)
    entries = {e.student_id: e for e in entries.select_related("student", "class_group")}
    if not entries:
        return []
    absent = set(AttendanceRecord.objects.filter(date=day, student_id__in=entries, status=AttendanceRecord.Status.ABSENT)
                 .values_list("student_id", "class_group_id"))
    exits = {e.student_id: e for e in GateEvent.objects.filter(student_id__in=entries, day=day,
                                                              kind=GateEvent.Kind.EXIT)}
    return [{"entry": e, "exit": exits.get(sid)} for sid, e in sorted(entries.items(), key=lambda kv: kv[1].at)
            if (sid, e.class_group_id) in absent]


MISSING_WINDOW = datetime.timedelta(hours=3)  # depois disso o aviso perde o sentido (servidor ligado tarde)


def notify_missing(school, when=None):
    """Avisa a família de quem não tem entrada registrada até ``notify_missing_after`` minutos depois do
    horário do turno. Desligado por padrão; só em dia letivo; uma vez por estudante e dia. Fica de fora quem
    já tem presença (ou atraso) na chamada ou justificativa de falta para o dia."""
    from apps.academics.models import ClassGroup
    from apps.communication.family_events import notify_family
    from apps.pedagogy.models import AbsenceJustification, AttendanceRecord
    from apps.registry.models import Enrollment

    cfg = GateSettings.for_school(school)
    if cfg.notify_missing_after is None:
        return 0
    when = timezone.localtime(when or now())
    day = when.date()
    if not is_school_day(school, day):
        return 0
    sent = 0
    classes = ClassGroup.objects.filter(school=school)
    current = classes.filter(school_year__is_current=True)
    for cg in (current if current.exists() else classes):  # sem ano marcado como atual, todas as turmas
        deadline = datetime.datetime.combine(day, cfg.entry_for(cg.turn), tzinfo=when.tzinfo) \
            + datetime.timedelta(minutes=cfg.notify_missing_after)
        if not deadline <= when <= deadline + MISSING_WINDOW:
            continue
        ids = set(Enrollment.objects.filter(class_group=cg, status="ativo").values_list("student_id", flat=True))
        ids -= set(GateEvent.objects.filter(student_id__in=ids, day=day, kind=GateEvent.Kind.ENTRY)
                   .values_list("student_id", flat=True))
        ids -= set(AttendanceRecord.objects.filter(student_id__in=ids, date=day).exclude(
            status=AttendanceRecord.Status.ABSENT).values_list("student_id", flat=True))
        ids -= set(AbsenceJustification.objects.filter(student_id__in=ids, start_date__lte=day, end_date__gte=day)
                   .exclude(status=AbsenceJustification.Status.REFUSED).values_list("student_id", flat=True))
        from apps.registry.models import Student

        for st in Student.objects.filter(pk__in=ids):
            sent += notify_family(
                st, "sem_entrada", f"Ainda não registramos a chegada de {st.first_name} à escola hoje",
                body=f"Entrada do turno às {cfg.entry_for(cg.turn):%H:%M}. Se {st.first_name} não vai à escola hoje, "
                     "justifique a falta pela plataforma. Se chegou sem passar pela leitura da carteirinha, "
                     "desconsidere.", url=reverse("gate:history", args=[st.pk]),
                dedupe_key=f"sem-entrada:{st.pk}:{day.isoformat()}", include_student=False)
    return sent

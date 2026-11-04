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
from django.db import transaction
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


def parse(raw):
    """(código, forma) do que a portaria recebeu, ou (None, motivo do erro)."""
    raw = (raw or "").strip()
    if raw.upper().startswith(QR_PREFIX + ":"):
        parts = raw.split(":")
        if len(parts) != 3:
            return None, "QR Code em formato desconhecido."
        code = normalize(parts[1])
        if not valid_shape(code) or not hmac.compare_digest(parts[2].upper(), _signature(code)):
            return None, "QR Code com assinatura inválida: não foi gerado por esta plataforma."
        return code, GateEvent.Method.QR
    code = normalize(raw)
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
    """Dia letivo pelo calendário oficial publicado; sem calendário, de segunda a sexta."""
    from apps.school_calendar.services import current_year, is_published, school_days

    year = current_year(school)
    if is_published(year):
        return day in (school_days(year, day, day) or [])
    return day.weekday() < 5


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


def register(student, kind, method, user, card=None, when=None):
    """Registra entrada ou saída. Devolve (evento, já existia). Uma de cada por dia: repetir a leitura não
    cria outro registro nem outro aviso."""
    when = timezone.localtime(when or now())
    day = when.date()
    existing = GateEvent.objects.filter(student=student, day=day, kind=kind).first()
    if existing:
        return existing, True
    cg = active_class(student)
    expected, late = (lateness(student.school, cg, when) if kind == GateEvent.Kind.ENTRY else (None, None))
    with transaction.atomic():
        event = GateEvent.objects.create(
            school=student.school, student=student, card=card, class_group=cg, kind=kind, method=method, day=day,
            at=when, expected=expected, late=late is not None, minutes_late=late, recorded_by=user)
        if kind == GateEvent.Kind.ENTRY:
            _fill_attendance(event, user)
    _notify(event)
    return event, False

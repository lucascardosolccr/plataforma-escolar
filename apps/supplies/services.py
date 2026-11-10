"""Regras da lista de materiais: quem vê e edita, alertas legais, leitura da lista colada e avisos.

Quem faz o quê:

- **montam:** direção, coordenação, secretaria e administração; o professor monta as listas das turmas em que
  leciona (ou as que ele mesmo criou) enquanto estão em rascunho, e envia para revisão;
- **publicam, devolvem e recolhem:** direção, coordenação, secretaria e administração;
- **veem as publicadas:** todas as famílias e estudantes da escola. O "já tenho" de cada família é só dela.
"""

import re
import unicodedata

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Role

from .models import SupplyCheck, SupplyItem, SupplyList

MANAGERS = (Role.DIRECAO.value, Role.COORDENACAO.value, Role.SECRETARIA.value, Role.ADMIN.value)
STAFF = MANAGERS + (Role.PROFESSOR.value,)
FAMILY = (Role.RESPONSAVEL.value, Role.ESTUDANTE.value)

MAX_PASTE_LINES = 150


# ---------------------------------------------------------------- acesso

def is_manager(user):
    return bool(user.school_id) and user.role in MANAGERS


def is_staff(user):
    return bool(user.school_id) and user.role in STAFF


def staff_lists(user):
    """Listas que a pessoa da equipe vê: a gestão vê todas; o professor, as das suas turmas e as que criou."""
    qs = SupplyList.objects.filter(school=user.school)
    if user.role in MANAGERS:
        return qs
    from apps.academics.permissions import teacher_class_ids

    mine = SupplyList.objects.filter(Q(created_by=user) | Q(class_groups__in=teacher_class_ids(user)))
    return qs.filter(pk__in=mine.values("pk"))


def viewable(user):
    """O que a pessoa pode abrir: a equipe, as suas listas e as publicadas; famílias, as publicadas em vigor."""
    if is_staff(user):
        return SupplyList.objects.filter(school=user.school).filter(
            Q(pk__in=staff_lists(user).values("pk")) | Q(status=SupplyList.Status.PUBLISHED))
    if user.school_id and user.role in FAMILY:
        return visible_published(user.school)
    return SupplyList.objects.none()


def can_edit(user, lst):
    """Mudar título, turmas e materiais. Professor só no rascunho; a gestão sempre."""
    if lst.school_id != user.school_id:
        return False
    if user.role in MANAGERS:
        return True
    return user.role == Role.PROFESSOR.value and lst.status == SupplyList.Status.DRAFT and \
        staff_lists(user).filter(pk=lst.pk).exists()


def visible_published(school, today=None):
    """Publicadas de anos letivos que não terminaram (as do ano que vem também)."""
    today = today or timezone.localdate()
    return SupplyList.objects.filter(school=school, status=SupplyList.Status.PUBLISHED).filter(
        Q(school_year__end_date__isnull=True) | Q(school_year__end_date__gte=today) | Q(school_year__is_current=True))


def own_students(user):
    from apps.library.access import own_students as _own

    return _own(user)


def lists_by_student(students, school):
    """{estudante: [listas publicadas das turmas em que ele tem matrícula ativa]}."""
    from apps.registry.models import Enrollment

    classes = {}
    for e in Enrollment.objects.filter(student__in=students, status="ativo").values("student_id", "class_group_id"):
        classes.setdefault(e["student_id"], set()).add(e["class_group_id"])
    wanted = set().union(*classes.values()) if classes else set()
    lists = list(visible_published(school).filter(class_groups__in=wanted).distinct().prefetch_related("class_groups"))
    out = {}
    for s in students:
        mine = classes.get(s.pk, set())
        out[s] = [lst for lst in lists if any(c.pk in mine for c in lst.class_groups.all())]
    return out


def progress(lst, student):
    """(itens obrigatórios marcados, total de obrigatórios, ids marcados)."""
    items = list(lst.items.all())
    done = set(SupplyCheck.objects.filter(item__supply_list=lst, student=student).values_list("item_id", flat=True))
    required = [i for i in items if not i.optional]
    return sum(1 for i in required if i.pk in done), len(required), done


# ---------------------------------------------------------------- alertas legais

def normalize(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


#: Material de uso coletivo: escola particular não pode pedir na lista (Lei 12.886/2013). O texto é o que a pessoa
#: lê ao lado do item; a escola decide, a plataforma só avisa.
COLLECTIVE = [
    (r"\bpapel higienico\b", "papel higiênico"),
    (r"\bpapel toalha\b", "papel toalha"),
    (r"\bguardanapos?\b", "guardanapo"),
    (r"\b(copos?|pratos?|talher(es)?) descartave", "descartáveis de copa"),
    (r"\b(lencos? de papel|lencos? descartave)", "lenço descartável"),
    (r"\balgodao\b", "algodão"),
    (r"\balcool\b", "álcool"),
    (r"\b(detergente|desinfetante|sabao|sabonete|agua sanitaria|material de limpeza)", "material de limpeza e higiene"),
    (r"\besponjas? (de|para) (lavar|louca|pratos?|cozinha|aco)", "material de limpeza"),
    (r"\bgiz\b(?! de cera)(?! de cor)(?! pastel)(?! colorido)", "giz de lousa"),
    (r"\b(pincel atomico|(marcador|caneta|pincel) (para|de) (quadro|lousa)|apagador)", "material de quadro"),
    (r"\b(grampeador|grampos? (para|de) grampeador|clipes?|clips)\b", "material de escritório"),
    (r"\b(toner|cartuchos?|tinta (para|de) impressora|fita (para|de) impressora)\b", "material de impressora"),
    (r"\bresmas?\b", "resma de papel"),
    (r"\bestencil\b", "estêncil"),
    (r"\bsacos? (plasticos?|de lixo)\b", "saco plástico"),
    (r"\b(medicamentos?|remedios?)\b", "medicamento"),
    (r"\b(baloes|balao|bexigas?)\b", "balões"),
    (r"\bpastas? suspensas?\b", "pasta suspensa"),
]
_COLLECTIVE = [(re.compile(rx), label) for rx, label in COLLECTIVE]
_BRAND = re.compile(r"(?<!qualquer )(?<!sem )(?<!sugestao de )\bmarcas?\b")


def item_warnings(item):
    text = normalize(f"{item.name} {item.notes}")
    out = []
    for rx, label in _COLLECTIVE:
        if rx.search(text):
            out.append(f"Parece {label}, de uso coletivo: escola particular não pode pedir na lista "
                       f"(Lei 12.886/2013). Na escola pública, a família não é obrigada a comprar.")
            break
    if _BRAND.search(text):
        out.append("Marca só pode aparecer como sugestão; exigir marca não é permitido (Código de Defesa do "
                   "Consumidor). Escreva, por exemplo, “sugestão: marca X ou similar”.")
    return out


def list_warnings(lst):
    """[(item, [alertas])] só dos itens com alerta."""
    return [(i, w) for i in lst.items.all() if (w := item_warnings(i))]


# ---------------------------------------------------------------- colar a lista

#: forma escrita → (singular, plural)
UNITS = {}
#: Valem como unidade mesmo sem "de" depois ("1 cx lápis", "100 folhas sulfite"); as outras só com "de"
#: ("1 pote de massinha"), para "1 pote plástico" não virar unidade "pote" e material "plástico".
ALONE_UNITS = set()
for _sing, _plur, *_abbr in [
    ("unidade", "unidades", "un", "und", "unid"), ("caixa", "caixas", "cx"), ("pacote", "pacotes", "pct", "pc"),
    ("folha", "folhas", "fls", "fl"), ("rolo", "rolos"), ("tubo", "tubos"), ("frasco", "frascos"),
    ("par", "pares"), ("kit", "kits"), ("bloco", "blocos"), ("pote", "potes"), ("metro", "metros", "m"),
    ("refil", "refis"), ("vidro", "vidros"),
]:
    for _form in (_sing, _plur, *_abbr):
        UNITS[_form] = (_sing, _plur)
        if _form in _abbr or _sing == "folha":
            ALONE_UNITS.add(_form)

_LINE = re.compile(
    r"^(?:(?P<num>\d{1,3})[.)]\s+)?"            # numeração da lista ("3) ", "4. "), ignorada
    r"(?:(?P<qty>\d{1,3})\s*(?:x\b|-|–|—)?\s*)?"  # quantidade ("2 ", "02 - ", "2x ")
    r"(?P<rest>.+)$", re.I)
_OPTIONAL = re.compile(r"\s*[\(\[]?\s*opcional\s*[\)\]]?\s*$", re.I)


def unit_label(unit, quantity):
    forms = UNITS.get(normalize(unit).rstrip("."))
    if not forms:
        return unit
    return forms[0] if quantity == 1 else forms[1]


def parse_line(line):
    """Um item a partir de uma linha como "02 - caixas de lápis de cor (opcional)". None se não houver item."""
    line = line.strip().lstrip("-•*·–—▪◦ ").strip().rstrip(";,.").strip()
    if not line:
        return None
    optional = bool(_OPTIONAL.search(line))
    line = _OPTIONAL.sub("", line).strip().rstrip(";,.-").strip()
    m = _LINE.match(line)
    if not m:
        return None
    if not m.group("qty") and (line.endswith(":") or line.isupper()):
        return None  # título de seção ("MATERIAL DE ARTES", "Para a pasta:")
    qty = int(m.group("qty")) if m.group("qty") else 1
    rest = m.group("rest").strip()
    unit = ""
    head, _, tail = rest.partition(" ")
    key = normalize(head).rstrip(".")
    linked = re.match(r"(de|do|da)\s+", tail.strip(), flags=re.I)
    if tail and key in UNITS and (linked or key in ALONE_UNITS):
        unit = unit_label(head, qty)
        rest = tail.strip()[linked.end():] if linked else tail.strip()
    if not rest or not re.search(r"[^\W\d_]", rest):
        return None
    qty = max(1, min(qty, 999))
    return {"name": (rest[0].upper() + rest[1:])[:160], "quantity": qty, "unit": unit, "optional": optional}


def parse_text(text):
    items = []
    for line in (text or "").splitlines()[:MAX_PASTE_LINES]:
        parsed = parse_line(line)
        if parsed:
            items.append(parsed)
    return items


def add_items(lst, parsed):
    start = (lst.items.order_by("-position").values_list("position", flat=True).first() or 0) + 1
    SupplyItem.objects.bulk_create([SupplyItem(supply_list=lst, position=start + n, **p) for n, p in enumerate(parsed)])
    return len(parsed)


def as_text(lst):
    """A lista em texto simples, para colar no WhatsApp ou imprimir sem a plataforma."""
    lines = [lst.title.upper(), f"{lst.school_year} · {lst.school}"]
    classes = ", ".join(c.name for c in lst.class_groups.all())
    if lst.grade or classes:
        lines.append(" · ".join(x for x in (lst.grade, classes) if x))
    if lst.deliver_by:
        lines.append(f"Entregar até {lst.deliver_by:%d/%m/%Y}")
    lines.append("")
    if lst.intro:
        lines += [lst.intro.strip(), ""]
    for item in lst.items.all():
        name = item.name
        unit = ""
        if item.unit:
            unit = f" {unit_label(item.unit, item.quantity)} de"
            if len(name) > 1 and name[1].islower():  # "1 caixa de lápis", sem estragar sigla ("TNT")
                name = name[0].lower() + name[1:]
        extra = f" ({item.notes})" if item.notes else ""
        lines.append(f"[ ] {item.quantity}{unit} {name}{extra}{' (opcional)' if item.optional else ''}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- avisos

def enrolled_students(lst):
    from apps.registry.models import Student

    return Student.objects.filter(enrollments__class_group__in=lst.class_groups.all(), enrollments__status="ativo",
                                  status="ativo").distinct()


def notify_families(lst, update=False):
    """Avisa as famílias das turmas vinculadas. Devolve quantos estudantes foram alcançados."""
    from apps.communication.family_events import notify_family

    url = reverse("supplies:detail", args=[lst.pk])
    title = (f"Lista de materiais atualizada: {lst.title}" if update else f"Lista de materiais: {lst.title}")
    when = f" Entregar até {lst.deliver_by:%d/%m/%Y}." if lst.deliver_by else ""
    body = ("A escola mudou a lista. Confira o que foi alterado." if update else
            f"A lista do material escolar está publicada.{when} Marque o que já providenciou.")
    students = list(enrolled_students(lst))
    for s in students:
        notify_family(s, "lista_materiais", title, body=body, url=url,
                      dedupe_key=f"materiais:{lst.pk}:{lst.revision}:{s.pk}")
    return len(students)


def notify_people(lst, users, title, body):
    """Aviso à equipe (pedido de revisão, lista devolvida). Cada envio é um aviso novo."""
    from apps.communication.models import Notification
    from apps.communication.services import notify_many

    stamp = int(timezone.now().timestamp())
    return notify_many(lst.school, list(users), Notification.Kind.ANNOUNCEMENT, title, body=body,
                       url=reverse("supplies:detail", args=[lst.pk]), dedupe_key=f"materiais:equipe:{lst.pk}:{stamp}")


def reviewers(school, exclude=None):
    from apps.core.models import User

    users = User.objects.filter(school=school, is_active=True, role__in=(Role.COORDENACAO.value, Role.DIRECAO.value))
    return users.exclude(pk=exclude.pk) if exclude else users


# ---------------------------------------------------------------- pendências

def pending_for_family(user, today=None):
    """Listas das turmas dos filhos com obrigatórios ainda não marcados, enquanto o prazo vale."""
    today = today or timezone.localdate()
    students = own_students(user)
    if not students:
        return 0
    total = 0
    for s, lists in lists_by_student(students, user.school).items():
        for lst in lists:
            recent = lst.published_at and (today - timezone.localtime(lst.published_at).date()).days <= 30
            if (lst.deliver_by and lst.deliver_by >= today) or (not lst.deliver_by and recent):
                done, required, _ = progress(lst, s)
                total += done < required
    return total

"""Revisão espaçada dos exercícios de prática: quando cada exercício volta para o estudante.

Fundamento:

- **Recuperar da memória** (responder de novo sem olhar) fixa mais que reler, e **espaçar** as revisões rende mais
  que concentrá-las na véspera. São as duas técnicas de estudo com a maior utilidade na revisão de Dunlosky,
  Rawson, Marsh, Nathan & Willingham (2013), Psychological Science in the Public Interest 14(1), 4–58,
  doi:10.1177/1529100612453266; meta-análise da prática distribuída em Cepeda, Pashler, Vul, Wixted & Rohrer
  (2006), Psychological Bulletin 132(3), 354–380, doi:10.1037/0033-2909.132.3.354.
- **Intervalos crescentes à moda de Leitner:** acertou na revisão, o exercício sobe de caixa e o próximo intervalo
  aumenta (1, 2, 4, 7 e 14 dias); errou, volta para amanhã. O melhor intervalo depende de quando será a prova
  (Cepeda, Vul, Rohrer, Wixted & Pashler, 2008, Psychological Science 19(11), 1095–1102): por isso o intervalo nunca
  passa da véspera da prova, e a última revisão cai antes dela.
- **Só a primeira resposta de cada dia conta** como recuperação. Responder de novo logo depois de ver o gabarito e a
  explicação é reestudo, útil, mas não mostra que o estudante lembra.
- **Intercalar assuntos:** a lista "para revisar hoje" alterna os tópicos em vez de agrupá-los. Praticar misturando
  tipos de problema melhorou o desempenho em prova de matemática num experimento em sala de aula (Rohrer, Dedrick &
  Stershic, 2015, Journal of Educational Psychology 107(3), 900–908, doi:10.1037/edu0000001).

É organização do estudo, não avaliação: nada aqui vira nota nem evidência além do que já virava (a primeira
tentativa, em ``cognitio.evidence``).
"""

import datetime
from collections import defaultdict
from itertools import zip_longest

from django.utils import timezone

INTERVALS = (1, 2, 4, 7, 14)  # dias até a próxima revisão, por caixa (0 = errou na última)


def _local_day(dt):
    return timezone.localtime(dt).date() if timezone.is_aware(dt) else dt.date()


def state(attempts, exam_date, today):
    """Situação de UM exercício para UM estudante a partir das tentativas (em ordem).

    Devolve {"state": "novo" | "hoje" | "agendado" | "concluido", "due": data ou None, "box": 0..len(INTERVALS)-1,
    "days": dias distintos em que respondeu}.
    """
    if not attempts:
        return {"state": "novo", "due": today if exam_date >= today else None, "box": 0, "days": 0}
    first_of_day = {}
    for a in attempts:
        first_of_day.setdefault(_local_day(a.created_at), a)
    box = 0
    for day in sorted(first_of_day):
        box = min(box + 1, len(INTERVALS) - 1) if first_of_day[day].is_correct else 0
    last_day = max(first_of_day)
    due = last_day + datetime.timedelta(days=INTERVALS[box])
    eve = exam_date - datetime.timedelta(days=1)
    if due > eve:
        due = eve if eve > last_day else None
    if exam_date < today or due is None:
        return {"state": "concluido", "due": None, "box": box, "days": len(first_of_day)}
    return {"state": "hoje" if due <= today else "agendado", "due": due, "box": box, "days": len(first_of_day)}


def plan(questions, attempts, exam_date, today=None):
    """{questão: estado} e a lista do dia intercalada por tópico (novos depois das revisões vencidas).

    ``attempts``: tentativas do estudante nessas questões, em ordem de criação.
    """
    today = today or timezone.localdate()
    by_q = defaultdict(list)
    for a in attempts:
        by_q[a.question_id].append(a)
    states = {q.pk: state(by_q.get(q.pk, []), exam_date, today) for q in questions}

    def interleave(qs):
        by_topic = defaultdict(list)
        for q in qs:
            by_topic[q.topic_id].append(q)
        return [q for group in zip_longest(*by_topic.values()) for q in group if q is not None]

    due = interleave([q for q in questions if states[q.pk]["state"] == "hoje"])
    new = interleave([q for q in questions if states[q.pk]["state"] == "novo"])
    upcoming = sorted((states[q.pk]["due"] for q in questions if states[q.pk]["state"] == "agendado"), key=str)
    return {"states": states, "today": due, "new": new, "next": upcoming[0] if upcoming else None}


def spaced_students(guide, student_ids):
    """Quantos estudantes responderam exercícios em 2 dias ou mais (prática distribuída) e quantos praticaram."""
    from .models import PracticeAttempt

    days = defaultdict(set)
    for sid, created in PracticeAttempt.objects.filter(question__guide=guide, student_id__in=student_ids) \
            .values_list("student_id", "created_at"):
        days[sid].add(_local_day(created))
    return {"practiced": len(days), "spaced": sum(1 for d in days.values() if len(d) >= 2)}

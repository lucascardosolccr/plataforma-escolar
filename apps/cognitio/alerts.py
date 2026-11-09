"""Sistema de alertas precoces (Early Warning) por regras pedagógicas explícitas.

Cada alerta informa estudante ou grupo, habilidade, evidências, período, regra,
fatores, incerteza, limitações e próxima ação. Não usa diagnóstico, laudo,
necessidade específica nem nenhum dado do módulo de inclusão (verificado em
teste). Nenhuma probabilidade é mostrada enquanto não houver modelo validado
(ver ``predictive.py``): até lá, todo alerta é sinalização exploratória.

Regras (``RULES``) e critérios em ``docs/EIA_COGNITIO_MODELOS_PREDITIVOS.md``.
"""

import datetime
import threading

from django.db import transaction
from django.utils import timezone

from apps.core.fmt import dec

from .mastery import apply_judgments, assess, group_evidence
from .models import LearningAlert, MasteryScale, SkillEvidence

METHOD = "Regra pedagógica explícita (sinalização exploratória; não é previsão estatística validada)"
LIMITS = ("Baseado só nos registros da plataforma: evidências faltantes, avaliações mal ligadas às habilidades ou "
          "situações atípicas no dia podem distorcer o resultado. Confirme com o que você observa em sala.")

RULES = {
    "dificuldade_persistente": "Dificuldade persistente",
    "prerequisito": "Pré-requisito não consolidado para conteúdo próximo",
    "fundamental_sem_evidencia": "Evidências insuficientes em habilidade fundamental",
    "contraditoria": "Desempenho inconsistente: confirmar com nova avaliação",
    "sem_evidencia_recente": "Sem evidência recente em habilidade ainda não consolidada",
    "queda": "Queda persistente nas evidências recentes",
    "retomada_coletiva": "Habilidade que demanda retomada com a turma",
    "acompanhamento": "Sinais combinados: frequência, entregas e habilidades",
    "trajetoria": "Trajetória em queda: notas ou presença",
}


_run = threading.local()  # alertas da turma lidos de uma vez durante generate_for_class


def _same(alert, name, value):
    field = LearningAlert._meta.get_field(name)
    if field.is_relation:  # compara pelo id: ler o objeto relacionado custaria uma consulta por campo
        return getattr(alert, field.attname) == (value.pk if value is not None else None)
    return getattr(alert, name) == value


def _upsert(school, fp, seen, **values):
    seen.add(fp)
    cache = getattr(_run, "alerts", None)
    alert = cache.get(fp) if cache is not None and fp in cache else         LearningAlert.objects.filter(school=school, fingerprint=fp).first()
    if alert is None:
        return LearningAlert.objects.create(school=school, fingerprint=fp, **values), True
    changed = [k for k, v in values.items() if not _same(alert, k, v)]
    for k in changed:
        setattr(alert, k, values[k])
    if not alert.active:
        alert.active = True
        changed.append("active")
        if alert.status == LearningAlert.Status.RESOLVED:
            alert.status = LearningAlert.Status.NEW  # a condição voltou
    if changed:  # sem mudança, nada a gravar (antes, cada alerta era regravado todo dia)
        alert.save()
    return alert, False


def _ev_ids(a):
    return [e.pk for e in a.evidence if getattr(e, "pk", None)][:30]


def generate_for_class(class_group, today=None):
    """Recalcula os alertas da turma. Devolve (novos, ativos).

    Uma transação por turma (no SQLite, cada gravação avulsa é um commit em disco) e os alertas existentes
    lidos de uma vez: na base de escala, de 42 s para poucos segundos por escola, com o mesmo resultado."""
    with transaction.atomic():
        _run.alerts = {a.fingerprint: a for a in LearningAlert.objects.filter(school=class_group.school,
                                                                             class_group=class_group)}
        try:
            return _generate_for_class(class_group, today)
        finally:
            _run.alerts = None


def _generate_for_class(class_group, today=None):
    from apps.registry.models import Enrollment

    from .graph import dependents as _dependents

    cache = {}

    def dependents(item, school):  # uma consulta por habilidade, não por estudante
        if item.pk not in cache:
            cache[item.pk] = list(_dependents(item, school).select_related("target"))
        return cache[item.pk]

    today = today or timezone.localdate()
    school = class_group.school
    scale = MasteryScale.for_school(school)
    students = {e.student_id: e.student for e in Enrollment.objects.filter(class_group=class_group, status="ativo")
                .select_related("student")}
    evs = SkillEvidence.objects.filter(class_group=class_group, student_id__in=students).select_related("item", "subject")
    grouped = group_evidence(evs)
    subj_of = {}
    for e in evs:
        subj_of[e.item_id] = e.subject
    # decisão do professor sem evidência mais nova vale também para os alertas
    states = apply_judgments({key: assess(v, scale, today) for key, v in grouped.items()})
    upcoming = _upcoming_items(class_group, today)
    seen, new = set(), 0
    start = min((e.observed_on for e in evs), default=None)

    def common(sid, item, a):
        return {"student": students.get(sid), "class_group": class_group, "subject": subj_of.get(item.pk),
                "item": item, "evidence_ids": _ev_ids(a), "period_start": start, "period_end": today,
                "method": METHOD, "limitations": LIMITS,
                "uncertainty": f"Incerteza {a.uncertainty or 'alta'} ({a.n_valid} evidência(s) válida(s))."}

    for (sid, item_id), a in states.items():
        item = a.evidence[0].item if a.evidence else None
        if item is None:
            continue
        name = students[sid].first_name
        span = (a.evidence[-1].observed_on - a.evidence[0].observed_on).days if a.evidence else 0
        if a.state == "dificuldade" and a.n_valid >= 3 and span >= 14:
            _, n = _upsert(school, f"persist:{sid}:{item.pk}", seen, rule="dificuldade_persistente",
                           level="importante", title=f"{name}: dificuldade persistente em {item.code}",
                           explanation=f"{a.n_valid} evidências em {span} dias, média {dec(a.mean)} (abaixo do corte "
                                       f"de {dec(scale.t1)}).",
                           factors=[f"{e.observed_on:%d/%m} {e.source_label}: "
                                    f"{'—' if e.ratio is None else round(e.ratio * 100)}%" for e in a.evidence][-6:],
                           next_action="Retomar a habilidade com outra abordagem e verificar os pré-requisitos "
                                       "(veja as recomendações). Registrar nova evidência depois.",
                           **common(sid, item, a))
            new += n
        if a.state == "contraditoria":
            _, n = _upsert(school, f"contra:{sid}:{item.pk}", seen, rule="contraditoria", level="atencao",
                           title=f"{name}: resultados inconsistentes em {item.code}",
                           explanation="Há evidências muito altas e muito baixas na mesma habilidade.",
                           factors=[f"{e.source_label}: {round(e.ratio * 100)}%" for e in a.evidence
                                    if e.ratio is not None][-6:],
                           next_action="Aplicar uma verificação curta e diferente (oral, prática ou escrita) para "
                                       "confirmar a hipótese antes de qualquer intervenção.",
                           **common(sid, item, a))
            new += n
        if a.state in ("dificuldade", "desenvolvimento") and a.stale:
            _, n = _upsert(school, f"stale:{sid}:{item.pk}", seen, rule="sem_evidencia_recente", level="atencao",
                           title=f"{name}: sem evidência recente em {item.code}",
                           explanation=f"Última evidência em {a.last_date:%d/%m/%Y}, há mais de {scale.stale_days} dias, "
                                       f"com a habilidade em '{a.label.lower()}'.",
                           factors=[a.label], next_action="Planejar uma nova situação que permita observar a habilidade.",
                           **common(sid, item, a))
            new += n
        if a.trend == "queda":
            _, n = _upsert(school, f"queda:{sid}:{item.pk}", seen, rule="queda", level="atencao",
                           title=f"{name}: queda nas evidências recentes de {item.code}",
                           explanation="As duas evidências mais recentes ficaram bem abaixo das anteriores. Pode ser "
                                       "situação pontual; não é conclusão de regressão.",
                           factors=[f"{e.observed_on:%d/%m}: {round(e.ratio * 100)}%" for e in a.evidence
                                    if e.ratio is not None][-5:],
                           next_action="Conversar com o estudante e observar de novo antes de concluir.",
                           **common(sid, item, a))
            new += n
        # Pré-requisito ainda não consolidado de algo que vem nas próximas semanas.
        if a.state in ("dificuldade", "desenvolvimento", "insuficiente", "nao_avaliado") and a.n_valid:
            for rel in dependents(item, school):
                if rel.target_id in upcoming:
                    when, what = upcoming[rel.target_id]
                    _, n = _upsert(school, f"prereq:{sid}:{item.pk}:{rel.target_id}", seen, rule="prerequisito",
                                   level="importante" if a.state == "dificuldade" else "atencao",
                                   title=f"{name}: {item.code} ainda não consolidada antes de {rel.target.code}",
                                   explanation=f"{rel.target.code} aparece em '{what}' ({when:%d/%m}). {item.code} pode "
                                               f"ser pré-requisito ({rel.get_kind_display().lower()}, "
                                               f"{rel.get_status_display().lower()}) e está '{a.label.lower()}'.",
                                   factors=[rel.rationale[:200]],
                                   next_action=f"Retomar {item.code} antes de {when:%d/%m} ou prever apoio na aula.",
                                   **common(sid, item, a))
                    new += n
    # Habilidade fundamental (com 2+ dependentes) já trabalhada e sem evidência suficiente.
    worked = _worked_items(class_group, today)
    for item in worked:
        deps = len(dependents(item, school))
        if deps < 2:
            continue
        lacking = [students[sid] for sid in students
                   if states.get((sid, item.pk)) is None or states[(sid, item.pk)].state in ("nao_avaliado",
                                                                                             "insuficiente")]
        if lacking and len(lacking) >= max(1, len(students) // 3):
            _, n = _upsert(school, f"fund:{class_group.pk}:{item.pk}", seen, rule="fundamental_sem_evidencia",
                           level="atencao", student=None, class_group=class_group, subject=None, item=item,
                           title=f"{class_group.name}: {item.code} sem evidência suficiente para {len(lacking)} estudante(s)",
                           explanation=f"{item.code} foi trabalhada e tem {deps} habilidade(s) que podem depender dela, "
                                       "mas falta evidência para concluir.",
                           factors=[s.first_name for s in lacking][:12], evidence_ids=[], period_start=start,
                           period_end=today, method=METHOD, limitations=LIMITS,
                           uncertainty="Sem evidência não quer dizer dificuldade.",
                           next_action="Incluir uma questão ou observação desta habilidade na próxima avaliação.")
            new += n
    # Retomada coletiva.
    by_item = {}
    for (sid, item_id), a in states.items():
        by_item.setdefault(item_id, []).append(a)
    for item_id, lst in by_item.items():
        diff = [a for a in lst if a.state == "dificuldade"]
        if students and len(diff) / len(students) >= 0.3 and len(diff) >= 2:
            item = lst[0].evidence[0].item
            _, n = _upsert(school, f"coletiva:{class_group.pk}:{item_id}", seen, rule="retomada_coletiva",
                           level="importante", student=None, class_group=class_group, subject=subj_of.get(item_id),
                           item=item, title=f"{class_group.name}: retomar {item.code} com a turma",
                           explanation=f"{len(diff)} de {len(students)} estudantes com dificuldade observada.",
                           factors=[], evidence_ids=[], period_start=start, period_end=today, method=METHOD,
                           limitations=LIMITS, uncertainty="Proporção calculada só com quem tem evidência suficiente.",
                           next_action="Replanejar: retomada coletiva com estratégia diferente e nova verificação.")
            new += n
    new += _general_signals(class_group, students, states, today, seen)
    new += _trajectory_signals(class_group, students, today, seen)
    # Condições que deixaram de ocorrer.
    stale_alerts = LearningAlert.objects.filter(school=school, class_group=class_group, active=True).exclude(
        fingerprint__in=seen)
    for al in stale_alerts:
        al.active = False
        if al.status in (LearningAlert.Status.NEW, LearningAlert.Status.REVIEW):
            al.status = LearningAlert.Status.RESOLVED
            al.status_note = (al.status_note + " " if al.status_note else "") + \
                f"Condição deixou de ocorrer em {today:%d/%m/%Y}."
        al.save()
    active = LearningAlert.objects.filter(school=school, class_group=class_group, active=True).count()
    return new, active


def _upcoming_items(class_group, today, days=30):
    """{item_id: (data, rótulo)} de planejamentos, atividades e avaliações dos próximos dias."""
    from apps.pedagogy.models import Activity, Evaluation, LessonPlan

    end = today + datetime.timedelta(days=days)
    out = {}
    for p in LessonPlan.objects.filter(class_group=class_group, starts_on__gte=today, starts_on__lte=end) \
            .prefetch_related("curriculum"):
        for it in p.curriculum.all():
            out.setdefault(it.pk, (p.starts_on, f"planejamento {p.title}"))
    for a in Activity.objects.filter(class_group=class_group, class_date__gte=today, class_date__lte=end) \
            .exclude(status="cancelada").prefetch_related("curriculum"):
        for it in a.curriculum.all():
            out.setdefault(it.pk, (a.class_date, f"atividade {a.title}"))
    for e in Evaluation.objects.filter(class_group=class_group, date__gte=today, date__lte=end) \
            .prefetch_related("curriculum"):
        for it in e.curriculum.all():
            out.setdefault(it.pk, (e.date, f"avaliação {e.title}"))
    return out


def _worked_items(class_group, today):
    from apps.curriculum.models import CurriculumItem
    from apps.pedagogy.models import Activity, LessonPlan

    ids = set(LessonPlan.objects.filter(class_group=class_group, ends_on__lt=today).values_list("curriculum", flat=True))
    ids |= set(Activity.objects.filter(class_group=class_group, class_date__lt=today, status="publicada")
               .values_list("curriculum", flat=True))
    ids.discard(None)
    return list(CurriculumItem.objects.filter(pk__in=ids))


def _general_signals(class_group, students, states, today, seen):
    """Frequência < 75% nos últimos 60 dias, 3+ entregas não registradas e 2+
    habilidades com dificuldade, em conjunto. Nunca usa dado de inclusão."""
    from apps.pedagogy.models import AttendanceRecord, Submission

    since = today - datetime.timedelta(days=60)
    new = 0
    for sid, st in students.items():
        recs = list(AttendanceRecord.objects.filter(student_id=sid, class_group=class_group, date__gte=since)
                    .values_list("status", flat=True))
        rate = (sum(1 for s in recs if s != "falta") / len(recs)) if recs else None
        missing = Submission.objects.filter(student_id=sid, activity__class_group=class_group,
                                            status="nao_entregue", activity__deadline__gte=since).count()
        diffs = [k[1] for k, a in states.items() if k[0] == sid and a.state == "dificuldade"]
        factors = []
        if rate is not None and rate < 0.75:
            factors.append(f"Frequência de {round(rate * 100)}% nos últimos 60 dias ({len(recs)} registros).")
        if missing >= 3:
            factors.append(f"{missing} atividades marcadas como não entregues nos últimos 60 dias.")
        if len(diffs) >= 2:
            factors.append(f"{len(diffs)} habilidades com dificuldade observada.")
        if len(factors) >= 2:
            _, n = _upsert(class_group.school, f"geral:{sid}:{class_group.pk}", seen, rule="acompanhamento",
                           level="importante", student=st, class_group=class_group, subject=None, item=None,
                           title=f"{st.first_name}: sinais combinados pedem acompanhamento",
                           explanation="Dois ou mais sinais ao mesmo tempo. Nenhum deles, sozinho, define nada.",
                           factors=factors, evidence_ids=[], period_start=since, period_end=today, method=METHOD,
                           limitations=LIMITS + " Faltas podem ter motivos justificados que não aparecem aqui.",
                           uncertainty="Combinação de indicadores simples, sem modelo estatístico.",
                           next_action="Conversar com o estudante e a família; articular com a coordenação.")
            new += n
    return new


def _trajectory_signals(class_group, students, today, seen):
    """Queda em curso (CUSUM) ou confirmada (Mann–Kendall) nas notas ou na presença semanal, desde o início
    do ano letivo. Métodos e referências em ``trajectory.py``. Ocorrências não entram aqui."""
    from apps.analytics.bi import _school_year_dates

    from .trajectory import class_overview

    if not students:
        return 0
    start = _school_year_dates(class_group.school, today)[0]
    new = 0
    for r in class_overview(class_group, start, today, today=today, behavior=False, students=set(students))["rows"]:
        ind = next((i for i in r["indicators"] if i["key"] == "trajetoria"), None)
        if ind is None:
            continue
        st = r["student"]
        _, n = _upsert(class_group.school, f"trajetoria:{st.pk}:{class_group.pk}", seen, rule="trajetoria",
                       level="atencao", student=st, class_group=class_group, subject=None, item=None,
                       title=f"{st.first_name}: trajetória em queda", explanation=ind["detail"], factors=[ind["detail"]],
                       evidence_ids=[], period_start=start, period_end=today,
                       method="Tendência robusta (Theil–Sen), teste de Mann–Kendall e CUSUM sobre notas e presença "
                              "semanal (sinalização exploratória; não é previsão estatística validada)",
                       limitations=LIMITS + " Mudança de critério de correção ou prova de recuperação também mudam a "
                                            "série.",
                       uncertainty="Queda confirmada estatisticamente nos registros; a causa não aparece nos dados.",
                       next_action="Abrir a trajetória do estudante, conversar com ele e com os professores sobre o que "
                                   "mudou e combinar uma verificação curta.")
        new += n
    return new


def generate_for_school(school, today=None):
    from apps.academics.models import ClassGroup

    total_new = 0
    for cg in ClassGroup.objects.filter(school=school, school_year__is_current=True):
        n, _ = generate_for_class(cg, today)
        total_new += n
    return total_new

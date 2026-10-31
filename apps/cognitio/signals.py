"""Mantém o repositório de evidências em dia sem pedir nada a mais ao professor.

Qualquer lançamento (nota, entrega, questão, observação, análise revisada, troca de
habilidades numa atividade ou avaliação) marca a turma; ao fim da transação, a
turma é recalculada uma única vez. Uma falha no recálculo nunca desfaz o
lançamento do professor: fica no log e o comando ``cognitio_rebuild`` corrige.
"""

import logging
import threading

from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save

logger = logging.getLogger(__name__)
_pending = threading.local()


def mark(class_group_id):
    if not class_group_id:
        return
    # O id entra antes de registrar (fora de transação, on_commit roda na hora).
    # Cada lançamento registra um callback, mas só o primeiro encontra trabalho:
    # ele esvazia o conjunto e os seguintes não fazem nada. Assim nada se perde
    # se a transação anterior foi desfeita e o callback dela, descartado.
    ids = getattr(_pending, "ids", None) or set()
    ids.add(class_group_id)
    _pending.ids = ids
    transaction.on_commit(_flush)


def _flush():
    from apps.academics.models import ClassGroup

    from .evidence import rebuild_class

    ids, _pending.ids = getattr(_pending, "ids", set()) or set(), None
    for cg in ClassGroup.objects.filter(pk__in=ids):
        try:
            rebuild_class(cg)
        except Exception:  # o lançamento do professor já foi salvo
            logger.exception("Falha ao recalcular evidências da turma %s", cg.pk)


def _class_of(instance):
    for path in ("class_group_id", "evaluation.class_group_id", "activity.class_group_id",
                 "group_work.class_group_id", "question.evaluation.class_group_id"):
        obj = instance
        try:
            for part in path.split("."):
                obj = getattr(obj, part)
        except Exception:
            continue
        if obj:
            return obj
    return None


def _on_change(sender, instance, **kwargs):
    mark(_class_of(instance))


def connect():
    from apps.pedagogy.models import Activity, Evaluation, GroupWork, GroupWorkDelivery, Grade, Submission

    from .models import QuestionResponse, QuestionSkill, SkillObservation, TextAnalysis

    for model in (Grade, Submission, GroupWorkDelivery, QuestionResponse, QuestionSkill, SkillObservation,
                  TextAnalysis, Evaluation, Activity, GroupWork):
        post_save.connect(_on_change, sender=model, dispatch_uid=f"cognitio-save-{model.__name__}")
        post_delete.connect(_on_change, sender=model, dispatch_uid=f"cognitio-del-{model.__name__}")
    for model in (Activity, Evaluation, GroupWork):
        m2m_changed.connect(_on_change, sender=model.curriculum.through,
                            dispatch_uid=f"cognitio-m2m-{model.__name__}")
    m2m_changed.connect(_on_change, sender=TextAnalysis.items.through, dispatch_uid="cognitio-m2m-text")

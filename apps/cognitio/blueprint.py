"""Validade de conteúdo da prova: o blueprint declarado × o que as questões medem.

A tela de questões deixa o professor etiquetar a avaliação com as habilidades que ela
cobre (``Evaluation.curriculum``) e ligar cada questão à habilidade que ela verifica
(``Question.skills``). Esta função cruza as duas coisas, sem olhar nenhuma resposta de
estudante — é sobre o desenho da prova, não sobre o desempenho da turma.

Para que serve (tabela de especificações / validade de conteúdo):

- **Peso de cada habilidade:** quantas questões e quantos pontos medem cada habilidade
  declarada. Uma prova que diz cobrir cinco habilidades mas concentra 80% dos pontos numa
  delas sub-representa as outras quatro. A representatividade do conteúdo é o cerne da
  validade de conteúdo (AERA, APA & NCME, 2014, *Standards for Educational and Psychological
  Testing*, padrão 1.11; Messick, 1995, *American Psychologist* 50(9), 741–749).
- **Declarada mas não medida:** habilidade na etiqueta da avaliação que nenhuma questão
  verifica — sub-representação do construto (Messick). Acontece quando a habilidade foi
  marcada na avaliação mas ficou sem questão, ou quando a questão que a media foi excluída.
- **Medida mas não declarada:** habilidade que alguma questão verifica e que não está na
  etiqueta — variância irrelevante ao construto, ou simplesmente uma etiqueta desatualizada.

Limites declarados: o "peso" soma os pontos inteiros de cada questão a todas as habilidades
que ela mede, então, quando uma questão mede mais de uma habilidade, os percentuais somam
mais de 100% — é proporção de atenção, não partição dos pontos. A função não julga se a
quantidade de questões por habilidade é suficiente para concluir sobre um estudante; isso é
papel da análise da prova (``exam_analysis``). Só descreve o que foi registrado.
"""

from decimal import Decimal

from .models import QuestionSkill

ZERO = Decimal("0")


def blueprint_check(evaluation, questions=None):
    """Compara ``evaluation.curriculum`` (blueprint) com as habilidades das questões."""
    declared = {i.pk: i for i in evaluation.curriculum.all()}
    if questions is None:
        questions = evaluation.questions.prefetch_related("questionskill_set__item")
    qs = list(questions)

    measured, q_count, points, principal = {}, {}, {}, set()
    for q in qs:
        mp = q.max_points or ZERO
        for link in q.questionskill_set.all():
            item = link.item
            measured.setdefault(item.pk, item)
            q_count[item.pk] = q_count.get(item.pk, 0) + 1
            points[item.pk] = points.get(item.pk, ZERO) + mp
            if link.role == QuestionSkill.Role.MAIN:
                principal.add(item.pk)

    total_points = sum((q.max_points or ZERO for q in qs), ZERO)

    def row(pk, item):
        n = q_count.get(pk, 0)
        pts = points.get(pk, ZERO)
        return {
            "item": item,
            "questions": n,
            "points": pts,
            "share": (pts / total_points * 100) if total_points else None,
            "principal": pk in principal,
            "measured": n > 0,
            "declared": pk in declared,
        }

    all_items = {**declared, **measured}
    rows = sorted((row(pk, item) for pk, item in all_items.items()), key=lambda r: r["item"].code)
    return {
        "has_data": bool(qs) and bool(all_items),
        "n_questions": len(qs),
        "total_points": total_points,
        "declared_total": len(declared),
        "rows": rows,
        "not_measured": [r for r in rows if r["declared"] and not r["measured"]],
        "not_declared": [r for r in rows if r["measured"] and not r["declared"]],
        "aligned": sum(1 for r in rows if r["declared"] and r["measured"]),
    }

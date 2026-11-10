"""Autorizações que valem por um período (uso de imagem, saída sozinho): quem está autorizado num dia.

Vale a assinatura mais recente do estudante entre as autorizações do tipo em vigor. Ela só autoriza se a resposta
for "autorizo" e passar na conferência: selo, sequência e texto atual (``signatures.verify``). Sem assinatura, ou
com qualquer falha, o estudante não está autorizado: o consentimento para crianças precisa ser expresso (LGPD,
art. 14, § 1º), e a resposta antiga sem assinatura eletrônica não conta.
"""

from django.utils import timezone

from . import signatures
from .models import Authorization, AuthorizationSignature


def standing(school, kind, student_ids, day=None):
    """{estudante: {"granted", "sig", "auth", "reason"}} para os estudantes com assinatura numa autorização do
    tipo em vigor; quem não aparece não tem assinatura (não está autorizado)."""
    day = day or timezone.localdate()
    ids = set(student_ids)
    latest = {}
    for auth in (Authorization.objects.filter(school=school, kind=kind, event_date__lte=day, valid_until__gte=day)
                 .exclude(status=Authorization.Status.CANCELED).select_related("school")):
        chain = list(AuthorizationSignature.objects.filter(authorization=auth).order_by("pk"))
        doc = None
        for s in chain:
            if s.student_id in ids and (s.student_id not in latest
                                        or (s.signed_at, s.pk) > (latest[s.student_id][0].signed_at,
                                                                  latest[s.student_id][0].pk)):
                doc = doc or auth.document_hash()
                latest[s.student_id] = (s, auth, chain, doc)
    out = {}
    for sid, (sig, auth, chain, doc) in latest.items():
        check = signatures.verify(sig, chain, doc)
        reason = (None if check["ok"] and sig.answer == "autorizo"
                  else "registro adulterado" if not (check["seal_ok"] and check["chain_ok"])
                  else "assinou uma versão anterior do texto" if not check["doc_ok"]
                  else "a família não autorizou")
        out[sid] = {"granted": reason is None, "sig": sig, "auth": auth, "reason": reason}
    return out


def allowed(student, kind, day=None):
    """A assinatura que autoriza este estudante hoje, ou None."""
    row = standing(student.school, kind, [student.pk], day).get(student.pk)
    return row["sig"] if row and row["granted"] else None

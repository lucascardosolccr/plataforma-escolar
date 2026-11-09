"""Assinatura eletrônica das autorizações de passeio, com as proteções contra fraude num lugar só.

O que impede cada fraude:

- **Outra pessoa usando a conta aberta** (o filho no celular do responsável, o computador da família logado):
  assinar pede a senha de novo e o nome completo de quem assina, conferido com o nome da conta. Cinco senhas
  erradas em 15 minutos bloqueiam a assinatura e avisam o responsável.
- **Assinatura que ninguém percebe:** todos os responsáveis do estudante recebem o aviso com a resposta, quem
  assinou e o código do comprovante. "Não foi você? Avise a escola."
- **Texto trocado depois da assinatura:** a assinatura guarda o resumo (SHA-256) do texto que a família viu. Se a
  escola mudar data, local ou qualquer detalhe, a conferência mostra que aquela assinatura é da versão anterior.
- **Registro alterado no banco:** cada assinatura leva um selo HMAC (chave secreta do servidor) sobre todos os
  campos e sobre o selo da assinatura anterior da mesma autorização. Editar um campo, apagar ou inserir uma
  assinatura no meio quebra a conferência.
- **Formulário reenviado ou montado à mão:** cada tela de assinatura leva um token assinado, de uso único, que
  amarra a pessoa, o estudante e a versão do texto, e vale 30 minutos.

Não é assinatura ICP-Brasil: é assinatura eletrônica com evidências (MP 2.200-2/2001, art. 10, § 2º, e Lei
14.063/2020), que a escola aceita ao adotar a plataforma. O comprovante e a conferência servem de prova.
"""

import hashlib
import hmac
import secrets
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.models import AuditLog, create_audit_log

from .models import AuthorizationResponse, AuthorizationSignature, Notification

TOKEN_SALT = "assinatura-autorizacao"
TOKEN_MAX_AGE = 30 * 60
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
FAILURE_DETAIL = "Assinatura de autorização: senha incorreta"
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford: sem I, L, O, U


def _key():
    return hashlib.sha256(f"{TOKEN_SALT}:{settings.SECRET_KEY}".encode()).digest()


def _payload(f):
    return "|".join(str(x) for x in (
        f["authorization_id"], f["student_id"], f["answer"], f["note"], f["signer_id"], f["signer_name"],
        f["signed_at"].isoformat(), f["ip_address"] or "", f["doc_hash"], f["prev_hash"], f["nonce"]))


def seal_for(fields):
    return hmac.new(_key(), _payload(fields).encode("utf-8"), hashlib.sha256).hexdigest()


def code_from(seal):
    n = int(seal[:13], 16) >> 2  # 50 bits
    return "".join(CODE_ALPHABET[(n >> (5 * i)) & 31] for i in reversed(range(10)))


def normalize_code(raw):
    raw = "".join(ch for ch in (raw or "").upper() if ch.isalnum())
    return raw.replace("O", "0").replace("I", "1").replace("L", "1")[:10]


def normalize_name(name):
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    return " ".join(name.casefold().split())


def name_matches(user, typed):
    """Com nome na conta, o digitado precisa ser o mesmo (sem diferença de acento ou maiúscula). Sem nome na
    conta, pelo menos nome e sobrenome."""
    expected = normalize_name(user.get_full_name())
    got = normalize_name(typed)
    if expected:
        return got == expected
    return len(got.split()) >= 2


# ---------- token de uso único ----------

def issue_token(user, auth, student):
    return signing.dumps({"u": user.pk, "a": auth.pk, "s": student.pk, "d": auth.document_hash(),
                          "n": secrets.token_hex(16)}, salt=TOKEN_SALT)


def read_token(token, user, auth, student):
    """O ``nonce`` do token, ou (None, motivo)."""
    try:
        data = signing.loads(token or "", salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
    except signing.SignatureExpired:
        return None, "A tela de assinatura ficou aberta por mais de 30 minutos. Confira o texto e assine de novo."
    except signing.BadSignature:
        return None, "Não foi possível conferir esta tela de assinatura. Abra a autorização e assine de novo."
    if (data.get("u"), data.get("a"), data.get("s")) != (user.pk, auth.pk, student.pk):
        return None, "Não foi possível conferir esta tela de assinatura. Abra a autorização e assine de novo."
    if data.get("d") != auth.document_hash():
        return None, "A escola alterou o texto desta autorização enquanto você lia. Leia a versão nova e assine."
    if AuthorizationSignature.objects.filter(nonce=data.get("n", "")).exists():
        return None, "Esta tela já foi usada para assinar. Para mudar a resposta, abra a autorização de novo."
    return data["n"], None


# ---------- tentativas de senha ----------

def failures(user):
    since = timezone.now() - FAILURE_WINDOW
    return AuditLog.objects.filter(user=user, action="reject", detail__startswith=FAILURE_DETAIL,
                                   created_at__gte=since).count()


def locked(user):
    return failures(user) >= MAX_FAILURES


def record_failure(request, user, auth):
    from .services import notify

    create_audit_log(user=user, action="reject", request=request, target=auth, detail=f"{FAILURE_DETAIL} ({auth})")
    if failures(user) == MAX_FAILURES:
        notify(user.school, user, Notification.Kind.ANNOUNCEMENT,
               "Assinatura bloqueada por senhas erradas",
               body="Alguém tentou assinar uma autorização com a sua conta e errou a senha 5 vezes. A assinatura "
                    "fica bloqueada por 15 minutos. Se não foi você, troque a senha e avise a escola.",
               url=reverse("communication:authorization_list"), priority=Notification.Priority.HIGH)


# ---------- assinar e conferir ----------

def sign(request, auth, student, user, answer, note, signer_name, nonce):
    from .family_events import family_of
    from .services import notify_many

    ip = request.META.get("REMOTE_ADDR") or None
    with transaction.atomic():  # IMMEDIATE: a assinatura anterior lida aqui é mesmo a última
        prev = AuthorizationSignature.objects.filter(authorization=auth).order_by("-pk").first()
        fields = {"authorization_id": auth.pk, "student_id": student.pk, "answer": answer, "note": note,
                  "signer_id": user.pk, "signer_name": signer_name, "signed_at": timezone.now().replace(microsecond=0),
                  "ip_address": ip, "doc_hash": auth.document_hash(), "prev_hash": prev.seal if prev else "",
                  "nonce": nonce}
        document = auth.document_text()
        seal = seal_for(fields)
        sig = AuthorizationSignature.objects.create(
            **fields, document=document, user_agent=request.META.get("HTTP_USER_AGENT", "")[:200], seal=seal, code=code_from(seal))
        resp, created = AuthorizationResponse.objects.update_or_create(
            authorization=auth, student=student,
            defaults={"answer": answer, "note": note, "answered_by": user, "signature": sig})
        create_audit_log(user=user, action="create" if created else "update", request=request, target=resp,
                         detail=f"Assinou '{sig.get_answer_display()}': {student.full_name} em '{auth.title}' "
                                f"(comprovante {sig.display_code})" + (f" (obs.: {note})" if note else ""))
    when = timezone.localtime(sig.signed_at)
    # Todos os responsáveis ficam sabendo, inclusive quem assinou: assinatura feita por outra pessoa aparece.
    notify_many(auth.school, family_of(student, include_student=False), Notification.Kind.ANNOUNCEMENT,
                f"Autorização assinada: {student.first_name} — {sig.get_answer_display().lower()}",
                body=f"{auth.title}. Assinada por {signer_name} em {when:%d/%m/%Y às %H:%M}. Comprovante "
                     f"{sig.display_code}. Não foi você? Avise a escola.",
                url=reverse("communication:authorization_receipt", args=[sig.code]), student=student,
                dedupe_key=f"assinatura:{sig.pk}", priority=Notification.Priority.HIGH)
    return sig


def verify(sig, chain=None, doc_hash=None):
    """Conferência de uma assinatura: selo, encadeamento, texto e se é a resposta que vale hoje."""
    fields = {f: getattr(sig, f) for f in ("authorization_id", "student_id", "answer", "note", "signer_id",
                                           "signer_name", "signed_at", "ip_address", "doc_hash", "prev_hash",
                                           "nonce")}
    # O texto guardado precisa bater com o resumo selado: trocar a cópia do texto também aparece.
    seal_ok = (hmac.compare_digest(seal_for(fields), sig.seal) and sig.code == code_from(sig.seal)
               and hashlib.sha256(sig.document.encode("utf-8")).hexdigest() == sig.doc_hash)
    if chain is None:
        chain = list(AuthorizationSignature.objects.filter(authorization_id=sig.authorization_id).order_by("pk"))
    idx = next((i for i, s in enumerate(chain) if s.pk == sig.pk), None)
    chain_ok = idx is not None and sig.prev_hash == (chain[idx - 1].seal if idx else "")
    doc_ok = sig.doc_hash == (doc_hash or sig.authorization.document_hash())
    later = [s for s in chain if s.student_id == sig.student_id and s.pk > sig.pk]
    return {"ok": seal_ok and chain_ok and doc_ok, "seal_ok": seal_ok, "chain_ok": chain_ok, "doc_ok": doc_ok,
            "current": not later, "replaced_by": later[-1] if later else None}


def verify_all(auth):
    """{assinatura: conferência} de todas as assinaturas da autorização, e quantas falharam."""
    chain = list(AuthorizationSignature.objects.filter(authorization=auth).order_by("pk"))
    doc = auth.document_hash()
    results = {s.pk: verify(s, chain, doc) for s in chain}
    return results, sum(1 for r in results.values() if not (r["seal_ok"] and r["chain_ok"]))


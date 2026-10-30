"""Importação de estudantes por planilha (.xlsx ou .csv), sem dependência nova.

Fluxo: ``read_table`` lê o arquivo → ``validate_rows`` confere cada linha
contra o banco (sem gravar nada) → a secretaria vê a prévia e escolhe o
tratamento → ``apply_rows`` revalida e grava tudo numa transação.

Regras que não mudam:

- nada sobrescreve dado em silêncio: cada alteração em aluno já cadastrado
  aparece na prévia, campo a campo, e só é aplicada no modo "atualizar";
- célula vazia nunca apaga dado existente;
- aluno já cadastrado é reconhecido pelo código do aluno ou, sem código, por
  nome + sobrenome + data de nascimento exatos (nunca por semelhança);
- matrícula ativa em outra turma não é trocada pela planilha (use Transferir);
- reenviar a mesma planilha não duplica ninguém.

O .xlsx é um ZIP de XML (Office Open XML). Lido com ``zipfile`` e
``xml.etree``: o expat do Python não resolve entidades externas e, desde a
3.7.1, limita expansão de entidades; o tamanho descompactado é limitado aqui
para barrar "bomba de ZIP".
"""

import csv
import io
import json
import re
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

from django.db import transaction
from django.utils import timezone

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_UNZIPPED_BYTES = 40 * 1024 * 1024
MAX_ROWS = 5000

# (chave, cabeçalho no modelo, obrigatório, descrição, exemplo)
COLUMNS = [
    ("codigo", "Código do aluno", False,
     "RA ou código usado pela escola. Recomendado: com ele a planilha pode ser reenviada sem "
     "duplicar ninguém e as fotos podem ser enviadas em lote (arquivo 2026001.jpg).", "2026001"),
    ("nome", "Nome", True, "Primeiro nome (ou nomes) do estudante.", "Ana Clara"),
    ("sobrenome", "Sobrenome", False, "Sobrenome completo.", "Souza Lima"),
    ("nascimento", "Data de nascimento", True, "No formato dia/mês/ano: 25/03/2016.", "25/03/2016"),
    ("turma", "Turma", False,
     "Nome exato da turma no ano letivo atual, como aparece em Turmas (ex.: 5º A). "
     "Em branco: cria só a ficha, sem matrícula.", "5º A"),
    ("matricula", "Número de matrícula", False, "Número da matrícula nesta turma. Não pode repetir.", "M-2026-0001"),
    ("situacao", "Situação", False, "ativo, transferido, concluido ou inativo. Em branco: ativo.", "ativo"),
    ("responsavel", "Responsável", False, "Nome de quem a escola deve procurar.", "Maria Souza"),
    ("telefone", "Telefone do responsável", False, "Com DDD. Obrigatório se houver responsável sem usuário.",
     "(11) 98888-7777"),
    ("usuario_responsavel", "Usuário do responsável", False,
     "Se a família já tem conta na plataforma: o usuário dela. O vínculo é criado já aprovado.", ""),
]
KEYS = [c[0] for c in COLUMNS]
LABELS = {c[0]: c[1] for c in COLUMNS}
REQUIRED = [c[0] for c in COLUMNS if c[2]]

STATUS_VALUES = {"ativo", "transferido", "concluido", "inativo"}
# Campos da ficha que a planilha pode preencher/alterar: chave → atributo.
STUDENT_FIELDS = {
    "codigo": "code", "nome": "first_name", "sobrenome": "last_name", "nascimento": "birth_date",
    "situacao": "status", "responsavel": "guardian_contact_name", "telefone": "guardian_contact_phone",
}


class ImportFileError(Exception):
    """Problema no arquivo inteiro (formato, tamanho, colunas)."""


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = re.sub(r"\(.*?\)|\*", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


ALIASES = {_norm(c[1]): c[0] for c in COLUMNS}
ALIASES.update({
    "codigo": "codigo", "ra": "codigo", "codigo do estudante": "codigo",
    "nome do aluno": "nome", "nome do estudante": "nome", "primeiro nome": "nome",
    "nascimento": "nascimento", "data nascimento": "nascimento", "data de nasc": "nascimento",
    "numero da matricula": "matricula", "matricula": "matricula", "n de matricula": "matricula",
    "status": "situacao", "nome do responsavel": "responsavel", "telefone": "telefone",
    "usuario responsavel": "usuario_responsavel", "usuario do responsavel na plataforma": "usuario_responsavel",
})


# --------------------------------------------------------------------------
# Leitura do arquivo


def read_table(uploaded):
    """Devolve (cabeçalhos originais, linhas como dict chave→texto, avisos)."""
    name = (uploaded.name or "").lower()
    if uploaded.size > MAX_FILE_BYTES:
        raise ImportFileError("O arquivo passa de 5 MB. Divida a planilha em partes menores.")
    data = uploaded.read()
    if name.endswith(".xlsx"):
        matrix = _read_xlsx(data)
    elif name.endswith(".csv"):
        matrix = _read_csv(data)
    else:
        raise ImportFileError("Envie uma planilha .xlsx (Excel) ou .csv.")
    matrix = [row for row in matrix if any(str(v).strip() for v in row)]
    if not matrix:
        raise ImportFileError("A planilha está vazia.")
    headers = [str(h).strip() for h in matrix[0]]
    keys, warnings = [], []
    for h in headers:
        key = ALIASES.get(_norm(h))
        if h and not key:
            warnings.append(f"Coluna “{h}” não faz parte do modelo e foi ignorada.")
        keys.append(key if key not in keys else None)
    missing = [LABELS[k] for k in REQUIRED if k not in keys]
    if missing:
        raise ImportFileError(
            "Faltam colunas obrigatórias: " + ", ".join(missing)
            + ". Baixe o modelo e mantenha os cabeçalhos da primeira linha."
        )
    body = matrix[1:]
    if len(body) > MAX_ROWS:
        raise ImportFileError(f"A planilha tem {len(body)} linhas; o limite por envio é {MAX_ROWS}.")
    rows = []
    for values in body:
        row = {k: "" for k in KEYS}
        for i, key in enumerate(keys):
            if key and i < len(values):
                row[key] = _clean(values[i])
        rows.append(row)
    return headers, rows, warnings


def _clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _read_csv(data):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if "\x00" in text:
        raise ImportFileError("O arquivo .csv parece binário. Salve como CSV ou envie o .xlsx.")
    sample = text[:4096]
    delim = max((";", ",", "\t"), key=sample.count)
    return list(csv.reader(io.StringIO(text), delimiter=delim))


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _read_xlsx(data):
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ImportFileError("O arquivo não é uma planilha .xlsx válida.")
    with zf:
        if sum(i.file_size for i in zf.infolist()) > MAX_UNZIPPED_BYTES:
            raise ImportFileError("A planilha descompactada é grande demais.")
        names = set(zf.namelist())
        try:
            wb = ET.fromstring(zf.read("xl/workbook.xml"))
            first = wb.find("m:sheets/m:sheet", _NS)
            rid = first.get(_REL)
            rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            target = next(r.get("Target") for r in rels if r.get("Id") == rid)
        except (KeyError, StopIteration, AttributeError, ET.ParseError):
            raise ImportFileError("Não foi possível ler a primeira aba da planilha.")
        path = target.lstrip("/")
        path = path if path.startswith("xl/") else "xl/" + path
        shared = []
        if "xl/sharedStrings.xml" in names:
            for si in ET.fromstring(zf.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{_NS['m']}}}t")))
        try:
            sheet = ET.fromstring(zf.read(path))
        except (KeyError, ET.ParseError):
            raise ImportFileError("Não foi possível ler a primeira aba da planilha.")
    matrix = []
    for row in sheet.iter(f"{{{_NS['m']}}}row"):
        values = {}
        for c in row.findall("m:c", _NS):
            col = _col_index(c.get("r", ""))
            if col is None or col > 60:
                continue
            kind = c.get("t")
            v = c.find("m:v", _NS)
            if kind == "s" and v is not None:
                text = shared[int(v.text)] if v.text and int(v.text) < len(shared) else ""
            elif kind == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{_NS['m']}}}t"))
            elif v is not None and v.text is not None:
                text = v.text
                if kind in (None, "n"):
                    num = float(text)
                    text = int(num) if num.is_integer() else num
            else:
                text = ""
            values[col] = text
        if values:
            matrix.append([values.get(i, "") for i in range(max(values) + 1)])
        if len(matrix) > MAX_ROWS + 1:
            break
    return matrix


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref or "")
    if not letters:
        return None
    n = 0
    for ch in letters.group():
        n = n * 26 + ord(ch) - 64
    return n - 1


# --------------------------------------------------------------------------
# Validação


def parse_date(text):
    text = str(text or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4,5}(\.0+)?", text):  # número de série do Excel
        serial = int(float(text))
        if 1 < serial < 80000:
            return date(1899, 12, 30) + timedelta(days=serial)
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _key(first, last, birth):
    return (_norm(first), _norm(last), birth.isoformat() if birth else "")


def validate_rows(school, rows):
    """Confere cada linha sem gravar. Devolve lista de resultados (dicts)."""
    from apps.academics.models import ClassGroup, SchoolYear
    from apps.core.models import Role, User

    from .models import Enrollment, Student

    current_year = SchoolYear.objects.filter(school=school, is_current=True).first()
    classes = {}
    cg_qs = ClassGroup.objects.filter(school=school)
    if current_year:
        cg_qs = cg_qs.filter(school_year=current_year)
    for cg in cg_qs:
        classes.setdefault(_norm(cg.name), []).append(cg)

    students = list(Student.objects.filter(school=school))
    by_code = {s.code: s for s in students if s.code}
    by_name = {}
    for s in students:
        by_name.setdefault(_key(s.first_name, s.last_name, s.birth_date), []).append(s)
    used_numbers = dict(
        Enrollment.objects.filter(school=school).exclude(enrollment_number="")
        .values_list("enrollment_number", "student_id")
    )
    active = {}
    if current_year:
        for e in Enrollment.objects.filter(school=school, school_year=current_year, status="ativo") \
                .select_related("class_group"):
            active[e.student_id] = e
    guardians = {
        u.username.lower(): u
        for u in User.objects.filter(school=school, role=Role.RESPONSAVEL.value, is_active=True)
    }

    seen_codes, seen_names, seen_numbers = {}, {}, {}
    today = timezone.localdate()
    results = []
    for i, raw in enumerate(rows, start=2):  # linha 1 é o cabeçalho
        errors, changes = [], []
        nome = raw.get("nome", "")
        birth = parse_date(raw.get("nascimento"))
        code = raw.get("codigo", "")
        if not nome:
            errors.append("Nome em branco.")
        if not raw.get("nascimento"):
            errors.append("Data de nascimento em branco.")
        elif birth is None:
            errors.append(f"Data de nascimento inválida: “{raw['nascimento']}” (use dia/mês/ano).")
        elif birth > today:
            errors.append("Data de nascimento no futuro.")
        elif birth.year < today.year - 100:
            errors.append("Data de nascimento improvável (mais de 100 anos).")
        if code and not re.fullmatch(r"[A-Za-z0-9._/-]{1,30}", code):
            errors.append("Código do aluno com caracteres inválidos (use letras, números, ponto, hífen).")
        if code:
            if code in seen_codes:
                errors.append(f"Código repetido na planilha (também na linha {seen_codes[code]}).")
            seen_codes.setdefault(code, i)
        name_key = _key(nome, raw.get("sobrenome"), birth)
        if nome and birth:
            if name_key in seen_names and not code:
                errors.append(f"Mesmo nome e nascimento da linha {seen_names[name_key]}.")
            seen_names.setdefault(name_key, i)
        status = _norm(raw.get("situacao"))
        if status and status not in STATUS_VALUES:
            errors.append(f"Situação “{raw['situacao']}” inválida (use ativo, transferido, concluido ou inativo).")
        if raw.get("responsavel") and not raw.get("telefone") and not raw.get("usuario_responsavel"):
            errors.append("Responsável sem identificação suficiente: informe o telefone ou o usuário dele.")
        if raw.get("telefone") and not raw.get("responsavel") and not raw.get("usuario_responsavel"):
            errors.append("Telefone sem o nome do responsável.")
        if raw.get("telefone") and len(re.sub(r"\D", "", raw["telefone"])) < 8:
            errors.append("Telefone do responsável incompleto.")
        guardian = None
        if raw.get("usuario_responsavel"):
            guardian = guardians.get(raw["usuario_responsavel"].lower())
            if guardian is None:
                errors.append(f"Usuário do responsável “{raw['usuario_responsavel']}” não encontrado nesta escola.")

        # Já cadastrado?
        existing = by_code.get(code) if code else None
        if existing is None and nome and birth:
            matches = by_name.get(name_key, [])
            if len(matches) > 1:
                errors.append("Há mais de um aluno cadastrado com este nome e nascimento: informe o código.")
            elif matches:
                existing = matches[0]
                if code and existing.code and existing.code != code:
                    errors.append(
                        f"Aluno já cadastrado com outro código ({existing.code}). Confira antes de importar."
                    )
        if existing is not None:
            for key, attr in STUDENT_FIELDS.items():
                new = raw.get(key, "")
                if not new:
                    continue  # vazio nunca apaga
                if key == "nascimento":
                    new = birth
                elif key == "situacao":
                    new = status
                old = getattr(existing, attr)
                if new and new != old:
                    show = (lambda v: v.strftime("%d/%m/%Y") if isinstance(v, date) else (v or "—"))
                    changes.append({"field": LABELS[key], "old": show(old), "new": show(new)})

        cg = None
        turma = raw.get("turma", "")
        if turma:
            found = classes.get(_norm(turma), [])
            if not current_year:
                errors.append("Não há ano letivo marcado como atual: cadastre-o antes de matricular.")
            elif not found:
                errors.append(f"Turma “{turma}” não existe no ano letivo {current_year}.")
            else:
                cg = found[0]
                prev = active.get(existing.pk) if existing else None
                if prev and prev.class_group_id != cg.pk:
                    errors.append(
                        f"Já matriculado na turma {prev.class_group.name}. Para mudar, use “Transferir” "
                        "na lista de matrículas."
                    )
        number = raw.get("matricula", "")
        if number:
            if len(number) > 20:
                errors.append("Número de matrícula com mais de 20 caracteres.")
            if number in seen_numbers:
                errors.append(f"Número de matrícula repetido na planilha (linha {seen_numbers[number]}).")
            seen_numbers.setdefault(number, i)
            owner = used_numbers.get(number)
            if owner and (existing is None or owner != existing.pk):
                errors.append(f"Número de matrícula {number} já pertence a outro aluno.")
            if not turma:
                errors.append("Número de matrícula sem turma.")

        if errors:
            state = "erro"
        elif existing is None:
            state = "novo"
        elif changes or (cg and not active.get(existing.pk)) or (
            guardian and not existing.guardian_links.filter(guardian=guardian).exists()
        ):
            state = "alterar"
        else:
            state = "igual"
        results.append({
            "line": i,
            "raw": raw,
            "status": state,
            "errors": errors,
            "changes": changes,
            "student_id": existing.pk if existing else None,
            "label": f"{nome} {raw.get('sobrenome', '')}".strip() or "(sem nome)",
            "class_id": cg.pk if cg else None,
            "enroll": bool(cg and (existing is None or not active.get(existing.pk))),
        })
    return results


def summarize(results):
    out = {"total": len(results), "novo": 0, "alterar": 0, "igual": 0, "erro": 0}
    for r in results:
        out[r["status"]] += 1
    return out


# --------------------------------------------------------------------------
# Gravação


def apply_rows(batch, user, request=None):
    """Revalida e grava a prévia de ``batch`` numa transação única.

    Revalidar evita gravar algo que mudou entre a prévia e a confirmação
    (outro cadastro feito no meio tempo vira "já cadastrado", não duplicata).
    """
    from apps.academics.models import ClassGroup
    from apps.core.models import User, create_audit_log

    from .models import Enrollment, GuardianLink, ImportBatch, Student

    stored = json.loads(batch.rows or "[]")
    results = validate_rows(batch.school, [r["raw"] for r in stored])
    update = batch.mode == ImportBatch.Mode.UPDATE
    counts = {"created": 0, "updated": 0, "skipped": 0, "error": 0}
    with transaction.atomic():
        for r in results:
            raw = r["raw"]
            if r["status"] == "erro":
                counts["error"] += 1
                continue
            if r["status"] == "igual" or (r["status"] == "alterar" and not update):
                r["outcome"] = "ignorado" if r["status"] == "igual" else "ignorado (modo só novos)"
                counts["skipped"] += 1
                continue
            birth = parse_date(raw["nascimento"])
            if r["status"] == "novo":
                st = Student.objects.create(
                    school=batch.school, first_name=raw["nome"], last_name=raw.get("sobrenome", ""),
                    birth_date=birth, code=raw.get("codigo", ""),
                    status=_norm(raw.get("situacao")) or "ativo",
                    guardian_contact_name=raw.get("responsavel", ""),
                    guardian_contact_phone=raw.get("telefone", ""),
                )
                r["outcome"] = "cadastrado"
                counts["created"] += 1
            else:
                st = Student.objects.get(pk=r["student_id"], school=batch.school)
                for key, attr in STUDENT_FIELDS.items():
                    value = raw.get(key, "")
                    if not value:
                        continue
                    if key == "nascimento":
                        value = birth
                    elif key == "situacao":
                        value = _norm(value)
                    setattr(st, attr, value)
                st.save()
                r["outcome"] = "atualizado"
                counts["updated"] += 1
            r["student_id"] = st.pk
            if r["enroll"] and r["class_id"]:
                cg = ClassGroup.objects.get(pk=r["class_id"], school=batch.school)
                Enrollment.objects.create(
                    school=batch.school, student=st, class_group=cg, school_year=cg.school_year,
                    enrollment_number=raw.get("matricula", ""), status="ativo",
                )
            if raw.get("usuario_responsavel"):
                guardian = User.objects.get(username__iexact=raw["usuario_responsavel"], school=batch.school)
                GuardianLink.objects.get_or_create(
                    school=batch.school, guardian=guardian, student=st,
                    defaults={"status": "aprovado", "requested_by": user, "validated_by": user,
                              "validated_at": timezone.now()},
                )
        batch.rows = json.dumps(results, ensure_ascii=False, default=str)
        batch.created_count = counts["created"]
        batch.updated_count = counts["updated"]
        batch.skipped_count = counts["skipped"]
        batch.error_count = counts["error"]
        batch.status = ImportBatch.Status.DONE
        batch.finished_at = timezone.now()
        batch.save()
        create_audit_log(
            user=user, action="create", request=request, target=batch,
            detail=(
                f"Importou a planilha {batch.filename}: {counts['created']} cadastrados, "
                f"{counts['updated']} atualizados, {counts['skipped']} ignorados, "
                f"{counts['error']} com erro"
            ),
        )
    return counts


# --------------------------------------------------------------------------
# Planilhas para baixar


def template_xlsx():
    from apps.analytics import xlsx

    header = [f"{c[1]}{' *' if c[2] else ''}" for c in COLUMNS]
    instructions = [["Coluna", "Obrigatória", "Como preencher", "Exemplo"]] + [
        [c[1], "Sim" if c[2] else "Não", c[3], c[4]] for c in COLUMNS
    ] + [
        [],
        ["Orientações gerais", "", "Preencha a aba “Alunos” a partir da linha 2. Não mude os cabeçalhos.", ""],
        ["", "", "Datas no formato dia/mês/ano. Uma linha por aluno.", ""],
        ["", "", "Célula vazia nunca apaga um dado já cadastrado.", ""],
        ["", "", "Aluno já cadastrado é reconhecido pelo código ou por nome + sobrenome + nascimento.", ""],
        ["", "", "Fotografias não vão na planilha: envie depois em “Fotos em lote”, com o código no nome do arquivo.", ""],
    ]
    example = [header, [c[4] for c in COLUMNS],
               ["2026002", "Bruno", "Alves", "02/11/2015", "5º A", "M-2026-0002", "", "João Alves", "(11) 97777-6666", ""]]
    return xlsx.build([("Alunos", [header]), ("Instruções", instructions), ("Exemplo", example)])


def rejected_xlsx(batch):
    from apps.analytics import xlsx

    results = json.loads(batch.rows or "[]")
    header = [c[1] for c in COLUMNS] + ["Linha original", "Motivo"]
    rows = [header]
    for r in results:
        if r.get("status") == "erro":
            rows.append([r["raw"].get(k, "") for k in KEYS] + [r["line"], " ".join(r["errors"])])
    return xlsx.build([("Rejeitados", rows)])

"""Varredura medida da plataforma: por perfil, segue os links internos e anota situação, tempo, consultas,
tamanho e redirecionamentos com mensagem de erro de cada página.

Rode SÓ numa cópia do banco (nunca no real), com as contas demo.* da escola de demonstração:

    set PYTHONPATH=<pasta com as configurações da cópia>
    set DJANGO_SETTINGS_MODULE=<configurações da cópia>
    .venv/Scripts/python.exe manage.py shell -c "exec(open('tools/varredura_paginas.py', encoding='utf-8').read())"

Usuários pela variável VARREDURA_USUARIOS (separados por vírgula); resultado em JSON em VARREDURA_SAIDA.
Em 02/11/2026 achou: link para 403, "Editar" que só devolvia erro, formulário com 120 consultas e
frequência de 195 KB (ver docs/VARREDURA_DE_MELHORIAS_2026-11-02.md).
"""
import os
import json
import re
import time
from collections import Counter

from django.conf import settings
from django.db import connection, reset_queries
from django.test import Client
from django.test.utils import setup_test_environment

from apps.core.models import User

setup_test_environment()
settings.ALLOWED_HOSTS = ["testserver"]
settings.DEBUG = True  # para contar consultas
OUT = os.environ.get("VARREDURA_SAIDA", "varredura.json")
SKIP = ("logout", "exportar", ".csv", ".xlsx", "/static/", "/media/", "anexo", "/foto", "download", "baixar", "imprimir=")
USERS = os.environ.get("VARREDURA_USUARIOS", "demo.direcao,demo.coordenacao,demo.secretaria,demo.prof1,demo.prof2,"
                       "demo.resp57,demo.aluna145,admin").split(",")
LIMIT = 220


def norm(url):
    # agrupa páginas iguais com ids diferentes para não varrer 50 fichas iguais
    return re.sub(r"/\d+/", "/N/", url.split("?")[0])


rows = []
for name in USERS:
    u = User.objects.filter(username=name, is_active=True).first()
    if not u:
        continue
    c = Client(raise_request_exception=False)
    c.force_login(u)
    seen, shapes, queue = set(), Counter(), [("/", 0)]
    while queue and len(seen) < LIMIT:
        url, depth = queue.pop(0)
        if url in seen or shapes[norm(url)] >= 3:
            continue
        seen.add(url)
        shapes[norm(url)] += 1
        reset_queries()
        t = time.perf_counter()
        r = c.get(url)
        ms = (time.perf_counter() - t) * 1000
        msgs = []
        if r.status_code == 302:
            from django.contrib.messages import WARNING, get_messages
            msgs = [str(m) for m in get_messages(r.wsgi_request) if m.level >= WARNING]
        rows.append({"user": name, "url": url, "status": r.status_code, "ms": round(ms), "q": len(connection.queries), "kb": round(len(r.content)/1024), "msgs": msgs})
        if depth < 3 and r.status_code == 200 and "text/html" in r.get("Content-Type", ""):
            for h in re.findall(r'href="(/[^"#]*)"', r.content.decode("utf-8", "ignore")):
                h = h.replace("&amp;", "&")
                if not any(x in h for x in SKIP) and h not in seen:
                    queue.append((h, depth + 1))
json.dump(rows, open(OUT, "w", encoding="utf-8"))
st = Counter(r["status"] for r in rows)
print("paginas", len(rows), dict(st))
print("ERROS", [(r["user"], r["url"], r["status"]) for r in rows if r["status"] >= 400][:30])
print("TOP CONSULTAS")
for r in sorted(rows, key=lambda r: -r["q"])[:10]:
    print(r["q"], r["ms"], r["user"], r["url"])
print("REDIRECIONA COM ERRO", [(r["user"], r["url"], r["msgs"][0][:60]) for r in rows if r["msgs"]])
print("TOP TAMANHO", [(r["kb"], r["user"], r["url"]) for r in sorted(rows, key=lambda r: -r["kb"])[:12]])
print("TOP TEMPO")
for r in sorted(rows, key=lambda r: -r["ms"])[:20]:
    print(r["ms"], r["q"], r["user"], r["url"])

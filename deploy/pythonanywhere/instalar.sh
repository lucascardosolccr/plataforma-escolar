#!/bin/bash
# Primeira instalação no PythonAnywhere (conta gratuita). Rode no console Bash do PythonAnywhere:
#     bash ~/plataforma-escolar/deploy/pythonanywhere/instalar.sh
# Pode rodar de novo sem estragar nada: não recria o .env nem apaga o banco.
set -euo pipefail

APP="$HOME/plataforma-escolar"
VENV="$HOME/.virtualenvs/escola"
cd "$APP"

PY=""
for v in python3.12 python3.13 python3.11 python3.10; do
  if command -v "$v" >/dev/null 2>&1; then PY="$v"; break; fi
done
[ -n "$PY" ] || { echo "Nenhum Python 3.10 a 3.13 encontrado."; exit 1; }
echo "== Python: $PY"

if [ ! -x "$VENV/bin/python" ]; then
  echo "== Criando o ambiente em $VENV"
  "$PY" -m venv "$VENV"
fi
echo "== Instalando as dependências (Django, argon2, Pillow)"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt

if [ ! -f .env ]; then
  echo "== Criando o .env"
  HOSTS="$USER.pythonanywhere.com,$USER.eu.pythonanywhere.com"
  cat > .env <<EOF
DJANGO_DEBUG=0
DJANGO_ALLOWED_HOSTS=$HOSTS
DJANGO_SSL=1
DJANGO_SSL_REDIRECT=0
DJANGO_PROXY_SSL=1
DJANGO_DAILY_JOBS_BACKGROUND=0
DJANGO_HOSPEDAGEM=PythonAnywhere, com servidores na União Europeia
EOF
  chmod 600 .env
  echo "   Endereços aceitos: $HOSTS"
  echo "   Conta nos EUA (www.pythonanywhere.com)? Troque o texto de DJANGO_HOSPEDAGEM no .env."
else
  echo "== .env já existe: mantido"
fi

echo "== Preparando o banco (a primeira vez leva cerca de 30 segundos)"
if [ -f db.sqlite3 ]; then "$VENV/bin/python" manage.py backupdb --manter 5; fi
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py check --deploy --fail-level ERROR

chmod 600 .secret_key db.sqlite3 2>/dev/null || true
mkdir -p media logs && chmod 700 media logs backups 2>/dev/null || true

echo
echo "== Pronto. Falta, uma única vez:"
echo "   1. Criar a conta de administração:"
echo "      $VENV/bin/python manage.py initadmin --school-code SUAESCOLA --school-name \"Nome da Escola\""
echo "   2. Configurar a aba Web (ver LEIA-ME.md, passo 5) e clicar em Reload."

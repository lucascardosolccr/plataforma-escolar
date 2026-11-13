#!/bin/bash
# Atualiza o codigo no PythonAnywhere a partir do GitHub (fluxo por repositorio):
#     bash ~/plataforma-escolar/deploy/pythonanywhere/atualizar-git.sh
# Faz backup do banco antes, puxa o codigo novo com "git pull" (banco, .env, chave, fotos e backups
# ficam, porque estao no .gitignore) e recarrega o site. Use este, e nao o atualizar.sh, quando o
# codigo foi clonado do GitHub.
set -euo pipefail

APP="$HOME/plataforma-escolar"
VENV="$HOME/.virtualenvs/escola"
cd "$APP"

echo "== Backup do banco antes de atualizar"
"$VENV/bin/python" manage.py backupdb --manter 5

echo "== Puxando o codigo do GitHub"
git pull --ff-only

echo "== Dependencias, migracoes e conferencia"
"$VENV/bin/pip" install --quiet -r requirements.txt
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py check --deploy --fail-level ERROR

WSGI="$(ls /var/www/*_wsgi.py 2>/dev/null | head -1 || true)"
if [ -n "$WSGI" ]; then touch "$WSGI"; echo "== Site recarregado ($WSGI)"; else echo "== Clique em Reload na aba Web."; fi
echo "== Atualizado."

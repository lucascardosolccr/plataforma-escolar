#!/bin/bash
# Rotina mensal no PythonAnywhere (a conta gratuita não agenda tarefas). Rode no dia de renovar o site:
#     bash ~/plataforma-escolar/deploy/pythonanywhere/manutencao.sh
# Depois baixe o backup mais novo da pasta backups/ (aba Files) e guarde fora da hospedagem.
set -euo pipefail

APP="$HOME/plataforma-escolar"
PY="$HOME/.virtualenvs/escola/bin/python"
cd "$APP"

echo "== Backup do banco"
"$PY" manage.py backupdb --manter 5
echo "== Retenção (LGPD): pré-cadastros recusados ou cancelados há mais de 180 dias"
"$PY" manage.py purgeapplications
echo "== Retenção (LGPD): relatório dos dados operacionais antigos (nunca registro escolar)"
"$PY" manage.py retencao   # só relata; para apagar o que ela listar, rode de novo com --aplicar

echo
echo "== Espaço usado (o limite da conta gratuita é 512 MB):"
du -sh "$APP/db.sqlite3" "$APP/media" "$APP/backups" "$HOME/.virtualenvs/escola" 2>/dev/null || true
du -sh "$HOME" 2>/dev/null || true
echo
echo "Agora: aba Files → plataforma-escolar/backups → baixe o arquivo mais novo."
echo "E na aba Web: clique no botão \"Run until ... from today\" para o site não sair do ar."

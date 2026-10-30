@echo off
chcp 65001 >nul
title Plataforma Escolar Integrada
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo.
  echo  Ambiente nao encontrado ^(pasta .venv^).
  echo  Siga a secao "Instalacao" do README.md e rode este arquivo novamente.
  echo.
  pause
  exit /b 1
)

rem Copia de seguranca a cada inicio, ANTES de atualizar o banco: se uma
rem atualizacao der errado, a copia de agora esta em backups\ (guarda as 10
rem mais recentes). A falha no backup nao impede o uso, mas avisa.
if exist "db.sqlite3" (
  echo Fazendo copia de seguranca do banco de dados...
  ".venv\Scripts\python.exe" manage.py backupdb
  if errorlevel 1 (
    echo.
    echo  ATENCAO: a copia de seguranca falhou. Veja a mensagem acima.
    echo  A plataforma vai abrir mesmo assim; avise o responsavel tecnico.
    echo.
  )
)

echo Aplicando atualizacoes do banco de dados...
".venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
  echo.
  echo  Falha ao preparar o banco de dados. Veja a mensagem acima.
  pause
  exit /b 1
)

echo.
echo ================================================================
echo  Plataforma Escolar Integrada
echo ----------------------------------------------------------------
echo  Neste computador, acesse:  http://127.0.0.1:8000/
echo  Em outros computadores da rede local, acesse:
echo     http://SEU-IP-AQUI:8000/  ^(veja o IP com o comando ipconfig^)
echo ----------------------------------------------------------------
echo  IMPORTANTE: mantenha esta janela aberta enquanto usar o sistema.
echo  Para encerrar, feche esta janela ou pressione Ctrl+C.
echo ================================================================
echo.

".venv\Scripts\python.exe" manage.py runserver 0.0.0.0:8000
pause

"""Backup e restauração do banco SQLite.

Copiar `db.sqlite3` com o servidor no ar pode capturar o arquivo no meio de uma
transação e gerar um backup corrompido — e a corrupção só aparece na hora de
restaurar, que é o pior momento possível. A API de backup do SQLite copia
página por página respeitando o bloqueio, então o resultado é sempre um banco
íntegro.

A lógica vive aqui, separada do comando, para poder ser exercitada com
arquivos reais: na suíte o banco do Django é em memória e não há arquivo para
copiar.
"""

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


class BackupError(Exception):
    """Falha no backup ou na verificação do arquivo gerado."""


def integrity_of(path):
    """Resultado do PRAGMA integrity_check, ou a falha ao abrir o arquivo."""
    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as exc:
        return f"não foi possível abrir: {exc}"
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        return f"não é um banco SQLite válido: {exc}"
    finally:
        conn.close()


def table_count(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        conn.close()


def backup_sqlite(source, dest_dir, prefix="db"):
    """Grava um backup íntegro de ``source`` em ``dest_dir``.

    Devolve o caminho do arquivo criado. Levanta ``BackupError`` se o arquivo
    gerado não passar na verificação de integridade — e nesse caso o descarta,
    para nunca deixar um backup inútil parecendo válido.
    """
    source = Path(source)
    if not source.exists():
        raise BackupError(f"Banco não encontrado em {source}.")

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = dest_dir / f"{prefix}-{stamp}.sqlite3"
    # Se dois backups caírem no mesmo segundo, não sobrescreve o primeiro.
    n = 2
    while dest.exists():
        dest = dest_dir / f"{prefix}-{stamp}-{n}.sqlite3"
        n += 1

    # Somente leitura na origem: o backup nunca pode alterar o banco vivo.
    src_conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    except sqlite3.Error as exc:
        dest.unlink(missing_ok=True)
        raise BackupError(f"Falha ao copiar o banco: {exc}") from exc
    finally:
        src_conn.close()

    resultado = integrity_of(dest)
    if resultado != "ok":
        dest.unlink(missing_ok=True)
        raise BackupError(
            f"O backup foi gerado mas falhou na integridade ({resultado}); "
            "o arquivo foi descartado."
        )
    return dest


def restore_sqlite(backup, target):
    """Restaura ``backup`` sobre ``target``.

    Confere a integridade do backup ANTES de tocar no banco atual, e guarda o
    atual ao lado com sufixo ``.antes-da-restauracao``. Restaurar de um arquivo
    corrompido sobre o único banco bom é a maneira mais fácil de transformar um
    incidente recuperável em perda definitiva.
    """
    backup = Path(backup)
    target = Path(target)
    if not backup.exists():
        raise BackupError(f"Backup não encontrado em {backup}.")

    resultado = integrity_of(backup)
    if resultado != "ok":
        raise BackupError(
            f"O backup não passou na verificação ({resultado}); "
            "a restauração foi interrompida e o banco atual não foi alterado."
        )

    anterior = None
    if target.exists():
        anterior = target.with_suffix(target.suffix + ".antes-da-restauracao")
        shutil.copy2(target, anterior)

    shutil.copy2(backup, target)
    return anterior


def rotate_backups(dest_dir, keep):
    """Conserva os ``keep`` mais recentes. Sem isto a pasta cresce sem limite."""
    if keep <= 0:
        return []
    arquivos = sorted(
        Path(dest_dir).glob("db-*.sqlite3"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removidos = arquivos[keep:]
    for p in removidos:
        p.unlink(missing_ok=True)
    return removidos

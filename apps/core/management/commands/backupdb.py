"""Backup do banco pela linha de comando.

A lógica está em apps/core/backup.py; aqui só se liga nas configurações.
"""

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.core.backup import (
    BackupError,
    backup_sqlite,
    restore_sqlite,
    rotate_backups,
    table_count,
)


class Command(BaseCommand):
    help = (
        "Cria um backup íntegro do banco e confere o resultado. Pode ser "
        "executado com a plataforma no ar. Use --restaurar para voltar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--destino",
            default="",
            help="Pasta onde gravar (padrão: backups/ na raiz do projeto).",
        )
        parser.add_argument(
            "--manter",
            type=int,
            default=10,
            help="Quantos backups conservar; 0 não apaga nada (padrão: 10).",
        )
        parser.add_argument(
            "--restaurar",
            default="",
            metavar="ARQUIVO",
            help=(
                "Restaura o banco a partir deste arquivo. Pare o servidor "
                "antes. O banco atual é guardado ao lado, por segurança."
            ),
        )

    def handle(self, *args, **options):
        if connection.vendor != "sqlite":
            raise CommandError(
                f"Este comando é específico do SQLite (banco atual: "
                f"{connection.vendor})."
            )

        alvo = Path(connection.settings_dict["NAME"])

        if options["restaurar"]:
            return self._restaurar(Path(options["restaurar"]), alvo)

        destino_dir = (
            Path(options["destino"])
            if options["destino"]
            else Path(settings.BASE_DIR) / "backups"
        )
        try:
            arquivo = backup_sqlite(alvo, destino_dir)
        except BackupError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Backup íntegro: {arquivo} "
                f"({arquivo.stat().st_size / 1024:.0f} KB, "
                f"{table_count(arquivo)} tabelas)"
            )
        )
        removidos = rotate_backups(destino_dir, options["manter"])
        if removidos:
            self.stdout.write(f"Backups antigos removidos: {len(removidos)}")
        self.stdout.write(
            "Para restaurar: pare o servidor e rode "
            f"python manage.py backupdb --restaurar {arquivo}"
        )

    def _restaurar(self, backup, alvo):
        try:
            anterior = restore_sqlite(backup, alvo)
        except BackupError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Banco restaurado de {backup}."))
        if anterior:
            self.stdout.write(
                f"O banco que havia antes foi guardado em {anterior}. "
                "Apague-o quando confirmar que a restauração ficou correta."
            )
        self.stdout.write("Suba o servidor e confira os dados.")

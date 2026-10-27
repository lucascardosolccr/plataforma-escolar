"""Ciclo completo de backup e restauração.

Um procedimento de backup só vale quando a restauração é comprovada. Estes
testes fazem o caminho inteiro em arquivos SQLite reais: gravam, fazem o
backup, apagam o dado, restauram e conferem que ele voltou.

Usam arquivos próprios em vez do banco do Django porque na suíte ele é em
memória — não existe arquivo para copiar, e é justamente a cópia do arquivo
que precisa ser testada.
"""

import shutil
import sqlite3
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from apps.core.backup import (
    BackupError,
    backup_sqlite,
    integrity_of,
    restore_sqlite,
    rotate_backups,
    table_count,
)


class BackupCycleTests(SimpleTestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="escola-backup-"))
        self.banco = self.dir / "db.sqlite3"
        self.backups = self.dir / "backups"
        self._gravar([("Escola A", "a"), ("Escola B", "b")])

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _gravar(self, linhas):
        conn = sqlite3.connect(self.banco)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS escola (nome TEXT, code TEXT UNIQUE)"
            )
            conn.executemany("INSERT OR IGNORE INTO escola VALUES (?, ?)", linhas)
            conn.commit()
        finally:
            conn.close()

    def _codes(self, path):
        conn = sqlite3.connect(path)
        try:
            return {r[0] for r in conn.execute("SELECT code FROM escola")}
        finally:
            conn.close()

    # --- backup ---

    def test_backup_is_created_and_integral(self):
        arquivo = backup_sqlite(self.banco, self.backups)
        self.assertTrue(arquivo.exists())
        self.assertGreater(arquivo.stat().st_size, 0)
        self.assertEqual(integrity_of(arquivo), "ok")
        self.assertGreaterEqual(table_count(arquivo), 1)

    def test_backup_contains_the_data_written_before_it(self):
        arquivo = backup_sqlite(self.banco, self.backups)
        self.assertEqual(self._codes(arquivo), {"a", "b"})

    def test_backup_does_not_see_data_written_after_it(self):
        arquivo = backup_sqlite(self.banco, self.backups)
        self._gravar([("Escola C", "c")])
        self.assertEqual(self._codes(arquivo), {"a", "b"})
        self.assertEqual(self._codes(self.banco), {"a", "b", "c"})

    def test_backup_leaves_source_untouched(self):
        antes = self.banco.read_bytes()
        backup_sqlite(self.banco, self.backups)
        self.assertEqual(self.banco.read_bytes(), antes)

    def test_two_backups_in_the_same_second_do_not_overwrite(self):
        a = backup_sqlite(self.banco, self.backups)
        b = backup_sqlite(self.banco, self.backups)
        self.assertNotEqual(a, b)
        self.assertTrue(a.exists() and b.exists())

    def test_missing_source_is_reported(self):
        with self.assertRaises(BackupError):
            backup_sqlite(self.dir / "nao-existe.sqlite3", self.backups)

    # --- restauração ---

    def test_full_cycle_recovers_deleted_record(self):
        arquivo = backup_sqlite(self.banco, self.backups)

        conn = sqlite3.connect(self.banco)
        try:
            conn.execute("DELETE FROM escola WHERE code = 'a'")
            conn.commit()
        finally:
            conn.close()
        self.assertEqual(self._codes(self.banco), {"b"})

        restore_sqlite(arquivo, self.banco)
        self.assertEqual(self._codes(self.banco), {"a", "b"})

    def test_restore_keeps_a_copy_of_the_previous_database(self):
        arquivo = backup_sqlite(self.banco, self.backups)
        self._gravar([("Escola C", "c")])
        anterior = restore_sqlite(arquivo, self.banco)
        self.assertIsNotNone(anterior)
        # O banco restaurado não tem C; a cópia do anterior tem.
        self.assertEqual(self._codes(self.banco), {"a", "b"})
        self.assertEqual(self._codes(anterior), {"a", "b", "c"})

    def test_restore_refuses_corrupt_backup_without_touching_database(self):
        """Restaurar de um arquivo corrompido não pode destruir o banco bom."""
        ruim = self.dir / "corrompido.sqlite3"
        ruim.write_bytes(b"isto nao e um banco sqlite")
        antes = self.banco.read_bytes()

        with self.assertRaises(BackupError):
            restore_sqlite(ruim, self.banco)

        self.assertEqual(self.banco.read_bytes(), antes)
        self.assertEqual(self._codes(self.banco), {"a", "b"})

    def test_restore_reports_missing_backup(self):
        with self.assertRaises(BackupError):
            restore_sqlite(self.dir / "nao-existe.sqlite3", self.banco)

    # --- rotação ---

    def test_rotation_keeps_only_the_requested_number(self):
        for _ in range(4):
            backup_sqlite(self.banco, self.backups)
        self.assertEqual(len(list(self.backups.glob("db-*.sqlite3"))), 4)

        rotate_backups(self.backups, keep=2)
        self.assertEqual(len(list(self.backups.glob("db-*.sqlite3"))), 2)

    def test_rotation_with_zero_keeps_everything(self):
        for _ in range(3):
            backup_sqlite(self.banco, self.backups)
        self.assertEqual(rotate_backups(self.backups, keep=0), [])
        self.assertEqual(len(list(self.backups.glob("db-*.sqlite3"))), 3)

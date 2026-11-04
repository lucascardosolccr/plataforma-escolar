"""Publicação numa hospedagem (deploy/pythonanywhere): pacote sem dados pessoais e chave secreta robusta."""

import importlib.util
import zipfile
from pathlib import Path

from django.conf import settings

import config.settings as project_settings

ROOT = Path(settings.BASE_DIR)


def _packer():
    spec = importlib.util.spec_from_file_location("empacotar", ROOT / "tools" / "empacotar_hospedagem.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_package_leaves_out_database_keys_photos_and_backups(tmp_path, monkeypatch):
    packer = _packer()
    fake = tmp_path / "plataforma-escolar"
    for rel in ("manage.py", "apps/core/views.py", "deploy/pythonanywhere/instalar.sh", "db.sqlite3", ".secret_key",
                ".env", "media/fotos/ana.jpg", "backups/db-1.sqlite3", "logs/app.log", ".venv/x.py",
                "apps/core/__pycache__/v.pyc", "scale.sqlite3"):
        (fake / rel).parent.mkdir(parents=True, exist_ok=True)
        (fake / rel).write_bytes(b"a\r\nb\r\n")
    monkeypatch.setattr(packer, "ROOT", fake)
    monkeypatch.setattr(packer, "OUT", tmp_path / "out" / "pacote.zip")
    packer.main()
    with zipfile.ZipFile(tmp_path / "out" / "pacote.zip") as z:
        names = sorted(z.namelist())
        script = z.read("plataforma-escolar/deploy/pythonanywhere/instalar.sh")
    assert names == ["plataforma-escolar/apps/core/views.py", "plataforma-escolar/deploy/pythonanywhere/instalar.sh",
                     "plataforma-escolar/manage.py"]
    assert script == b"a\nb\n"  # bash no Linux da hospedagem não aceita CRLF


def test_empty_secret_key_file_gets_a_new_key_instead_of_breaking_the_site(tmp_path, monkeypatch):
    monkeypatch.delenv("DJANGO_SECRET_KEY", raising=False)
    monkeypatch.setattr(project_settings, "BASE_DIR", tmp_path)
    (tmp_path / ".secret_key").write_text("", encoding="utf-8")
    key = project_settings._secret_key()
    assert len(key) >= 50
    assert (tmp_path / ".secret_key").read_text(encoding="utf-8") == key
    assert project_settings._secret_key() == key


def test_deploy_scripts_are_committed_with_lf():
    attrs = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attrs

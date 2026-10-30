"""Retenção de dados: apaga arquivos de pré-cadastros que não viraram matrícula.

Pré-cadastro recusado ou cancelado há mais de N dias (padrão 180) perde a
foto e os documentos enviados (certidão, comprovante de residência...). O
registro do pedido fica, sem os arquivos, para o histórico da secretaria.
Pré-cadastro aprovado não é tocado: os dados passaram para a ficha.

Uso:  python manage.py purgeapplications [--dias 180] [--simular]
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import AuditLog
from apps.registry.models import StudentApplication


class Command(BaseCommand):
    help = "Apaga foto e documentos de pré-cadastros recusados/cancelados há mais de N dias."

    def add_arguments(self, parser):
        parser.add_argument("--dias", type=int, default=180)
        parser.add_argument("--simular", action="store_true", help="Só mostra o que seria apagado.")

    def handle(self, *args, dias, simular, **options):
        limit = timezone.now() - timedelta(days=dias)
        qs = StudentApplication.objects.filter(status__in=["recusado", "cancelado"], updated_at__lt=limit)
        files = 0
        for app in qs:
            docs = list(app.documents.all())
            files += len(docs) + (1 if app.photo else 0)
            if simular:
                continue
            for d in docs:
                d.file.delete(save=False)
                d.delete()
            if app.photo:
                app.photo.delete(save=False)
                StudentApplication.objects.filter(pk=app.pk).update(photo="")
        if not simular and files:
            AuditLog.objects.create(action="delete", target_type="StudentApplication", target_id="retencao",
                                    detail=f"Retenção: {files} arquivo(s) de pré-cadastros encerrados há mais de {dias} dias")
        verb = "seriam apagados" if simular else "apagados"
        self.stdout.write(f"{qs.count()} pré-cadastro(s) encerrado(s); {files} arquivo(s) {verb}.")

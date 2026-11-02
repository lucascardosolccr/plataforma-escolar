"""Política de retenção de dados (LGPD, art. 15 e 16; Prompt 9 §13).

Separa três grupos, e só o primeiro é apagado, e só com ``--aplicar``:

1. **Dados operacionais, sem valor de registro escolar** (apagados com --aplicar):
   - avisos já lidos há mais de ``--avisos-dias`` (padrão 365);
   - execuções diárias dos lembretes com mais de ``--lembretes-dias`` (padrão 365);
   - "Estou ciente" e marcações de autorrelato de provas com mais de 2 anos.
2. **Para revisão humana** (só relatados): contas inativas há mais de 2 anos,
   que a secretaria pode desativar; registros de auditoria com mais de 5 anos.
3. **Registro escolar** (nunca tocado aqui): notas, frequência, ocorrências,
   atividades, entregas, matrículas, planos e documentos. A guarda deles
   segue as normas da rede de ensino; apagá-los é decisão da escola, não da
   plataforma.

Pré-cadastros têm comando próprio (``purgeapplications``).

Uso:  python manage.py retencao              (só relata)
      python manage.py retencao --aplicar    (apaga o grupo 1 e registra na auditoria)
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.communication.models import Notification, ReminderRun
from apps.core.models import AuditLog, User


class Command(BaseCommand):
    help = "Relata e, com --aplicar, apaga dados operacionais antigos (nunca registro escolar)."

    def add_arguments(self, parser):
        parser.add_argument("--aplicar", action="store_true", help="Apaga o grupo 1. Sem isto, só relata.")
        parser.add_argument("--avisos-dias", type=int, default=365)
        parser.add_argument("--lembretes-dias", type=int, default=365)

    def handle(self, *args, aplicar, avisos_dias, lembretes_dias, **options):
        from apps.pedagogy.models import ActivityAcknowledgement
        from apps.study.models import TopicCheck

        now = timezone.now()
        two_years = now - timedelta(days=730)
        groups = {
            "avisos lidos": Notification.objects.filter(is_read=True,
                                                        created_at__lt=now - timedelta(days=avisos_dias)),
            "execuções de lembretes": ReminderRun.objects.filter(
                day__lt=(now - timedelta(days=lembretes_dias)).date()),
            "“Estou ciente” antigos": ActivityAcknowledgement.objects.filter(created_at__lt=two_years),
            "autorrelatos de provas antigos": TopicCheck.objects.filter(updated_at__lt=two_years),
        }
        self.stdout.write("Grupo 1 — dados operacionais (apagados com --aplicar):")
        counts = {}
        for label, qs in groups.items():
            counts[label] = qs.count()
            self.stdout.write(f"  {label}: {counts[label]}")
        self.stdout.write("Grupo 2 — para revisão humana (nada é apagado):")
        self.stdout.write("  contas ativas sem entrar há mais de 2 anos: "
                          f"{User.objects.filter(is_active=True, last_login__lt=two_years).count()}")
        self.stdout.write("  registros de auditoria com mais de 5 anos: "
                          f"{AuditLog.objects.filter(created_at__lt=now - timedelta(days=1826)).count()}")
        self.stdout.write("Grupo 3 — registro escolar: não é tratado por este comando.")
        if not aplicar:
            self.stdout.write(self.style.WARNING("Nada foi apagado. Use --aplicar para apagar o grupo 1."))
            return
        with transaction.atomic():
            for qs in groups.values():
                qs.delete()
            AuditLog.objects.create(action="delete", target_type="Retenção",
                                    detail="Retenção aplicada: " + "; ".join(f"{k}: {v}" for k, v in counts.items()))
        self.stdout.write(self.style.SUCCESS("Grupo 1 apagado e registrado na auditoria."))

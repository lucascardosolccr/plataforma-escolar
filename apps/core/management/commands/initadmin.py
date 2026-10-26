from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Role, School, User


class Command(BaseCommand):
    help = "Cria a escola e a conta administrativa inicial (idempotente)."

    def add_arguments(self, parser):
        parser.add_argument("--school-name", default="")
        parser.add_argument("--school-code", default="")
        parser.add_argument("--username", default="")
        parser.add_argument("--email", default="")
        parser.add_argument("--password", default="")

    def handle(self, *args, **options):
        school = None
        code = options["school_code"]
        if code:
            school, created = School.objects.get_or_create(
                code=code, defaults={"name": options["school_name"] or code}
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f'Escola criada: {school.name}'))

        username = options["username"]
        if not username:
            username = input("Usuário do administrador: ").strip()
        password = options["password"]
        if not password:
            import getpass

            password = getpass.getpass("Senha do administrador: ")

        if User.objects.filter(username=username).exists():
            self.stdout.write(self.style.WARNING("Administrador já existe; nada a fazer."))
            return

        with transaction.atomic():
            user = User.objects.create_superuser(
                username=username,
                email=options["email"] or "",
                password=password,
            )
            user.role = Role.ADMIN
            user.school = school
            user.first_name = "Administrador"
            user.save(update_fields=["role", "school", "first_name"])

        self.stdout.write(
            self.style.SUCCESS(
                f'Conta administrativa "{username}" criada. '
                "Troque a senha no primeiro acesso pela interface."
            )
        )
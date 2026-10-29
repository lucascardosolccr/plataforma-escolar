"""Controle de acesso do calendário escolar.

Reaproveita as regras de escopo já existentes (cadastro e pedagógico) para não
duplicar a matriz RBAC. O ``CalendarScope`` carrega vínculos, matrículas e
atribuições uma vez por requisição, evitando uma consulta por evento.
"""

from django.utils import timezone

from apps.core.models import Role

ADMIN_RECORD_ROLES = (
    Role.ADMIN.value,
    Role.DIRECAO.value,
    Role.COORDENACAO.value,
    Role.SECRETARIA.value,
)


def can_view_calendar(user):
    """Qualquer perfil autenticado vê o calendário dentro do seu escopo."""
    return user.is_authenticated


def teacher_of_student(user, student):
    from apps.registry.access import teacher_of_student as _tos

    return _tos(user, student)


def _covers_date(enrollment, when):
    """A matrícula cobre a data? (avaliações têm uma data só, não prazo)."""
    if enrollment.started_on and when < enrollment.started_on:
        return False
    if enrollment.ended_on and when > enrollment.ended_on:
        return False
    return True


class CalendarScope:
    """Escopo de acesso do usuário, com dados carregados sob demanda e cacheados.

    Uma instância deve viver apenas durante uma requisição: os caches refletem
    os vínculos e matrículas no momento em que foram lidos.
    """

    def __init__(self, user):
        self.user = user
        self.role = user.role
        self.staff = user.role in ADMIN_RECORD_ROLES
        self.today = timezone.localdate()
        self._student_ids = None
        self._student_id_set = None
        self._students = None
        self._enrollments_by_student = None
        self._enrollments_by_class = None
        self._assignments = None
        self._assigned_class_ids = None
        self._active_classes = {}
        self._student_enrollments = {}

    # ---------- dados da família (responsável/estudante) ----------

    def _load_family(self):
        if self._enrollments_by_student is not None:
            return
        from apps.registry.models import Enrollment, Student

        if self.role == Role.RESPONSAVEL.value:
            from apps.pedagogy.access import _approved_child_ids

            ids = list(_approved_child_ids(self.user))
        elif self.role == Role.ESTUDANTE.value:
            from apps.pedagogy.access import own_student

            own = own_student(self.user)
            ids = [own.pk] if own is not None else []
        else:
            ids = []

        by_student = {}
        by_class = {}
        if ids:
            qs = Enrollment.objects.filter(student_id__in=ids).only(
                "student_id", "class_group_id", "started_on", "ended_on"
            )
            for enr in qs:
                by_student.setdefault(enr.student_id, []).append(enr)
                by_class.setdefault(enr.class_group_id, []).append(enr)

        self._student_ids = ids
        self._student_id_set = set(ids)
        self._enrollments_by_student = by_student
        self._enrollments_by_class = by_class
        self._students = (
            list(
                Student.objects.filter(pk__in=ids).order_by(
                    "first_name", "last_name"
                )
            )
            if ids
            else []
        )

    def _enrollments(self, item, student_ids=None):
        enrs = self._enrollments_by_class.get(item.class_group_id, [])
        if student_ids is None:
            return enrs
        return [enr for enr in enrs if enr.student_id in student_ids]

    def _reaches(self, item):
        from apps.pedagogy.access import reaches
        from apps.pedagogy.models import Evaluation

        self._load_family()
        enrs = self._enrollments(item, self._student_id_set)
        if isinstance(item, Evaluation):
            return any(_covers_date(enr, item.date) for enr in enrs)
        return reaches(enrs, item)

    def item_reaches_student(self, item, student):
        """O item publicado para a turma alcança este estudante?

        Vale para qualquer perfil que use o filtro por estudante (equipe,
        professor ou família), por isso consulta as matrículas do estudante
        informado, não apenas as do escopo familiar.
        """
        from apps.pedagogy.access import reaches
        from apps.pedagogy.models import Evaluation

        if student.pk not in self._student_enrollments:
            from apps.registry.models import Enrollment

            self._student_enrollments[student.pk] = list(
                Enrollment.objects.filter(student=student).only(
                    "student_id", "class_group_id", "started_on", "ended_on"
                )
            )
        enrs = [
            enr
            for enr in self._student_enrollments[student.pk]
            if enr.class_group_id == item.class_group_id
        ]
        if isinstance(item, Evaluation):
            return any(_covers_date(enr, item.date) for enr in enrs)
        return reaches(enrs, item)

    def reached_students(self, item):
        """Estudantes do usuário alcançados pelo item, na ordem de exibição."""
        from apps.pedagogy.access import reaches
        from apps.pedagogy.models import Evaluation

        self._load_family()
        is_evaluation = isinstance(item, Evaluation)
        out = []
        for student in self._students:
            enrs = [
                enr
                for enr in self._enrollments_by_student.get(student.pk, [])
                if enr.class_group_id == item.class_group_id
            ]
            if is_evaluation:
                ok = any(_covers_date(enr, item.date) for enr in enrs)
            else:
                ok = reaches(enrs, item)
            if ok:
                out.append(student)
        return out

    # ---------- dados do professor ----------

    def _load_assignments(self):
        if self._assignments is None:
            from apps.academics.models import TeacherAssignment

            self._assignments = set(
                TeacherAssignment.objects.filter(
                    teacher=self.user, school=self.user.school
                ).values_list("class_group_id", "subject_id")
            )
            self._assigned_class_ids = {cid for cid, _ in self._assignments}
        return self._assignments

    def _teaches(self, item):
        return (item.class_group_id, item.subject_id) in self._load_assignments()

    def _active_class_ids(self, student):
        if student.pk not in self._active_classes:
            from apps.registry.models import Enrollment

            self._active_classes[student.pk] = set(
                Enrollment.objects.filter(student=student, status="ativo")
                .values_list("class_group_id", flat=True)
            )
        return self._active_classes[student.pk]

    def _teacher_of_student(self, student):
        self._load_assignments()
        return bool(self._active_class_ids(student) & self._assigned_class_ids)

    # ---------- visibilidade por origem ----------

    def activity_visible(self, act):
        if self.staff:
            return True
        if self.role == Role.PROFESSOR.value:
            return self._teaches(act)
        if self.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
            # Cancelada continua no histórico, como na lista de atividades; só
            # o rascunho e o que ainda não foi publicado ficam fora.
            if (
                act.status != act.Status.CANCELED
                and not act.is_visible_to_family
            ):
                return False
            if act.published_date > self.today:
                return False
            return self._reaches(act)
        return False

    def group_work_visible(self, gw):
        if self.staff:
            return True
        if self.role == Role.PROFESSOR.value:
            return self._teaches(gw)
        if self.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
            if (
                gw.status != gw.Status.CANCELED
                and not gw.is_visible_to_family
            ):
                return False
            if gw.published_date > self.today:
                return False
            return self._reaches(gw)
        return False

    def evaluation_visible(self, ev):
        from apps.pedagogy.models import Evaluation

        if ev.status != Evaluation.Status.PUBLISHED:
            return False
        if self.staff:
            return True
        if self.role == Role.PROFESSOR.value:
            return self._teaches(ev)
        if self.role in (Role.RESPONSAVEL.value, Role.ESTUDANTE.value):
            return self._reaches(ev)
        return False

    def occurrence_visible(self, student):
        """Mesma regra da tela de ocorrências (o estudante não vê as próprias)."""
        if not self.user.is_authenticated:
            return False
        if self.staff:
            return True
        if self.role == Role.PROFESSOR.value:
            return self._teacher_of_student(student)
        if self.role == Role.RESPONSAVEL.value:
            self._load_family()
            return student.pk in self._student_id_set
        return False

    def justification_visible(self, student):
        """Mesma regra da tela de justificativas."""
        return self.occurrence_visible(student)


# ---------- atalhos sem escopo (compatibilidade) ----------


def event_reaches_student(item, student):
    """O item publicado para a turma alcança este estudante?"""
    from apps.pedagogy.access import enrollments_by_student, reaches
    from apps.pedagogy.models import Evaluation

    por_aluno = enrollments_by_student([student.pk], item.class_group_id)
    enrs = por_aluno.get(student.pk, [])
    if isinstance(item, Evaluation):
        return any(_covers_date(enr, item.date) for enr in enrs)
    return reaches(enrs, item)


def activity_visible(user, act):
    return CalendarScope(user).activity_visible(act)


def group_work_visible(user, gw):
    return CalendarScope(user).group_work_visible(gw)


def evaluation_visible(user, ev):
    return CalendarScope(user).evaluation_visible(ev)


def reached_students(user, item):
    return CalendarScope(user).reached_students(item)


def occurrence_visible(user, student):
    return CalendarScope(user).occurrence_visible(student)


def justification_visible(user, student):
    return CalendarScope(user).justification_visible(student)

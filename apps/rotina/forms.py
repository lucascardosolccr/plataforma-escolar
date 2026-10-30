from django import forms

from apps.academics.models import Subject, TeacherAssignment
from apps.core.models import Role, User

from .models import ClassSchedule, MealMenu


class MealForm(forms.ModelForm):
    """Uma refeição do dia. Descrição em branco = refeição não servida."""

    class Meta:
        model = MealMenu
        fields = ["description", "substitution", "notes", "ingredients", "allergens", "validated_by",
                  "changed", "change_note"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 2}),
            "ingredients": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"description": "O que será servido", "changed": "É uma alteração de última hora"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False

    def clean(self):
        data = super().clean()
        if (data.get("ingredients") or data.get("allergens")) and not (data.get("validated_by") or "").strip():
            self.add_error(
                "validated_by",
                "Informe quem validou ingredientes e alergênicos. Sem isso, essas informações não são publicadas.",
            )
        if data.get("changed") and not (data.get("change_note") or "").strip():
            self.add_error("change_note", "Diga o que mudou.")
        return data


class ScheduleSlotForm(forms.ModelForm):
    class Meta:
        model = ClassSchedule
        fields = ["weekday", "start_time", "end_time", "subject", "teacher", "room"]
        widgets = {"start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def __init__(self, *args, class_group=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_group = class_group
        assigned = TeacherAssignment.objects.filter(class_group=class_group)
        self.fields["subject"].queryset = Subject.choices_for(
            class_group.school, keep=self.instance.subject_id).order_by("name")
        self.fields["teacher"].queryset = User.objects.filter(
            school=class_group.school, role=Role.PROFESSOR.value, is_active=True
        ).order_by("first_name")
        self.fields["teacher"].required = False
        self.fields["teacher"].help_text = "Em branco: o professor atribuído à disciplina nesta turma."
        self._assigned = assigned

    def clean(self):
        data = super().clean()
        start, end = data.get("start_time"), data.get("end_time")
        if start and end and end <= start:
            self.add_error("end_time", "O término precisa ser depois do início.")
        subject, teacher = data.get("subject"), data.get("teacher")
        if subject and not teacher:
            a = self._assigned.filter(subject=subject).first()
            if a:
                data["teacher"] = a.teacher
        if start and end and data.get("weekday") is not None:
            clash = ClassSchedule.objects.filter(
                class_group=self.class_group, weekday=data["weekday"], start_time__lt=end, end_time__gt=start
            ).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error("start_time", f"Conflita com {clash.first().subject} no mesmo horário.")
            t = data.get("teacher")
            if t:
                busy = ClassSchedule.objects.filter(
                    teacher=t, weekday=data["weekday"], start_time__lt=end, end_time__gt=start
                ).exclude(pk=self.instance.pk).exclude(class_group=self.class_group)
                if busy.exists():
                    self.add_error("teacher", f"{t.get_full_name() or t.username} já dá aula em "
                                              f"{busy.first().class_group.name} neste horário.")
        return data

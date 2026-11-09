import datetime

from django import forms
from django.utils import timezone

from apps.academics.models import ClassGroup

from .models import Booking, Resource

MAX_AHEAD = 90  # dias


class ResourceForm(forms.ModelForm):
    class Meta:
        model = Resource
        fields = ["name", "kind", "notes", "active"]

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        qs = Resource.objects.filter(school=self.school, name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe um espaço ou equipamento com esse nome.")
        return name


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ["resource", "day", "start", "end", "class_group", "purpose"]
        widgets = {"day": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "start": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
                   "end": forms.TimeInput(attrs={"type": "time"}, format="%H:%M")}

    def __init__(self, *args, school=None, classes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.school = school
        self.fields["resource"].queryset = Resource.objects.filter(school=school, active=True)
        self.fields["resource"].empty_label = "Escolha…"
        self.fields["class_group"].queryset = classes if classes is not None else ClassGroup.objects.filter(
            school=school)
        self.fields["class_group"].empty_label = "—"

    def clean(self):
        c = super().clean()
        day, start, end, res = c.get("day"), c.get("start"), c.get("end"), c.get("resource")
        today = timezone.localdate()
        if day and day < today:
            self.add_error("day", "Escolha hoje ou um dia futuro.")
        elif day and day > today + datetime.timedelta(days=MAX_AHEAD):
            self.add_error("day", f"Reserve com até {MAX_AHEAD} dias de antecedência.")
        if start and end and end <= start:
            self.add_error("end", "O fim precisa ser depois do início.")
        if day == today and end and end <= timezone.localtime().time() and not self.errors:
            self.add_error("end", "Esse horário de hoje já passou.")
        if res and day and start and end and not self.errors:
            clash = conflicts(res, day, start, end).first()
            if clash:
                who = ((clash.booked_by.get_full_name() or clash.booked_by.username) if clash.booked_by
                       else "outra pessoa")
                raise forms.ValidationError(
                    f"{res} já está reservado das {clash.start:%H:%M} às {clash.end:%H:%M} por {who}.")
        return c


def conflicts(resource, day, start, end, exclude=None):
    """Reservas ativas do recurso que se sobrepõem ao intervalo (encostar não conta: 8h–9h e 9h–10h cabem)."""
    qs = Booking.objects.filter(resource=resource, day=day, canceled_at__isnull=True, start__lt=end, end__gt=start)
    if exclude is not None:
        qs = qs.exclude(pk=exclude)
    return qs

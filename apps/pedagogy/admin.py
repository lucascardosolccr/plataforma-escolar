from django.contrib import admin

from .models import (
    AbsenceJustification,
    AcademicRule,
    Activity,
    AttendanceRecord,
    Evaluation,
    Grade,
    InterventionPlan,
    Occurrence,
    PedagogicalObservation,
    PlanNote,
    SchoolConfig,
    Submission,
)


@admin.register(AcademicRule)
class AcademicRuleAdmin(admin.ModelAdmin):
    list_display = ("school", "subject", "formula", "passing_grade")
    list_filter = ("formula", "school")


@admin.register(Evaluation)
class EvaluationAdmin(admin.ModelAdmin):
    list_display = ("title", "class_group", "subject", "date", "status", "created_by")
    list_filter = ("status", "school")


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ("student", "evaluation", "value", "updated_by", "updated_at")
    search_fields = ("student__first_name", "student__last_name")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("title", "class_group", "subject", "deadline", "published_date")


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ("student", "activity", "status")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("student", "class_group", "date", "status")
    list_filter = ("status", "date")
    search_fields = ("student__first_name",)


@admin.register(AbsenceJustification)
class AbsenceJustificationAdmin(admin.ModelAdmin):
    list_display = ("student", "start_date", "end_date", "status", "validated_by")
    list_filter = ("status", "school")


@admin.register(Occurrence)
class OccurrenceAdmin(admin.ModelAdmin):
    list_display = ("student", "date", "status", "recorded_by", "created_at")
    list_filter = ("status", "school")


@admin.register(PedagogicalObservation)
class PedagogicalObservationAdmin(admin.ModelAdmin):
    list_display = ("student", "content", "teacher", "observed_at")


@admin.register(InterventionPlan)
class InterventionPlanAdmin(admin.ModelAdmin):
    list_display = ("student", "title", "status", "created_by")
    list_filter = ("status", "school")


@admin.register(PlanNote)
class PlanNoteAdmin(admin.ModelAdmin):
    list_display = ("plan", "created_by", "created_at")


@admin.register(SchoolConfig)
class SchoolConfigAdmin(admin.ModelAdmin):
    list_display = ("school", "max_absences_percent")
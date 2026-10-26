from django.contrib import admin

from .models import ClassGroup, SchoolYear, Subject, TeacherAssignment


@admin.register(SchoolYear)
class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ("name", "school", "start_date", "end_date", "is_current")
    list_filter = ("school", "is_current")


@admin.register(ClassGroup)
class ClassGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "school_year", "grade", "turn", "school")
    list_filter = ("school", "school_year", "turn")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "school")
    list_filter = ("school",)


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "subject", "class_group", "school_year", "school")
    list_filter = ("school", "school_year", "subject")
    search_fields = ("teacher__username", "teacher__first_name", "teacher__last_name")
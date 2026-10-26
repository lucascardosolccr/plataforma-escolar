from django.contrib import admin

from .models import Enrollment, GuardianLink, GuardianProfile, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "school", "status")
    list_filter = ("school", "status")
    search_fields = ("first_name", "last_name")


@admin.register(GuardianProfile)
class GuardianProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "relation", "phone", "comm_preference")
    search_fields = ("user__username", "user__first_name")


@admin.register(GuardianLink)
class GuardianLinkAdmin(admin.ModelAdmin):
    list_display = ("guardian", "student", "relation", "status", "school")
    list_filter = ("school", "status")
    search_fields = ("guardian__username", "student__first_name", "student__last_name")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "class_group", "school_year", "status", "school")
    list_filter = ("school", "school_year", "status")
    search_fields = ("student__first_name", "student__last_name", "enrollment_number")
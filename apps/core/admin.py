from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AuditLog, School, User


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "created_at")
    search_fields = ("name", "code")


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "school", "is_active")
    list_filter = ("role", "is_active", "school")
    search_fields = ("username", "email", "first_name", "last_name")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Plataforma", {"fields": ("role", "school")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        ("Plataforma", {"fields": ("role", "school")}),
    )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "target_type", "target_id", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("detail", "user__username")
    readonly_fields = ("user", "action", "target_type", "target_id", "detail", "ip_address", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
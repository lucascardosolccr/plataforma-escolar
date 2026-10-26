from django.contrib import admin

from .models import (
    Announcement,
    AnnouncementRead,
    Message,
    Notification,
    ServiceRequest,
    Thread,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "title", "is_read", "created_at")
    list_filter = ("kind", "is_read", "school")
    search_fields = ("title", "user__username")


@admin.register(Thread)
class ThreadAdmin(admin.ModelAdmin):
    list_display = ("title", "student", "created_by", "created_at")
    list_filter = ("school",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("thread", "sender", "created_at", "read_at")


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "scope", "audience", "class_group", "student", "created_by")
    list_filter = ("scope", "audience", "school")


@admin.register(AnnouncementRead)
class AnnouncementReadAdmin(admin.ModelAdmin):
    list_display = ("announcement", "user", "read_at")


@admin.register(ServiceRequest)
class ServiceRequestAdmin(admin.ModelAdmin):
    list_display = ("title", "requester", "category", "status", "created_at")
    list_filter = ("status", "category", "school")
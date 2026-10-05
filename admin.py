from django.contrib import admin
from .models import PresenceCheck, Profile, Project, TrackerUser, WorkSession
class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
@admin.register(TrackerUser)
class TrackerUserAdmin(ReadOnlyAdmin):
    list_display = ("id", "name", "role", "tg_id", "origin")
    list_filter = ("role", "origin")
    search_fields = ("name",)
@admin.register(Project)
class ProjectAdmin(ReadOnlyAdmin):
    list_display = ("id", "name", "is_active")
    list_filter = ("is_active",)
class CheckInline(admin.TabularInline):
    model = PresenceCheck
    fields = ("question", "answer", "status", "created_at", "resolved_at")
    readonly_fields = fields
    extra = 0
    can_delete = False
@admin.register(WorkSession)
class WorkSessionAdmin(ReadOnlyAdmin):
    list_display = ("id", "user", "project", "started", "ended", "status",
                    "passed_count", "missed_count")
    list_filter = ("status", "project")
    search_fields = ("user__name",)
    list_select_related = ("user", "project")
    inlines = [CheckInline]
@admin.register(PresenceCheck)
class PresenceCheckAdmin(ReadOnlyAdmin):
    list_display = ("id", "session", "kind", "question", "status")
    list_filter = ("status", "kind")
    list_select_related = ("session__user", "session__project")
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "tracker_user")
    list_select_related = ("user", "tracker_user")

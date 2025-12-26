from django.contrib import admin
from .models import ConversationThread, ConversationCheckpoint, WorkflowState


@admin.register(ConversationThread)
class ConversationThreadAdmin(admin.ModelAdmin):
    list_display = ['thread_id', 'user', 'workflow_type', 'is_active', 'created_at', 'updated_at']
    list_filter = ['workflow_type', 'is_active', 'created_at']
    search_fields = ['thread_id', 'user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Thread Information', {
            'fields': ('thread_id', 'user', 'workflow_type', 'is_active')
        }),
        ('Metadata', {
            'fields': ('metadata',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(ConversationCheckpoint)
class ConversationCheckpointAdmin(admin.ModelAdmin):
    list_display = ['checkpoint_id', 'thread', 'version', 'created_at']
    list_filter = ['created_at', 'version']
    search_fields = ['checkpoint_id', 'thread__thread_id']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Checkpoint Information', {
            'fields': ('thread', 'checkpoint_id', 'parent_checkpoint', 'version')
        }),
        ('State Data', {
            'fields': ('state', 'checkpoint_metadata')
        }),
        ('Timestamps', {
            'fields': ('created_at',)
        }),
    )


@admin.register(WorkflowState)
class WorkflowStateAdmin(admin.ModelAdmin):
    list_display = ['thread', 'current_step', 'status', 'updated_at']
    list_filter = ['status', 'current_step']
    search_fields = ['thread__thread_id']
    readonly_fields = ['updated_at']

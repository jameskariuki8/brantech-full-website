from django.db import models
from django.contrib.auth.models import User
from pydantic import BaseModel
from typing import Optional

class ConversationThread(models.Model):
    """Represents a conversation or workflow thread"""
    
    WORKFLOW_CHOICES = [
        ('chatbot', 'Chatbot Conversation'),
        ('blog_generation', 'Blog Generation'),
        ('content_enhancement', 'Content Enhancement'),
    ]
    
    thread_id = models.CharField(max_length=255, unique=True, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    workflow_type = models.CharField(
        max_length=50,
        choices=WORKFLOW_CHOICES,
        default='chatbot'
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['thread_id']),
            models.Index(fields=['user', 'workflow_type']),
        ]
    
    def __str__(self):
        return f"{self.thread_id} ({self.workflow_type})"


class ConversationCheckpoint(models.Model):
    """Stores LangGraph checkpoint data"""
    
    thread = models.ForeignKey(
        ConversationThread,
        on_delete=models.CASCADE,
        related_name='checkpoints'
    )
    checkpoint_id = models.CharField(max_length=255, db_index=True)
    parent_checkpoint = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='children'
    )
    
    # LangGraph state data (serialized)
    state = models.JSONField()
    
    # Metadata for querying and filtering
    checkpoint_metadata = models.JSONField(default=dict, blank=True)
    
    # Version tracking
    version = models.IntegerField(default=1)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        unique_together = [['thread', 'checkpoint_id']]
        indexes = [
            models.Index(fields=['thread', 'checkpoint_id']),
            models.Index(fields=['thread', '-created_at']),
        ]
    
    def __str__(self):
        return f"Checkpoint {self.checkpoint_id[:8]}... ({self.thread.thread_id})"


class WorkflowState(models.Model):
    """Stores workflow-specific state (e.g., blog generation progress)"""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    thread = models.OneToOneField(
        ConversationThread,
        on_delete=models.CASCADE,
        related_name='workflow_state'
    )
    current_step = models.CharField(max_length=100, default='')
    progress_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
    
    def __str__(self):
        return f"{self.thread.thread_id} - {self.status}"
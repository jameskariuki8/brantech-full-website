from django.db import models
from django.utils import timezone
from pgvector.django import VectorField


def _truncate_for_embedding(text: str, max_chars: int = 1500) -> str:
    """Truncate text for embedding use.

    - Keeps output <= max_chars characters.
    - Avoids cutting the last word in half when possible.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated + " ..."


class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    excerpt = models.TextField(max_length=300)
    content = models.TextField()
    image = models.ImageField(upload_to='blog_images/', blank=True, null=True)
    tags = models.CharField(max_length=200, blank=True, default='', help_text="Comma-separated tags")
    category = models.CharField(max_length=100, default='General')
    featured = models.BooleanField(default=False)
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # Vector embedding for semantic search (768 dimensions for Gemini embedding-001)
    embedding = VectorField(dimensions=768, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def get_tags_list(self):
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
    
    def get_embedding_text(self) -> str:
        """Return the text to be embedded for this blog post."""
        parts = [
            f"Title: {self.title}",
            f"Category: {self.category}",
            f"Tags: {self.tags}",
        ]
        # Use excerpt first (short summary), then truncated content to limit embedding size
        body = (self.excerpt or "") + "\n\n" + (self.content or "")
        parts.append(_truncate_for_embedding(body, max_chars=1500))
        return "\n".join(parts)


class Project(models.Model):
    title = models.CharField(max_length=200)
    short_description = models.TextField(max_length=500, blank=True, null=True)
    description = models.TextField() # This is the full description
    project_url = models.URLField(blank=True, null=True, help_text="Link to live project or demo")
    github_url = models.URLField(blank=True, null=True, help_text="Link to GitHub repository")
    image = models.ImageField(upload_to='project_images/', blank=True, null=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # Vector embedding for semantic search (768 dimensions for Gemini embedding-001)
    embedding = VectorField(dimensions=768, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
    
    def get_embedding_text(self) -> str:
        """Return the text to be embedded for this project."""
        parts = [
            f"Project: {self.title}",
            f"Technologies: {self.short_description or ''}",
        ]
        parts.append(_truncate_for_embedding(self.description or "", max_chars=1500))
        return "\n".join(parts)

class Event(models.Model):
    EVENT_TYPES = [
        ('webinar', 'Webinar'),
        ('workshop', 'Workshop'),
        ('conference', 'Conference'),
        ('meetup', 'Meetup'),
        ('launch', 'Product Launch'),
    ]
    
    title = models.CharField(max_length=200)
    description = models.TextField()
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    date = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True, null=True)
    is_online = models.BooleanField(default=False)
    registration_link = models.URLField(blank=True, null=True)
    max_attendees = models.PositiveIntegerField(blank=True, null=True)
    image = models.ImageField(upload_to='event_images/', blank=True, null=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.title} - {self.date.strftime('%Y-%m-%d')}"

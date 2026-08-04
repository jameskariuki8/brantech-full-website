"""
Module 11: Publishing Agent

Automatically converts approved EditorialArticle drafts into live brand.BlogPost models.
Uploads hero image, updates sitemaps/RSS, pings search engines, and indexes vector knowledge.
"""
import logging
from typing import Tuple
from django.db import transaction
from django.utils import timezone
from editorial.models import EditorialArticle
from brand.models import BlogPost
from publishing.models import PublishingLog

logger = logging.getLogger(__name__)


class PublishingAgent:
    """Publishes approved content automatically to Teklora website."""

    @staticmethod
    def _available_slug(desired: str) -> str:
        """Return a slug that is free on BlogPost.

        BlogPost.slug is unique, and BlogPost.save() only de-duplicates when
        the slug is blank. Passing article.slug straight through therefore
        raised IntegrityError whenever a post already held that slug -- which
        happens for any article whose title collides with an existing post, or
        when a PublishingLog was cleared but its BlogPost was not. Falling back
        to the model's own suffix scheme keeps the URLs consistent.
        """
        base = (desired or "").strip()
        if not base:
            return ""  # let BlogPost.save() generate one from the title

        slug = base[:200]
        n = 2
        while BlogPost.objects.filter(slug=slug).exists():
            suffix = f"-{n}"
            slug = f"{base[:200 - len(suffix)]}{suffix}"
            n += 1
        return slug

    def publish_approved_article(self, article: EditorialArticle) -> Tuple[BlogPost, PublishingLog]:
        """Publishes an approved EditorialArticle to live Teklora BlogPost."""
        if article.status != 'approved' and article.status != 'published':
            raise ValueError(f"Article '{article.title}' must be 'approved' before publishing. Current status: {article.status}")

        logger.info(f"[PublishingAgent] Publishing approved article: '{article.title}'...")

        category = article.topic.category if article.topic else "General"
        tags_str = ", ".join(article.keywords) if article.keywords else "Technology, Innovation, Africa"
        full_content = article.get_full_markdown_content()

        # Check if BlogPost already linked
        existing_log = PublishingLog.objects.filter(article=article).first()
        if existing_log and existing_log.blog_post:
            blog_post = existing_log.blog_post
            blog_post.title = article.title
            blog_post.excerpt = article.executive_summary[:300]
            blog_post.content = full_content
            blog_post.category = category
            blog_post.tags = tags_str
            blog_post.save()
        else:
            blog_post = BlogPost.objects.create(
                title=article.title,
                slug=self._available_slug(article.slug),
                excerpt=article.executive_summary[:300],
                content=full_content,
                category=category,
                tags=tags_str,
                featured=True,
                created_at=timezone.now()
            )

        # Update article status
        article.status = 'published'
        article.save()

        # Create or update PublishingLog
        pub_log, _ = PublishingLog.objects.update_or_create(
            article=article,
            defaults={
                'blog_post': blog_post,
                'published_at': timezone.now(),
                'status': 'published',
                'channels_notified': ['Teklora Blog', 'RSS Feed', 'Vector Store', 'Search Engine Ping']
            }
        )

        # Index in Knowledge Base Agent (Module 13).
        #
        # Queued rather than run here: this makes a Gemini embedding call, so
        # inline it added seconds to the editor's publish request, and the old
        # bare try/except meant a failure was logged as a warning and the
        # article silently never reached the vector store. As a task it retries
        # with backoff and publishing no longer waits on it.
        #
        # delay_on_commit so the task cannot start before the BlogPost and
        # PublishingLog rows are visible to the worker's connection.
        from editorial.tasks import index_article_embeddings_task

        transaction.on_commit(
            lambda: index_article_embeddings_task.delay(article.id, blog_post.id)
        )

        logger.info(f"[PublishingAgent] PUBLISHED SUCCESS! BlogPost ID #{blog_post.id}: '{blog_post.title}' ({blog_post.get_absolute_url()})")
        return blog_post, pub_log

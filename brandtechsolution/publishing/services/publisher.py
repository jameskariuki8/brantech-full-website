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
    def _fit_title(title: str) -> str:
        """Cut a title down to what BlogPost.title can actually hold.

        EditorialArticle.title is max_length=300 and BlogPost.title is
        max_length=200, so a generated title anywhere in that 100-character
        gap saves happily on the article and then raises
        StringDataRightTruncation at publish -- the editor clicks Publish and
        gets a 500, with the article stuck on 'approved'. The writer agent
        takes its title from the model, which is only asked for a headline,
        not given a length budget, so this is reachable in normal use.

        The limit is read off the field rather than hardcoded, so widening the
        column is enough to change the behaviour. Cuts on a word boundary
        where one is close enough to the end to be worth keeping.
        """
        limit = BlogPost._meta.get_field('title').max_length
        text = (title or "").strip()
        if not limit or len(text) <= limit:
            return text

        clipped = text[:limit].rstrip()
        cut = clipped.rfind(' ')
        # Only honour a space in the last quarter; otherwise a title with one
        # very long token would lose most of itself.
        if cut > limit * 0.75:
            clipped = clipped[:cut].rstrip()
        logger.warning(
            "[PublishingAgent] Title exceeded BlogPost.title (%d > %d); truncated.",
            len(text), limit,
        )
        return clipped

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
            blog_post.title = self._fit_title(article.title)
            blog_post.excerpt = article.executive_summary[:300]
            blog_post.content = full_content
            blog_post.category = category
            blog_post.tags = tags_str
            blog_post.save()
        else:
            blog_post = BlogPost.objects.create(
                title=self._fit_title(article.title),
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

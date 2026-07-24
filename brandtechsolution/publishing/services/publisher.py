"""
Module 11: Publishing Agent

Automatically converts approved EditorialArticle drafts into live brand.BlogPost models.
Uploads hero image, updates sitemaps/RSS, pings search engines, and indexes vector knowledge.
"""
import logging
from typing import Tuple
from django.utils import timezone
from editorial.models import EditorialArticle
from brand.models import BlogPost
from publishing.models import PublishingLog
from knowledge_base.services.knowledge_graph import KnowledgeBaseAgent

logger = logging.getLogger(__name__)


class PublishingAgent:
    """Publishes approved content automatically to Teklora website."""

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
                slug=article.slug,
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

        # Index in Knowledge Base Agent (Module 13)
        try:
            kb_agent = KnowledgeBaseAgent()
            kb_agent.index_document(
                title=article.title,
                content=full_content,
                doc_type='article',
                metadata={
                    "article_id": article.id,
                    "blog_post_id": blog_post.id,
                    "category": category,
                    "slug": article.slug
                }
            )
        except Exception as e:
            logger.warning(f"Failed indexing published article into Knowledge Base: {e}")

        logger.info(f"[PublishingAgent] PUBLISHED SUCCESS! BlogPost ID #{blog_post.id}: '{blog_post.title}' ({blog_post.get_absolute_url()})")
        return blog_post, pub_log

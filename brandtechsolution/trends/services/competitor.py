"""
Module 14: Competitor Intelligence Agent

Monitors tech news sources (OpenAI, Google, TechCrunch, Verge, MIT Tech Review) to identify
content gaps and emerging topics not yet covered by Teklora.
"""
import logging
from typing import List, Dict, Any
from trends.models import CompetitorSource, CompetitorArticle, TrendTopic
from trends.services.discovery import TrendDiscoveryEngine

logger = logging.getLogger(__name__)


class CompetitorIntelligenceAgent:
    """Identifies content gaps by monitoring leading technology media outlets."""

    DEFAULT_COMPETITORS = [
        {"name": "TechCrunch", "site_url": "https://techcrunch.com", "feed_url": "https://techcrunch.com/feed/"},
        {"name": "The Verge", "site_url": "https://theverge.com", "feed_url": "https://www.theverge.com/rss/index.xml"},
        {"name": "MIT Technology Review", "site_url": "https://technologyreview.com", "feed_url": "https://www.technologyreview.com/topstories.rss"},
    ]

    def ensure_default_competitors(self):
        for comp in self.DEFAULT_COMPETITORS:
            CompetitorSource.objects.get_or_create(
                name=comp["name"],
                defaults={"site_url": comp["site_url"], "feed_url": comp["feed_url"]}
            )

    def analyze_competitor_gaps(self) -> List[Dict[str, Any]]:
        """Scrapes competitor feeds and finds topics with high gap score for Teklora."""
        engine = TrendDiscoveryEngine()
        gaps = []

        for source in CompetitorSource.objects.filter(is_active=True):
            if source.feed_url:
                items = engine._fetch_rss_feed(source.name, source.feed_url, limit=5)
                for item in items:
                    # Check if Teklora has covered this topic recently
                    already_covered = TrendTopic.objects.filter(title__icontains=item['title'][:20]).exists()
                    gap_score = 9.0 if not already_covered else 2.0

                    art, _ = CompetitorArticle.objects.update_or_create(
                        url=item['source_url'] or f"http://placeholder-{hash(item['title'])}",
                        defaults={
                            'competitor': source,
                            'title': item['title'],
                            'summary': item['summary'],
                            'content_gap_score': gap_score
                        }
                    )
                    if gap_score > 7.0:
                        gaps.append({
                            'competitor': source.name,
                            'title': item['title'],
                            'summary': item['summary'],
                            'gap_score': gap_score,
                        })

        logger.info(f"[CompetitorIntelligenceAgent] Found {len(gaps)} content gap opportunities.")
        return gaps

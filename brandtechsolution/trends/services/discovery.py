"""
Module 1: Trend Discovery Engine

Continuously monitors global technology sources (Hacker News, RSS feeds, GitHub, Tech Blogs),
normalizes data, removes duplicates, categorizes technologies, calculates popularity/velocity,
and stores TrendTopic objects.
"""
import logging
import json
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
from django.utils import timezone
from trends.models import TrendTopic

logger = logging.getLogger(__name__)

# Curated list of high-signal RSS & API feeds for technology discovery
DEFAULT_DISCOVERY_FEEDS = [
    {"name": "Hacker News", "type": "hn_api", "url": "https://hacker-news.firebaseio.com/v0/topstories.json"},
    {"name": "TechCrunch AI", "type": "rss", "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "OpenAI Blog", "type": "rss", "url": "https://openai.com/news/rss.xml"},
    {"name": "Google AI Blog", "type": "rss", "url": "https://blog.google/technology/ai/rss/"},
    {"name": "Anthropic News", "type": "rss", "url": "https://www.anthropic.com/news/rss.xml"},
    {"name": "Dev.to Tech", "type": "rss", "url": "https://dev.to/feed"},
]


class TrendDiscoveryEngine:
    """Discovers, normalizes, deduplicates, and stores tech trends from worldwide sources."""

    def __init__(self, feeds: List[Dict[str, str]] = None):
        self.feeds = feeds or DEFAULT_DISCOVERY_FEEDS

    def run_discovery(self, limit_per_source: int = 10) -> List[TrendTopic]:
        """Runs discovery cycle across all configured feeds and updates database."""
        logger.info("[TrendDiscoveryEngine] Starting global trend discovery run...")
        new_topics = []

        for feed in self.feeds:
            try:
                feed_type = feed.get("type")
                if feed_type == "hn_api":
                    items = self._fetch_hacker_news(limit=limit_per_source)
                elif feed_type == "rss":
                    items = self._fetch_rss_feed(feed["name"], feed["url"], limit=limit_per_source)
                else:
                    items = []

                for item in items:
                    topic = self._process_discovered_item(item)
                    if topic:
                        new_topics.append(topic)
            except Exception as e:
                logger.error(f"[TrendDiscoveryEngine] Error fetching {feed.get('name')}: {e}")

        logger.info(f"[TrendDiscoveryEngine] Discovery finished. Processed {len(new_topics)} topics.")
        return new_topics

    def _fetch_hacker_news(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetches top tech stories from official Hacker News Firebase API."""
        items = []
        try:
            req = urllib.request.Request("https://hacker-news.firebaseio.com/v0/topstories.json", headers={'User-Agent': 'TekloraBot/1.0'})
            with urllib.request.urlopen(req, timeout=5) as response:
                top_ids = json.loads(response.read().decode())[:limit]

            for story_id in top_ids:
                try:
                    item_url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                    req_item = urllib.request.Request(item_url, headers={'User-Agent': 'TekloraBot/1.0'})
                    with urllib.request.urlopen(req_item, timeout=3) as item_res:
                        data = json.loads(item_res.read().decode())
                        if data and data.get('title'):
                            score = data.get('score', 10)
                            comments = data.get('descendants', 0)
                            items.append({
                                'title': data.get('title'),
                                'summary': f"Hacker News submission with {score} points and {comments} comments.",
                                'source': 'Hacker News',
                                'source_url': data.get('url', f"https://news.ycombinator.com/item?id={story_id}"),
                                'popularity_score': min(10.0, score / 50.0),
                                'growth_velocity': min(10.0, (score + comments * 2) / 40.0),
                                'category': self._categorize_title(data.get('title')),
                                'keywords': self._extract_basic_keywords(data.get('title')),
                            })
                except Exception as inner_e:
                    logger.warning(f"Error fetching HN item {story_id}: {inner_e}")
        except Exception as e:
            logger.error(f"Failed fetching HackerNews top stories: {e}")
        return items

    def _fetch_rss_feed(self, source_name: str, feed_url: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Parses RSS XML feed into standardized item dictionaries."""
        items = []
        try:
            req = urllib.request.Request(feed_url, headers={'User-Agent': 'Mozilla/5.0 (TekloraBot/1.0)'})
            with urllib.request.urlopen(req, timeout=5) as response:
                content = response.read()

            root = ET.fromstring(content)
            # Find item tags (works for standard RSS 2.0 & Atom)
            rss_items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

            for el in rss_items[:limit]:
                title_el = el.find('title') or el.find('{http://www.w3.org/2005/Atom}title')
                link_el = el.find('link') or el.find('{http://www.w3.org/2005/Atom}link')
                desc_el = el.find('description') or el.find('{http://www.w3.org/2005/Atom}summary')

                title = title_el.text.strip() if title_el is not None and title_el.text else ""
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                if not link and link_el is not None:
                    link = link_el.attrib.get('href', '')

                summary = desc_el.text.strip() if desc_el is not None and desc_el.text else title

                if title:
                    items.append({
                        'title': title,
                        'summary': summary[:500],
                        'source': source_name,
                        'source_url': link,
                        'popularity_score': 7.5,
                        'growth_velocity': 6.0,
                        'category': self._categorize_title(title),
                        'keywords': self._extract_basic_keywords(title),
                    })
        except Exception as e:
            logger.warning(f"Failed parsing RSS feed '{source_name}' ({feed_url}): {e}")
        return items

    def _process_discovered_item(self, item_data: Dict[str, Any]) -> TrendTopic:
        """Deduplicates against database and creates or updates a TrendTopic record."""
        title = item_data['title'].strip()
        
        # Check existing topic by title prefix
        existing = TrendTopic.objects.filter(title__iexact=title).first()
        if existing:
            # Update scores if popularity grew
            if item_data.get('popularity_score', 0) > existing.popularity_score:
                existing.popularity_score = item_data['popularity_score']
                existing.growth_velocity = item_data.get('growth_velocity', existing.growth_velocity)
                existing.save()
            return existing

        # Create new discovered trend topic
        topic = TrendTopic.objects.create(
            title=title,
            summary=item_data.get('summary', title),
            source=item_data.get('source', 'Web Discovery'),
            source_url=item_data.get('source_url', ''),
            category=item_data.get('category', 'Artificial Intelligence'),
            keywords=item_data.get('keywords', []),
            popularity_score=item_data.get('popularity_score', 5.0),
            growth_velocity=item_data.get('growth_velocity', 5.0),
            future_potential=7.0,
            confidence_score=0.85,
            status='discovered',
            raw_data=item_data
        )
        logger.info(f"[TrendDiscoveryEngine] Created new TrendTopic: {topic.title}")
        return topic

    def _categorize_title(self, title: str) -> str:
        """Simple rule-based classifier for technology topics."""
        t = title.lower()
        if any(w in t for w in ['llm', 'gpt', 'gemini', 'claude', 'neural', 'ai', 'agent', 'model']):
            return 'Artificial Intelligence'
        if any(w in t for w in ['cloud', 'aws', 'azure', 'kubernetes', 'docker', 'serverless']):
            return 'Cloud & Infrastructure'
        if any(w in t for w in ['cybersecurity', 'security', 'vulnerability', 'exploit', 'breach']):
            return 'Cybersecurity'
        if any(w in t for w in ['python', 'rust', 'javascript', 'react', 'django', 'framework', 'api']):
            return 'Software Development'
        if any(w in t for w in ['mobile', 'africa', 'fintech', 'mpesa', 'startup']):
            return 'African Tech Ecosystem'
        return 'Innovation & Frontier Tech'

    def _extract_basic_keywords(self, title: str) -> List[str]:
        """Extracts key nouns/tech words from title."""
        words = [w.strip(":,.-()\"'") for w in title.split()]
        filtered = [w for w in words if len(w) > 3 and w.lower() not in ['this', 'that', 'with', 'from', 'have', 'what']]
        return list(set(filtered))[:6]

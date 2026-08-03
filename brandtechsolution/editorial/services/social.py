"""
Module 9: Multi-Platform Content Agent

Generates an entire multi-channel media ecosystem from a single article:
LinkedIn posts, Twitter threads, Instagram carousels, email newsletters, Medium/Dev.to drafts,
podcast outlines, YouTube/TikTok scripts, and executive summaries.
"""
import logging
import json
from typing import Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from brandtechsolution.config import config
from editorial.models import EditorialArticle, SocialPackage

logger = logging.getLogger(__name__)

MULTI_PLATFORM_PROMPT = """You are the Head of Growth & Social Strategy at Teklora Media.
Transform this long-form article into a multi-platform content ecosystem.

Article Title: {title}
Executive Summary: {executive_summary}
Technical Overview: {technical_explanation}
African Opportunities: {african_perspective}

Generate tailored content for every platform specified below:
1. LinkedIn Post (professional hook, key takeaways, call to action)
2. LinkedIn Long-form Article
3. Twitter Thread (5-7 punchy tweets)
4. Facebook Post
5. Instagram Carousel (5 slide outlines with headlines & bullet points)
6. Newsletter Edition (engaging intro, breakdown, subscriber CTA)
7. Medium & Dev.to Adaptations
8. Podcast Episode Outline (host opening, 3 main discussion segments, closing)
9. YouTube Video Script (hook, intro, breakdown visual cues, outro)
10. TikTok / Short Video Script (15-60 second rapid narration script)

Return your response ONLY as a JSON object matching this schema:
{{
  "linkedin_post": "Engaging LinkedIn post...",
  "linkedin_article": "Detailed LinkedIn article draft...",
  "twitter_thread": [
    "1/7 Tweet hook...",
    "2/7 Key context...",
    "3/7 Technical breakdown...",
    "4/7 African perspective...",
    "5/7 Future outlook...",
    "6/7 Summary...",
    "7/7 Link to full Teklora article..."
  ],
  "facebook_post": "Facebook post draft...",
  "instagram_carousel": [
    {{"slide": 1, "headline": "Title Slide", "bullet": "Key hook"}},
    {{"slide": 2, "headline": "The Problem", "bullet": "Why it matters"}},
    {{"slide": 3, "headline": "The Breakthrough", "bullet": "How it works"}},
    {{"slide": 4, "headline": "African Opportunity", "bullet": "Local impact"}},
    {{"slide": 5, "headline": "Read More", "bullet": "Visit Teklora.co.ke"}}
  ],
  "newsletter": "Newsletter edition text...",
  "medium_article": "Medium draft...",
  "devto_article": "Dev.to draft...",
  "podcast_outline": "Podcast outline...",
  "youtube_script": "YouTube script...",
  "tiktok_script": "TikTok script...",
  "executive_summary_one_pager": "1-page summary..."
}}
"""


class MultiPlatformContentAgent:
    """Generates multi-channel distribution content from articles."""

    def __init__(self):
        try:
            self.model = ChatGoogleGenerativeAI(
                model=config.gemini_chat_model,
                google_api_key=config.google_api_key,
                temperature=0.4
            )
        except Exception as e:
            logger.warning(f"MultiPlatformContentAgent LLM init failed: {e}")
            self.model = None

    def generate_social_ecosystem(self, article: EditorialArticle) -> SocialPackage:
        """Generates SocialPackage for an article."""
        logger.info(f"[MultiPlatformContentAgent] Generating social package for '{article.title}'...")

        existing = SocialPackage.objects.filter(article=article).first()
        if existing:
            return existing

        social_data = self._generate_all_channels(article)

        package = SocialPackage.objects.create(
            article=article,
            linkedin_post=social_data.get('linkedin_post', f"🚀 Exciting developments in {article.title}! Read our deep dive on Teklora."),
            linkedin_article=social_data.get('linkedin_article', article.get_full_markdown_content()),
            twitter_thread=social_data.get('twitter_thread', [f"1/🧵 Deep dive into {article.title}. Read on Teklora!"]),
            facebook_post=social_data.get('facebook_post', f"New on Teklora: {article.title}"),
            instagram_carousel=social_data.get('instagram_carousel', []),
            newsletter=social_data.get('newsletter', f"Welcome to Teklora Innovation Dispatch.\n\nFeatured: {article.title}\n\n{article.executive_summary}"),
            medium_article=social_data.get('medium_article', article.get_full_markdown_content()),
            devto_article=social_data.get('devto_article', article.get_full_markdown_content()),
            podcast_outline=social_data.get('podcast_outline', f"Episode: The Rise of {article.title}"),
            youtube_script=social_data.get('youtube_script', f"Script for {article.title}"),
            tiktok_script=social_data.get('tiktok_script', f"15s Script for {article.title}"),
            executive_summary_one_pager=social_data.get('executive_summary_one_pager', article.executive_summary)
        )
        logger.info(f"[MultiPlatformContentAgent] Social package created for '{article.title}'")
        return package

    def _generate_all_channels(self, article: EditorialArticle) -> Dict[str, Any]:
        if not self.model:
            return self._fallback_channels(article)

        try:
            prompt = MULTI_PLATFORM_PROMPT.format(
                title=article.title,
                executive_summary=article.executive_summary,
                technical_explanation=article.technical_explanation,
                african_perspective=article.african_perspective
            )
            res = self.model.invoke([
                SystemMessage(content="You are a social media growth strategist. Return ONLY raw JSON."),
                HumanMessage(content=prompt)
            ])
            content = res.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()

            return json.loads(content, strict=False)
        except Exception as e:
            logger.error(f"[MultiPlatformContentAgent] Social ecosystem generation error for '{article.title}': {e}")
            return self._fallback_channels(article)

    def _fallback_channels(self, article: EditorialArticle) -> Dict[str, Any]:
        return {
            "linkedin_post": f"💡 How {article.title} is redefining tech innovation. Explore our technical analysis on Teklora: {article.executive_summary}",
            "linkedin_article": article.get_full_markdown_content(),
            "twitter_thread": [
                f"1/ 🚀 Discovering {article.title}: A deep dive into technical architecture & African tech opportunities.",
                f"2/ 🔑 Key Insight: {article.executive_summary}",
                f"3/ 🌍 African Perspective: {article.african_perspective[:200]}...",
                f"4/ 🔗 Read the full story on Teklora Media!"
            ],
            "facebook_post": f"Inside {article.title} — Technical Analysis & African Opportunities on Teklora.",
            "instagram_carousel": [
                {"slide": 1, "headline": article.title, "bullet": article.subtitle},
                {"slide": 2, "headline": "Key Takeaway", "bullet": article.executive_summary[:100]}
            ],
            "newsletter": f"Teklora Innovation Dispatch\n\nFeatured Insight: {article.title}\n\n{article.executive_summary}",
            "medium_article": article.get_full_markdown_content(),
            "devto_article": article.get_full_markdown_content(),
            "podcast_outline": f"Host Introduction to {article.title}\nSegment 1: Technical Foundations\nSegment 2: African Tech Ecosystem Impact\nConclusion.",
            "youtube_script": f"[Intro Visual] Glowing Teklora Logo\nNarrator: Welcome back! Today we look into {article.title}...",
            "tiktok_script": f"Here is why {article.title} matters in under 30 seconds! {article.executive_summary[:100]}",
            "executive_summary_one_pager": article.executive_summary
        }

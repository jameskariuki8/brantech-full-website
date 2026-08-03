"""
Module 6: AI Writer Agent

Generates professional, human-grade, structured long-form articles for Teklora.
Ensures storytelling, SEO optimization, technical accuracy, and African ecosystem perspective.
"""
import logging
import json
from typing import Dict, Any, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from brandtechsolution.config import config
from research.models import VerifiedFactReport
from editorial.models import EditorialArticle

logger = logging.getLogger(__name__)

ARTICLE_WRITER_PROMPT = """You are the Senior Editor-in-Chief at Teklora Media (Africa's premier technology innovation publication).
Write a masterpiece, long-form, highly readable technology article based on this verified research dossier.

Topic Title: {title}
Verified Facts & Technical Overview:
{verified_text}

African Ecosystem Perspective:
{african_perspective}

Target Audience Strategy: {target_audience} ({tone})

Requirements:
- Journalistic quality, human-like voice, clear explanations, compelling storytelling.
- Highly structured with distinct sections.
- SEO optimized, clear headings, engaging hook.
- Strong focus on African technological context, opportunities, and enterprise impact.

Return your complete article ONLY as a valid JSON object matching this schema:
{{
  "title": "Compelling Title",
  "subtitle": "Engaging Subtitle summarizing the core breakthrough",
  "executive_summary": "High-impact 2-sentence summary...",
  "hero_paragraph": "Atmospheric opening paragraph...",
  "introduction": "Comprehensive introduction setting up the technology...",
  "problem_statement": "What bottleneck or challenge does this solve?",
  "historical_context": "Background leading to this breakthrough...",
  "current_developments": "What is happening right now in the industry...",
  "technical_explanation": "In-depth engineering and architectural deep dive...",
  "industry_impact": "Global enterprise and market impact...",
  "african_perspective": "Deep analysis of impact on African tech, developers, and startups...",
  "case_studies": "Real or representative enterprise implementation examples...",
  "expert_insights": "Key architectural quotes and strategic lessons...",
  "future_predictions": "Where this technology will be in 2-5 years...",
  "conclusion": "Final memorable synthesis and takeaways...",
  "call_to_action": "Subscribe to Teklora Innovation Dispatch...",
  "faqs": [
    {{"question": "FAQ 1?", "answer": "Clear answer..."}},
    {{"question": "FAQ 2?", "answer": "Clear answer..."}}
  ],
  "meta_description": "Compelling meta description under 160 characters",
  "keywords": ["keyword1", "keyword2", "keyword3"],
  "estimated_reading_time": 7
}}
"""


class AIWriterAgent:
    """Generates long-form, SEO-optimized tech articles from verified research reports."""

    def __init__(self):
        try:
            self.model = ChatGoogleGenerativeAI(
                model=config.gemini_chat_model,
                google_api_key=config.google_api_key,
                temperature=0.4
            )
        except Exception as e:
            logger.warning(f"AIWriterAgent LLM init failed: {e}")
            self.model = None

    def write_article(self, report: VerifiedFactReport, strategy: Dict[str, Any]) -> EditorialArticle:
        """Generates complete EditorialArticle object."""
        logger.info(f"[AIWriterAgent] Drafting article for '{report.dossier.topic.title}'...")

        existing = EditorialArticle.objects.filter(verification_report=report).first()
        if existing:
            return existing

        article_data = self._generate_draft(report, strategy)

        article = EditorialArticle.objects.create(
            topic=report.dossier.topic,
            verification_report=report,
            title=article_data.get('title', report.dossier.topic.title),
            subtitle=article_data.get('subtitle', 'Emerging Tech Insight'),
            executive_summary=article_data.get('executive_summary', report.dossier.topic.summary),
            hero_paragraph=article_data.get('hero_paragraph', ''),
            introduction=article_data.get('introduction', ''),
            problem_statement=article_data.get('problem_statement', ''),
            historical_context=article_data.get('historical_context', ''),
            current_developments=article_data.get('current_developments', ''),
            technical_explanation=article_data.get('technical_explanation', report.dossier.technical_explanations),
            industry_impact=article_data.get('industry_impact', report.dossier.industry_applications),
            african_perspective=article_data.get('african_perspective', report.dossier.african_opportunities),
            case_studies=article_data.get('case_studies', ''),
            expert_insights=article_data.get('expert_insights', ''),
            future_predictions=article_data.get('future_predictions', report.dossier.future_outlook),
            conclusion=article_data.get('conclusion', ''),
            call_to_action=article_data.get('call_to_action', 'Subscribe to Teklora Innovation Dispatch.'),
            faqs=article_data.get('faqs', []),
            references=report.dossier.sources,
            meta_description=article_data.get('meta_description', report.dossier.topic.summary[:150]),
            keywords=article_data.get('keywords', report.dossier.topic.keywords),
            target_audience=strategy.get('target_audience', 'developers'),
            tone=strategy.get('tone', 'Analytical & Authoritative'),
            reading_time_minutes=article_data.get('estimated_reading_time', 6),
            status='review_pending'
        )

        report.dossier.topic.status = 'approved_for_article'
        report.dossier.topic.save()

        logger.info(f"[AIWriterAgent] Draft complete: '{article.title}' (#{article.id}). Status set to review_pending.")
        return article

    def _generate_draft(self, report: VerifiedFactReport, strategy: Dict[str, Any]) -> Dict[str, Any]:
        if not self.model:
            return self._fallback_draft(report)

        try:
            prompt = ARTICLE_WRITER_PROMPT.format(
                title=report.dossier.topic.title,
                verified_text=report.verified_dossier,
                african_perspective=report.dossier.african_opportunities,
                target_audience=strategy.get('target_audience', 'developers'),
                tone=strategy.get('tone', 'Authoritative')
            )
            res = self.model.invoke([
                SystemMessage(content="You are an award-winning tech journalist. Return ONLY raw JSON."),
                HumanMessage(content=prompt)
            ])
            content = res.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()

            return json.loads(content, strict=False)
        except Exception as e:
            logger.error(f"[AIWriterAgent] LLM generation error for '{report.dossier.topic.title}': {e}")
            return self._fallback_draft(report)

    def _fallback_draft(self, report: VerifiedFactReport) -> Dict[str, Any]:
        d = report.dossier
        return {
            "title": f"Understanding {d.topic.title}: Architecture, Impact, and African Opportunities",
            "subtitle": f"A deep dive into how {d.topic.title} is shaping modern technology ecosystems.",
            "executive_summary": f"{d.topic.title} represents a significant advancement in software and AI infrastructure.",
            "hero_paragraph": f"As technology continues to accelerate, {d.topic.title} has emerged as a key area of focus for engineers and businesses.",
            "introduction": f"In this comprehensive analysis, we explore the rise of {d.topic.title} and its implications for global tech.",
            "problem_statement": f"Traditional approaches faced limitations in scalability and efficiency, which {d.topic.title} directly addresses.",
            "historical_context": "Developed through iterative research across distributed systems and AI advancement.",
            "current_developments": f"Leading organizations are rapidly adopting {d.topic.title} into their production workflows.",
            "technical_explanation": d.technical_explanations,
            "industry_impact": d.industry_applications or "Transforms operational speed and system reliability.",
            "african_perspective": d.african_opportunities or "Presents high strategic value for tech hubs in Kenya, Nigeria, and across Africa.",
            "case_studies": "Representative enterprise deployments demonstrate a 40% improvement in performance.",
            "expert_insights": "Industry leaders highlight modularity and developer experience as primary drivers.",
            "future_predictions": d.future_outlook or "Expected to become a standard component in modern tech stacks over the coming years.",
            "conclusion": f"Teklora will continue to monitor developments in {d.topic.title} as adoption grows.",
            "call_to_action": "Join the Teklora community for more technology insights and deep dives.",
            "faqs": [{"question": f"What is {d.topic.title}?", "answer": d.topic.summary}],
            "meta_description": f"Explore {d.topic.title}: technical analysis, global impact, and African ecosystem opportunities.",
            "keywords": d.topic.keywords,
            "estimated_reading_time": 6
        }

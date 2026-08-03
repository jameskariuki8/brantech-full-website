"""
Module 2: Trend Intelligence Agent

Evaluates and scores every discovered trend topic based on Novelty, Business Relevance,
African Relevance, Developer Interest, Virality, and Future Potential using Gemini API.
Assigns a Priority Score and promotes high-scoring trends for research.
"""
import logging
import json
from typing import Optional, Dict, Any
from django.conf import settings
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from brandtechsolution.config import config
from trends.models import TrendTopic

logger = logging.getLogger(__name__)

INTELLIGENCE_PROMPT = """You are the Chief Intelligence Officer at Teklora, an African technology media and innovation publication.
Analyze the following tech trend and score it on a scale of 0.0 to 10.0 across 6 criteria:

1. Novelty: How new or groundbreaking is this topic?
2. Business Relevance: How significant is the business/enterprise impact?
3. African Relevance: How applicable, impactful, or interesting is this to the African tech ecosystem, developers, and startups?
4. Developer Interest: How excited will software engineers, AI developers, and tech builders be?
5. Virality: How likely is this to drive high social sharing and discussion?
6. Future Potential: Will this topic remain strategically important over the next 12-36 months?

Trend Title: {title}
Category: {category}
Summary: {summary}
Source: {source}

Return your evaluation ONLY as a valid JSON object matching this structure:
{{
  "novelty_score": 8.5,
  "business_relevance_score": 7.0,
  "african_relevance_score": 8.0,
  "developer_interest_score": 9.0,
  "virality_score": 7.5,
  "future_potential": 8.5,
  "reasoning": "Brief explanation of why this topic received these scores."
}}
"""


class TrendIntelligenceAgent:
    """Evaluates tech trends and computes Priority Score for editorial workflow."""

    def __init__(self, priority_threshold: float = 6.5):
        self.priority_threshold = priority_threshold
        try:
            self.model = ChatGoogleGenerativeAI(
                model=config.gemini_chat_model,
                google_api_key=config.google_api_key,
                temperature=0.2
            )
        except Exception as e:
            logger.warning(f"Gemini LLM initialization warning in TrendIntelligenceAgent: {e}")
            self.model = None

    def evaluate_trend(self, topic: TrendTopic) -> TrendTopic:
        """Evaluates a single TrendTopic and updates its intelligence metrics."""
        logger.info(f"[TrendIntelligenceAgent] Scoring topic: '{topic.title}'")

        scores = self._call_ai_evaluator(topic)
        if not scores:
            scores = self._heuristic_fallback_evaluator(topic)

        topic.novelty_score = scores.get('novelty_score', 6.0)
        topic.business_relevance_score = scores.get('business_relevance_score', 6.0)
        topic.african_relevance_score = scores.get('african_relevance_score', 6.0)
        topic.developer_interest_score = scores.get('developer_interest_score', 6.0)
        topic.virality_score = scores.get('virality_score', 6.0)
        topic.future_potential = scores.get('future_potential', 7.0)

        # Weighted calculation for Priority Score:
        # African relevance (20%), Developer Interest (20%), Business (20%), Novelty (15%), Virality (15%), Future Potential (10%)
        weighted_score = (
            topic.african_relevance_score * 0.20 +
            topic.developer_interest_score * 0.20 +
            topic.business_relevance_score * 0.20 +
            topic.novelty_score * 0.15 +
            topic.virality_score * 0.15 +
            topic.future_potential * 0.10
        )
        topic.priority_score = round(weighted_score, 2)

        if topic.priority_score >= self.priority_threshold:
            topic.status = 'prioritized'
            logger.info(f"[TrendIntelligenceAgent] PROMOTED topic '{topic.title}' -> Priority {topic.priority_score:.1f}")
        else:
            logger.info(f"[TrendIntelligenceAgent] Topic '{topic.title}' scored {topic.priority_score:.1f} (below threshold {self.priority_threshold})")

        topic.save()
        return topic

    def evaluate_all_discovered(self) -> int:
        """Evaluates all pending discovered topics."""
        discovered = TrendTopic.objects.filter(status='discovered')
        count = 0
        for topic in discovered:
            self.evaluate_trend(topic)
            count += 1
        return count

    def _call_ai_evaluator(self, topic: TrendTopic) -> Optional[Dict[str, float]]:
        """Queries Gemini LLM for structured scoring."""
        if not self.model:
            return None

        try:
            prompt = INTELLIGENCE_PROMPT.format(
                title=topic.title,
                category=topic.category,
                summary=topic.summary,
                source=topic.source
            )
            response = self.model.invoke([
                SystemMessage(content="You are an expert tech journalism evaluation agent. Return ONLY raw JSON."),
                HumanMessage(content=prompt)
            ])
            
            content = response.content.strip()
            # Clean markdown codeblocks if wrapped
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()

            return json.loads(content, strict=False)
        except Exception as e:
            logger.error(f"[TrendIntelligenceAgent] LLM scoring error for topic '{topic.title}': {e}")
            return None

    def _heuristic_fallback_evaluator(self, topic: TrendTopic) -> Dict[str, float]:
        """Fallback scoring rule when LLM is unavailable."""
        pop = topic.popularity_score or 5.0
        return {
            'novelty_score': min(10.0, pop * 0.9),
            'business_relevance_score': 7.0,
            'african_relevance_score': 7.5,
            'developer_interest_score': min(10.0, pop * 1.1),
            'virality_score': pop,
            'future_potential': 7.5,
        }

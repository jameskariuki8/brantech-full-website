"""
Module 3: Research Agent

Acts as an investigative technology journalist. Performs multi-source research synthesis
to build a structured Research Dossier covering timelines, key concepts, technical breakdowns,
advantages/limitations, African opportunities, and reference sources.
"""
import logging
import json
from typing import Optional, Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from brandtechsolution.config import config
from trends.models import TrendTopic
from research.models import ResearchDossier

logger = logging.getLogger(__name__)

RESEARCH_PROMPT = """You are an Investigative Technology Journalist and Research Specialist for Teklora Media.
Perform deep research synthesis on the following technology topic:

Topic Title: {title}
Category: {category}
Summary Context: {summary}
Initial Source: {source} ({source_url})

Analyze this topic and produce a comprehensive research dossier containing:
1. Key Concepts: 3-5 core concepts and technical definitions.
2. Timeline: 3 key historical milestones leading to this innovation.
3. Technical Explanation: A deep architectural and engineering breakdown (how it works under the hood).
4. Advantages & Limitations: Pros, cons, bottlenecks, and performance tradeoffs.
5. Industry Applications: How global enterprises and tech companies are adopting it.
6. African Opportunities: Specific strategic opportunities, startup use cases, developer opportunities, and economic impact for Africa (e.g. Kenya, Nigeria, South Africa, Egypt, Rwanda).
7. Future Outlook: What to expect over the next 2-5 years.
8. Primary Sources: 3-5 realistic reference citations with titles and URLs.

Return your response ONLY as a JSON object matching this schema:
{{
  "key_concepts": [
    {{"term": "Concept Name", "definition": "Explanation..."}}
  ],
  "timeline": [
    {{"year_or_phase": "2023", "event": "Milestone description..."}}
  ],
  "technical_explanations": "Detailed multi-paragraph technical breakdown...",
  "advantages_and_limitations": {{
    "advantages": ["Advantage 1", "Advantage 2"],
    "limitations": ["Limitation 1", "Limitation 2"]
  }},
  "industry_applications": "Global enterprise use cases...",
  "african_opportunities": "Specific African ecosystem opportunities...",
  "future_outlook": "2-5 year strategic forecast...",
  "sources": [
    {{"title": "Official Announcement", "url": "{source_url}"}}
  ],
  "structured_dossier": "Complete compiled markdown research summary..."
}}
"""


class ResearchAgent:
    """Investigates technology topics deeply and generates a ResearchDossier."""

    def __init__(self):
        try:
            self.model = ChatGoogleGenerativeAI(
                model=config.gemini_chat_model,
                google_api_key=config.google_api_key,
                temperature=0.3
            )
        except Exception as e:
            logger.warning(f"ResearchAgent LLM init failed: {e}")
            self.model = None

    def conduct_research(self, topic: TrendTopic) -> ResearchDossier:
        """Executes deep research for a given TrendTopic."""
        logger.info(f"[ResearchAgent] Beginning deep research for '{topic.title}'...")
        
        # Check if dossier exists
        existing = ResearchDossier.objects.filter(topic=topic).first()
        if existing:
            return existing

        topic.status = 'researching'
        topic.save()

        research_data = self._synthesize_research(topic)

        dossier = ResearchDossier.objects.create(
            topic=topic,
            key_concepts=research_data.get('key_concepts', []),
            timeline=research_data.get('timeline', []),
            technical_explanations=research_data.get('technical_explanations', 'Technical analysis pending.'),
            advantages_and_limitations=research_data.get('advantages_and_limitations', {}),
            industry_applications=research_data.get('industry_applications', ''),
            african_opportunities=research_data.get('african_opportunities', 'Significant potential for local developer adoption and fintech/agritech scaling.'),
            future_outlook=research_data.get('future_outlook', ''),
            sources=research_data.get('sources', [{'title': topic.source, 'url': topic.source_url}]),
            structured_dossier=research_data.get('structured_dossier', f"# Research Dossier: {topic.title}\n\n{topic.summary}")
        )
        logger.info(f"[ResearchAgent] Successfully created dossier for '{topic.title}'")
        return dossier

    def _synthesize_research(self, topic: TrendTopic) -> Dict[str, Any]:
        """Queries Gemini for deep research dossier."""
        if not self.model:
            return self._fallback_research(topic)

        try:
            prompt = RESEARCH_PROMPT.format(
                title=topic.title,
                category=topic.category,
                summary=topic.summary,
                source=topic.source,
                source_url=topic.source_url or "https://teklora.co.ke"
            )
            res = self.model.invoke([
                SystemMessage(content="You are an expert tech journalist researcher. Return ONLY raw JSON."),
                HumanMessage(content=prompt)
            ])
            content = res.content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                if content.startswith("json"):
                    content = content[4:].strip()

            return json.loads(content, strict=False)
        except Exception as e:
            logger.error(f"[ResearchAgent] AI research synthesis error for '{topic.title}': {e}")
            return self._fallback_research(topic)

    def _fallback_research(self, topic: TrendTopic) -> Dict[str, Any]:
        """Provides structured fallback dossier when offline or on API error."""
        return {
            "key_concepts": [{"term": topic.title, "definition": topic.summary}],
            "timeline": [{"year_or_phase": "Recent", "event": "Discovered across tech channels"}],
            "technical_explanations": f"Deep architectural breakdown of {topic.title}. Focuses on scalability, reliability, and modular integration.",
            "advantages_and_limitations": {
                "advantages": ["High efficiency", "Scalable architecture"],
                "limitations": ["Requires initial setup and evaluation"]
            },
            "industry_applications": f"Applied in enterprise technology, software infrastructure, and {topic.category}.",
            "african_opportunities": f"Great opportunity for African engineers and startups to leverage {topic.title} for regional tech solutions.",
            "future_outlook": "Expected to see rapid adoption over the next 12-24 months.",
            "sources": [{"title": topic.source, "url": topic.source_url or ""}],
            "structured_dossier": f"# Research Dossier: {topic.title}\n\n{topic.summary}"
        }

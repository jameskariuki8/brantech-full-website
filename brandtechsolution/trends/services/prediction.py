"""
Module 15: Trend Prediction Agent

Predicts upcoming technology innovations and shifts (next month, next quarter, next year)
using search growth, GitHub signals, VC funding trends, and LLM extrapolations.
"""
import logging
import json
from typing import List, Dict, Any
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from brandtechsolution.config import config
from trends.models import TrendPrediction, TrendTopic

logger = logging.getLogger(__name__)

PREDICTION_PROMPT = """You are a Technology Futures & Predictive Intelligence Analyst at Teklora.
Based on current trending topics in the industry, predict 3 upcoming technology trends that will emerge over the next {timeframe}.

Current industry signals:
{signals_text}

For each prediction, provide:
1. Topic Name
2. Category
3. Confidence Score (0.0 to 1.0)
4. Evidence Signals (GitHub velocity, investment trends, search growth)
5. Detailed Forecast Report (why this will trend, African market implications, enterprise impact)

Return ONLY a JSON list of objects matching this schema:
[
  {{
    "topic_name": "Autonomous Multi-Agent Orchestration Frameworks",
    "category": "Artificial Intelligence",
    "confidence_score": 0.88,
    "evidence_signals": {{"github_growth": "450%", "vc_investments": "High", "search_intent": "Explosive"}},
    "prediction_report": "Detailed forecast explanation..."
  }}
]
"""


class TrendPredictionAgent:
    """Generates technology forecast reports for Teklora's readers."""

    def __init__(self):
        try:
            self.model = ChatGoogleGenerativeAI(
                model=config.gemini_chat_model,
                google_api_key=config.google_api_key,
                temperature=0.4
            )
        except Exception as e:
            logger.warning(f"TrendPredictionAgent LLM init failed: {e}")
            self.model = None

    def generate_predictions(self, timeframe: str = 'next_quarter') -> List[TrendPrediction]:
        """Generates future technology predictions based on active trend topics."""
        recent_trends = TrendTopic.objects.all()[:15]
        signals = [f"- {t.title} (Category: {t.category}, Priority: {t.priority_score})" for t in recent_trends]
        signals_text = "\n".join(signals) if signals else "- Agentic AI Workflows\n- Localized LLMs in Africa\n- Quantum-safe Cryptography"

        predictions = []
        if self.model:
            try:
                prompt = PREDICTION_PROMPT.format(timeframe=timeframe, signals_text=signals_text)
                res = self.model.invoke([
                    SystemMessage(content="You are a tech trend forecasting expert. Output raw JSON only."),
                    HumanMessage(content=prompt)
                ])
                content = res.content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    if content.startswith("json"):
                        content = content[4:].strip()

                items = json.loads(content, strict=False)
                for item in items:
                    pred = TrendPrediction.objects.create(
                        topic_name=item.get('topic_name', 'Emerging Tech Topic'),
                        category=item.get('category', 'Artificial Intelligence'),
                        timeframe=timeframe,
                        confidence_score=item.get('confidence_score', 0.8),
                        evidence_signals=item.get('evidence_signals', {}),
                        prediction_report=item.get('prediction_report', 'Forecast details')
                    )
                    predictions.append(pred)
            except Exception as e:
                logger.error(f"[TrendPredictionAgent] Error generating predictions: {e}")

        logger.info(f"[TrendPredictionAgent] Created {len(predictions)} forecasts for {timeframe}.")
        return predictions

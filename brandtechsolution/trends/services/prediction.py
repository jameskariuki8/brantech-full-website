"""
Module 15: Trend Prediction Agent

Forecasts upcoming technology shifts from the signals already in the trend
table, and writes them up as TrendPrediction rows.

On the harness since step 6. The schema changed shape in the move: the prompt
used to ask for a bare JSON *list*, which leaves nowhere to put a status, so a
forecaster with nothing to forecast had no way to say so and would invent
three. Predictions now arrive wrapped, and the wrapper is what carries the
abstention.
"""
import logging

from pydantic import BaseModel, Field

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.contract import AgentOutput
from ai_workflows.harness.llm import ModelRole
from ai_workflows.harness.persona import Persona
from trends.models import TrendPrediction, TrendTopic

logger = logging.getLogger(__name__)

# How many trend rows are shown to the forecaster as signal. Unchanged from
# before the rewrite; it is a prompt-size choice, not a claim about how many
# matter.
SIGNAL_LIMIT = 15


class Forecast(BaseModel):
    """One predicted trend."""

    topic_name: str = ""
    category: str = "Artificial Intelligence"
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    # Left loose: it lands in a JSONField and its keys are the model's choice
    # of which signals it found -- GitHub velocity for one topic, funding for
    # another. Pinning the keys would make it fill the ones it had nothing for.
    evidence_signals: dict = Field(default_factory=dict)
    prediction_report: str = ""

    @property
    def is_complete(self) -> bool:
        return bool(self.topic_name and self.prediction_report)


class ForecastSet(AgentOutput):
    predictions: list[Forecast] = Field(default_factory=list)


PERSONA = Persona(
    name="trend_prediction",
    role="a Technology Futures and Predictive Intelligence Analyst at Teklora",
    directives=(
        "Extrapolate from the signals you are given -- search growth, GitHub "
        "velocity, funding activity -- and say which signal each forecast rests on.",
        "Give each forecast a confidence score that reflects the strength of "
        "the evidence rather than the appeal of the idea.",
        "Cover what a forecast means for African markets and for enterprise "
        "adoption, not only for the technology itself.",
    ),
    constraints=(
        "Do not present an extrapolation as a reported fact.",
        "Do not invent growth figures, funding rounds or adoption rates. If a "
        "signal is not in the material you were given, you do not have it.",
        "Return no predictions rather than padding to a count.",
    ),
)

PREDICTION_PROMPT = """Predict up to 3 technology trends that will emerge over the next {timeframe}.

Current industry signals:
{signals_text}

Base each forecast on these signals. If they do not support a forecast, return
no predictions and say why.
"""


class TrendPredictionAgent(Agent):
    """Generates technology forecast reports for Teklora's readers."""

    name = "trend_prediction"
    persona = PERSONA
    model_role = ModelRole.ANALYTIC
    tool_suite = "trend_prediction"

    def run(self, request: AgentRequest) -> AgentResult:
        timeframe = request.payload.get("timeframe", "next_quarter")
        signals = request.payload["signals_text"]

        forecasts = self.ask(
            PREDICTION_PROMPT.format(timeframe=timeframe, signals_text=signals),
            ForecastSet,
        )
        return AgentResult(
            agent=self.name, output=forecasts,
            abstained=forecasts.abstained, notes=forecasts.notes,
        )

    def generate_predictions(self, timeframe: str = 'next_quarter') -> list[TrendPrediction]:
        """Forecast from the current trend table.

        Returns an empty list when there is nothing to forecast from or when
        the agent declined. The placeholder signal list this used to fall back
        on -- three hardcoded topic names -- is gone: forecasting from invented
        signals produces an invented forecast that reads exactly like a real
        one.
        """
        recent = TrendTopic.objects.all()[:SIGNAL_LIMIT]
        if not recent:
            logger.info("[trend_prediction] no trend signals recorded yet; nothing to forecast")
            return []

        signals_text = "\n".join(
            f"- {t.title} (category: {t.category}, priority: {t.priority_score})"
            for t in recent
        )

        result = self.execute(AgentRequest(
            payload={"timeframe": timeframe, "signals_text": signals_text}
        ))
        if result.abstained:
            logger.warning(
                "[trend_prediction] declined to forecast %s: %s",
                timeframe, result.notes or "no reason given",
            )
            return []

        created = []
        for forecast in result.output.predictions:
            if not forecast.is_complete:
                # A named topic with no report, or a report with no topic, is
                # half an answer. Dropping it beats storing a row an editor has
                # to open to discover is empty.
                logger.warning(
                    "[trend_prediction] dropped an incomplete forecast: %r",
                    forecast.topic_name or "(unnamed)",
                )
                continue

            created.append(TrendPrediction.objects.create(
                topic_name=forecast.topic_name,
                category=forecast.category,
                timeframe=timeframe,
                confidence_score=forecast.confidence_score,
                evidence_signals=forecast.evidence_signals,
                prediction_report=forecast.prediction_report,
            ))

        logger.info("[trend_prediction] created %d forecasts for %s", len(created), timeframe)
        return created

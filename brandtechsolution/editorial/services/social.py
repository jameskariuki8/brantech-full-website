"""
Module 9: Multi-Platform Content Agent

Turns one article into the channel-specific versions of it: LinkedIn, X,
Instagram, the newsletter, Medium and Dev.to, a podcast outline, and video
scripts.

On the harness since step 6. This agent's fallback was the least dangerous of
the six -- it pasted the article's own markdown into every channel and stuck an
emoji on the front -- but it was still a fallback: the package existed, looked
populated in the admin, and would have gone out as a LinkedIn post that was
actually a 2,000-word markdown document.
"""
import logging

from pydantic import Field

from ai_workflows.harness.base import Agent, AgentRequest, AgentResult
from ai_workflows.harness.contract import AgentOutput, ask, require
from ai_workflows.harness.llm import ModelRole
from ai_workflows.harness.persona import Persona
from editorial.models import EditorialArticle, SocialPackage

logger = logging.getLogger(__name__)


class SocialEcosystem(AgentOutput):
    """One article, rewritten for every channel."""

    linkedin_post: str = ""
    linkedin_article: str = ""
    twitter_thread: list = Field(default_factory=list)
    facebook_post: str = ""
    instagram_carousel: list = Field(default_factory=list)
    newsletter: str = ""
    medium_article: str = ""
    devto_article: str = ""
    podcast_outline: str = ""
    youtube_script: str = ""
    tiktok_script: str = ""
    executive_summary_one_pager: str = ""


PERSONA = Persona(
    name="social",
    role="the Head of Growth and Social Strategy at Teklora Media",
    directives=(
        "Rewrite for each channel rather than reformatting for it. A LinkedIn "
        "post and a TikTok script are different pieces of writing about the "
        "same story.",
        "Open with the specific thing that is new, not with a rhetorical "
        "question.",
        "Keep the African angle in the versions where it is the story.",
    ),
    constraints=(
        "Use only what the article establishes. A shorter format is not "
        "licence to sharpen a claim past what was verified.",
        "Do not add figures, superlatives or urgency the article does not "
        "support.",
    ),
)

SOCIAL_PROMPT = """Adapt this article for every channel below.

Article Title: {title}
Executive Summary: {executive_summary}
Technical Overview: {technical_explanation}
African Opportunities: {african_perspective}

Channels:
1. LinkedIn post -- professional hook, key takeaways, call to action.
2. LinkedIn long-form article.
3. X/Twitter thread -- 5-7 posts.
4. Facebook post.
5. Instagram carousel -- 5 slides, each with a headline and a bullet.
6. Newsletter edition -- intro, breakdown, subscriber CTA.
7. Medium adaptation.
8. Dev.to adaptation.
9. Podcast outline -- opening, three segments, close.
10. YouTube script -- hook, intro, visual cues, outro.
11. TikTok script -- 15-60 seconds of narration.
12. A one-page executive summary.
"""

# The channels that are actually published from. The long-tail formats may come
# back empty without the package being useless.
REQUIRED = ("linkedin_post", "newsletter", "executive_summary_one_pager")


class MultiPlatformContentAgent(Agent):
    """Generates multi-channel distribution content from articles."""

    name = "social"
    persona = PERSONA
    model_role = ModelRole.CREATIVE
    tool_suite = "social"

    def run(self, request: AgentRequest) -> AgentResult:
        article = request.payload["article"]

        package = ask(
            self.voiced_persona(),
            SOCIAL_PROMPT.format(
                title=article.title,
                executive_summary=article.executive_summary,
                technical_explanation=article.technical_explanation,
                african_perspective=article.african_perspective,
            ),
            SocialEcosystem,
            role=self.model_role,
            agent=self.name,
        )
        if package.usable:
            require(package, *REQUIRED, agent=self.name)

        return AgentResult(
            agent=self.name, output=package,
            abstained=package.abstained, notes=package.notes,
        )

    def generate_social_ecosystem(self, article: EditorialArticle) -> SocialPackage | None:
        """Build the channel package for `article`.

        Returns None when the agent declined. Unlike the earlier stages this is
        not fatal to the article: the piece is already written and reviewable,
        and the package can be regenerated on its own. The orchestrator treats
        it that way.
        """
        logger.info("[social] building the package for '%s'", article.title)

        existing = SocialPackage.objects.filter(article=article).first()
        if existing:
            return existing

        result = self.execute(AgentRequest(payload={"article": article}))
        if result.abstained:
            logger.warning(
                "[social] declined to adapt '%s': %s",
                article.title, result.notes or "no reason given",
            )
            return None

        content = result.output
        package = SocialPackage.objects.create(
            article=article,
            linkedin_post=content.linkedin_post,
            linkedin_article=content.linkedin_article,
            twitter_thread=content.twitter_thread,
            facebook_post=content.facebook_post,
            instagram_carousel=content.instagram_carousel,
            newsletter=content.newsletter,
            medium_article=content.medium_article,
            devto_article=content.devto_article,
            podcast_outline=content.podcast_outline,
            youtube_script=content.youtube_script,
            tiktok_script=content.tiktok_script,
            executive_summary_one_pager=content.executive_summary_one_pager,
        )
        logger.info("[social] package created for '%s'", article.title)
        return package

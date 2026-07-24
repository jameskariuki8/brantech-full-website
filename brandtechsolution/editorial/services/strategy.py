"""
Module 5: Editorial Strategy Agent & Module 16: Personalization Agent

Determines the optimal target audience (developers, enterprise executives, startup founders,
investors, students), tone, complexity, vocabulary, length, and reading difficulty for an article.
Also provides personalized article variant parameters.
"""
import logging
from typing import Dict, Any
from research.models import VerifiedFactReport

logger = logging.getLogger(__name__)


class EditorialStrategyAgent:
    """Selects editorial strategy and target audience persona for content creation."""

    AUDIENCE_PROFILES = {
        'developers': {
            'target_audience': 'developers',
            'tone': 'Technically Precise & Code-Focused',
            'reading_difficulty': 'Advanced',
            'focus_area': 'Architecture, code examples, API performance, developer tooling, GitHub adoption',
            'length_words': 1800
        },
        'business_executives': {
            'target_audience': 'business_executives',
            'tone': 'Strategic & Executive Summary Style',
            'reading_difficulty': 'Intermediate',
            'focus_area': 'ROI, enterprise security, compliance, cost optimization, competitive advantage',
            'length_words': 1400
        },
        'african_founders': {
            'target_audience': 'african_founders',
            'tone': 'Actionable, Entrepreneurial & Regional',
            'reading_difficulty': 'Intermediate',
            'focus_area': 'Local infrastructure, payment integration, market adoption across Kenya, Nigeria, SA, scaling in Africa',
            'length_words': 1600
        },
        'investors': {
            'target_audience': 'investors',
            'tone': 'Analytical & Valuation Focused',
            'reading_difficulty': 'Intermediate',
            'focus_area': 'Market size, TAM/SAM, growth rate, defensibility, moat, venture capital trends',
            'length_words': 1300
        }
    }

    def determine_strategy(self, report: VerifiedFactReport) -> Dict[str, Any]:
        """Determines best audience profile based on trend category and dossier."""
        category = report.dossier.topic.category.lower()
        
        if 'developer' in category or 'software' in category or 'infrastructure' in category:
            profile_key = 'developers'
        elif 'african' in category or 'fintech' in category or 'startup' in category:
            profile_key = 'african_founders'
        elif 'business' in category or 'enterprise' in category or 'cybersecurity' in category:
            profile_key = 'business_executives'
        else:
            profile_key = 'developers'

        strategy = self.AUDIENCE_PROFILES[profile_key].copy()
        logger.info(f"[EditorialStrategyAgent] Strategy selected: {strategy['target_audience']} ({strategy['tone']})")
        return strategy

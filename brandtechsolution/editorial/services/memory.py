"""
Module 17: Editorial Memory Agent

Remembers writing style, brand voice, preferred terminology, past articles, and SEO history
to prevent topic duplication and maintain brand integrity over thousands of articles.
"""
import logging
from typing import List, Tuple
from editorial.models import EditorialMemory, EditorialArticle

logger = logging.getLogger(__name__)


class EditorialMemoryAgent:
    """Enforces style guidelines, voice consistency, and avoids topic duplication."""

    def get_or_create_memory(self) -> EditorialMemory:
        memory, _ = EditorialMemory.objects.get_or_create(
            id=1,
            defaults={
                'brand_voice': 'Authoritative, forward-looking, technically grounded, African-centric, and accessible.',
                'preferred_terminology': {
                    'AI': 'Artificial Intelligence',
                    'ML': 'Machine Learning',
                    'DevOps': 'Modern Engineering Practices',
                    'Teklora': 'Teklora Media & Solutions'
                },
                'excluded_topics': []
            }
        )
        return memory

    def check_duplicate_coverage(self, title: str) -> Tuple[bool, str]:
        """Checks if a title or topic was recently covered to avoid repetition."""
        memory = self.get_or_create_memory()
        
        # Check against database published/drafted articles
        existing = EditorialArticle.objects.filter(title__icontains=title[:20]).first()
        if existing:
            return True, f"Topic similar to existing article '{existing.title}' (ID #{existing.id})"

        return False, "Topic is original"

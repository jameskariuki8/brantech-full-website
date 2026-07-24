"""
Module 13: Knowledge Base Agent

Indexes all articles, research papers, trends, and verified facts into a vector store
with pgvector embeddings. Enables semantic search and cross-referencing for all agents.
"""
import logging
from typing import List, Dict, Any
from django.conf import settings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from pgvector.django import L2Distance, CosineDistance
from brandtechsolution.config import config
from knowledge_base.models import KnowledgeDocument

logger = logging.getLogger(__name__)


class KnowledgeBaseAgent:
    """Manages long-term semantic knowledge memory for Teklora."""

    def __init__(self):
        try:
            self.embeddings = GoogleGenerativeAIEmbeddings(
                model=config.gemini_embedding_model,
                google_api_key=config.google_api_key
            )
        except Exception as e:
            logger.warning(f"KnowledgeBaseAgent embeddings init failed: {e}")
            self.embeddings = None

    def index_document(self, title: str, content: str, doc_type: str = 'article', metadata: Dict[str, Any] = None) -> KnowledgeDocument:
        """Generates embedding vector and stores document in Knowledge Base."""
        metadata = metadata or {}
        embedding_vector = None

        if self.embeddings:
            try:
                # Combine title and text for embedding
                text_to_embed = f"Title: {title}\nType: {doc_type}\nContent: {content[:3000]}"
                embedding_vector = self.embeddings.embed_query(text_to_embed)
            except Exception as e:
                logger.error(f"[KnowledgeBaseAgent] Embedding error for '{title}': {e}")

        doc = KnowledgeDocument.objects.create(
            title=title,
            doc_type=doc_type,
            content=content,
            metadata=metadata,
            embedding=embedding_vector
        )
        logger.info(f"[KnowledgeBaseAgent] Indexed KnowledgeDocument #{doc.id}: '{title}'")
        return doc

    def semantic_search(self, query: str, limit: int = 5) -> List[KnowledgeDocument]:
        """Performs pgvector cosine distance search across Knowledge Base documents."""
        if self.embeddings:
            try:
                query_vector = self.embeddings.embed_query(query)
                # Query with pgvector CosineDistance annotation
                results = KnowledgeDocument.objects.exclude(embedding__isnull=True)\
                    .annotate(distance=CosineDistance('embedding', query_vector))\
                    .order_by('distance')[:limit]
                return list(results)
            except Exception as e:
                logger.error(f"[KnowledgeBaseAgent] Semantic search error: {e}")

        # Fallback substring search
        return list(KnowledgeDocument.objects.filter(content__icontains=query)[:limit])

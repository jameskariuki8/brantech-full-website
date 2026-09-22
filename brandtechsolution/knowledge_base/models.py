from django.db import models
from django.utils import timezone
from pgvector.django import VectorField


class KnowledgeDocument(models.Model):
    """Module 13: Knowledge Base Agent

    Stores vector embeddings and structured text of every article, research paper,
    summary, trend, and source to allow future articles to reuse verified knowledge via RAG.
    """
    DOC_TYPES = [
        ('article', 'Published Article'),
        ('research_dossier', 'Research Dossier'),
        ('trend_summary', 'Trend Summary'),
        ('source_doc', 'External Reference Document'),
    ]

    title = models.CharField(max_length=300)
    doc_type = models.CharField(max_length=30, choices=DOC_TYPES, default='article')
    content = models.TextField()
    metadata = models.JSONField(default=dict, help_text="Source URL, tags, category, author info")
    
    # 3072 dimensions matching Gemini embedding-001 vector space
    embedding = VectorField(dimensions=3072, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_doc_type_display()}] {self.title}"


# ============================================================
# UNIFIED SEMANTIC MEMORY
# ============================================================
# Step 2 of the agent harness. Memory lived in three places that did not know
# about each other: DjangoCheckpointer (chat only), EditorialMemory (a
# singleton row, editorial only), and this app's KnowledgeDocument -- a proper
# pgvector store that was barely used, while the newsroom's duplicate check
# compared the first twenty characters of a title.
#
# Vectors also lived as single columns on BlogPost, Project and
# KnowledgeDocument, which meant a row could hold exactly one vector and
# nothing recorded which model produced it. Two embedding spaces could not
# coexist, so changing the embedding model was unimplementable: every stored
# vector would have been incomparable with every new one, and nothing would
# have raised -- search would simply have got quietly worse.


class EmbeddingSpace(models.Model):
    """One embedding model's vector space.

    Vectors from two models are not comparable; a cosine score between them is
    a number with no meaning. So a space is the unit of comparability, and
    queries never mix them. Changing model creates a new space and backfills
    into it while the old one keeps serving, then cutover is one atomic flip.
    """

    BUILDING = 'building'
    ACTIVE = 'active'
    RETIRED = 'retired'
    STATUS_CHOICES = [
        (BUILDING, 'Building'),
        (ACTIVE, 'Active'),
        (RETIRED, 'Retired'),
    ]

    provider = models.CharField(max_length=40, default='gemini')
    model_id = models.CharField(max_length=120)
    dimensions = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=BUILDING)

    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            # Two active spaces would mean queries silently drawing from both.
            models.UniqueConstraint(
                fields=['status'], condition=models.Q(status='active'),
                name='only_one_active_embedding_space',
            ),
        ]

    def __str__(self):
        return f"{self.provider}/{self.model_id} ({self.dimensions}d, {self.status})"

    @classmethod
    def active(cls):
        return cls.objects.filter(status=cls.ACTIVE).first()


class MemoryDocument(models.Model):
    """One thing worth remembering, independent of how it is embedded.

    Identity and usage statistics live here rather than on the vector, so they
    survive a re-embedding. That is the point: retrieval counts are the input
    to the importance score that decides what gets re-embedded first when the
    model changes, and a count that reset on every migration would be useless
    for exactly the job it exists to do.
    """

    content_type = models.ForeignKey(
        'contenttypes.ContentType', on_delete=models.CASCADE, null=True, blank=True,
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)

    # Which corpus this belongs to. `Memory` took a `scope` argument from the
    # day it was written, stored it, and never used it -- so a caller writing
    # `Memory(scope="editorial")` got a parameter that read as a filter and
    # filtered nothing. This is the column that makes it true.
    scope = models.CharField(max_length=40, default='default', db_index=True)

    kind = models.CharField(max_length=40, default='document', db_index=True)
    title = models.CharField(max_length=300, blank=True, default='')
    text = models.TextField(blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)

    # Skips re-embedding text that has not changed.
    content_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)

    # The strongest importance signal, and the one that did not exist before:
    # how often the agents actually use this. View counts measure human
    # attention; this measures what the system reaches for.
    retrieval_count = models.PositiveIntegerField(default=0, db_index=True)
    last_retrieved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['content_type', 'object_id'],
                condition=models.Q(content_type__isnull=False),
                name='one_memory_document_per_object',
            ),
        ]
        indexes = [models.Index(fields=['kind', '-retrieval_count'])]

    def __str__(self):
        return self.title or f"MemoryDocument #{self.pk}"


class Embedding(models.Model):
    """One document's vector in one space.

    provider / model_id / dimensions are denormalised from the space on
    purpose. A space row can be edited and a model can be renamed or retired,
    but what produced *this* vector cannot change after the fact, so provenance
    has to survive its parent being corrected. It also makes "which model
    served this result?" a query rather than an inference from deployment
    dates, and makes a space holding two model_ids an assertable bug rather
    than silent corruption.
    """

    space = models.ForeignKey(EmbeddingSpace, related_name='embeddings', on_delete=models.CASCADE)
    document = models.ForeignKey(MemoryDocument, related_name='embeddings', on_delete=models.CASCADE)

    provider = models.CharField(max_length=40)
    model_id = models.CharField(max_length=120)
    dimensions = models.PositiveIntegerField()

    # No fixed dimension: pgvector emits a bare `vector` column, which accepts
    # any width, so one table holds both spaces during a migration.
    #
    # The cost of that is an index, and the prediction this comment used to
    # make turned out to be right: Postgres refuses `create index ... using
    # hnsw` on a column whose width it does not know ("column does not have
    # dimensions"), and the answer is a partial index per space over a cast
    # expression, not a schema redesign. See knowledge_base/indexes.py, which
    # builds it, and Memory._vector_column, which carries the matching cast
    # into the query so the index is actually used.
    #
    # One constraint that only shows up in practice: pgvector caps hnsw at
    # 2000 dimensions, and gemini-embedding-001's native width is 3072. That
    # space cannot be indexed at any effort, which is why `manage.py reembed`
    # exists -- a narrower space is a supported Matryoshka truncation of the
    # same model, and it is indexable.
    vector = VectorField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['space', 'document'], name='one_embedding_per_document_per_space',
            ),
        ]
        indexes = [models.Index(fields=['space', 'document'])]

    def __str__(self):
        return f"{self.document} in {self.space}"

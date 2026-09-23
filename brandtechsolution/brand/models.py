from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.templatetags.static import static
from pgvector.django import VectorField


def _truncate_for_embedding(text: str, max_chars: int = 1500) -> str:
    """Truncate text for embedding use.

    - Keeps output <= max_chars characters.
    - Avoids cutting the last word in half when possible.
    """
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    if " " in truncated:
        truncated = truncated.rsplit(" ", 1)[0]
    return truncated + " ..."


class BlogPost(models.Model):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    excerpt = models.TextField(max_length=300)
    content = models.TextField()
    image = models.ImageField(upload_to='blog_images/', blank=True, null=True)
    tags = models.CharField(max_length=200, blank=True, default='', help_text="Comma-separated tags")
    category = models.CharField(max_length=100, default='General')
    featured = models.BooleanField(default=False)
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
    ]
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='draft', db_index=True
    )
    view_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # DEAD COLUMN. Nothing writes this and nothing reads it. Semantic search
    # moved to knowledge_base.Embedding, which records which model produced
    # each vector and so can survive a change of embedding model -- this one
    # holds a single unlabelled vector and cannot. Whatever is in here is
    # whatever `init_vector_stores` left the last time it wrote columns.
    #
    # Kept rather than dropped so migration 0003_backfill_embeddings stays
    # reversible: unapplying it copies the vectors back here. It comes out
    # once that rollback is no longer worth keeping.
    embedding = VectorField(dimensions=3072, null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:200] or "post"  # 200 leaves room for "-N" suffix (field max=220)
            slug = base
            n = 2
            while BlogPost.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("blog_detail", kwargs={"slug": self.slug})

    def get_tags_list(self):
        return [tag.strip() for tag in self.tags.split(',') if tag.strip()]
    
    def get_embedding_text(self) -> str:
        """Return the text to be embedded for this blog post."""
        parts = [
            f"Title: {self.title}",
            f"Category: {self.category}",
            f"Tags: {self.tags}",
        ]
        # Use excerpt first (short summary), then truncated content to limit embedding size
        body = (self.excerpt or "") + "\n\n" + (self.content or "")
        parts.append(_truncate_for_embedding(body, max_chars=1500))
        return "\n".join(parts)


class Project(models.Model):
    title = models.CharField(max_length=200)
    short_description = models.TextField(max_length=500, blank=True, null=True)
    description = models.TextField() # This is the full description
    project_url = models.URLField(blank=True, null=True, help_text="Link to live project or demo")
    github_url = models.URLField(blank=True, null=True, help_text="Link to GitHub repository")
    image = models.ImageField(upload_to='project_images/', blank=True, null=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # DEAD COLUMN. Nothing writes this and nothing reads it. Semantic search
    # moved to knowledge_base.Embedding, which records which model produced
    # each vector and so can survive a change of embedding model -- this one
    # holds a single unlabelled vector and cannot. Whatever is in here is
    # whatever `init_vector_stores` left the last time it wrote columns.
    #
    # Kept rather than dropped so migration 0003_backfill_embeddings stays
    # reversible: unapplying it copies the vectors back here. It comes out
    # once that rollback is no longer worth keeping.
    embedding = VectorField(dimensions=3072, null=True, blank=True)
    
    # GitHub Integration Fields
    github_repo_id = models.IntegerField(blank=True, null=True, help_text="Unique ID from GitHub")
    commit_count = models.IntegerField(blank=True, null=True, default=0, help_text="Total number of commits")
    last_synced_at = models.DateTimeField(blank=True, null=True, help_text="When the repository was last synced")
    is_github_synced = models.BooleanField(default=False, help_text="True if this project was auto-populated from GitHub")
    github_role = models.CharField(max_length=50, blank=True, null=True, help_text="User's role (e.g., owner, collaborator)")
    readme_content = models.TextField(blank=True, null=True, help_text="Raw Markdown README from GitHub")
    cached_commits = models.JSONField(blank=True, null=True, help_text="Last 10 commits cached during sync")

    # ============================================================
    # SHOWCASE FIELDS
    # ============================================================
    # /projects/ renders every row as a compact card. /products/ renders the
    # subset with showcase=True as a full-width article, grouped by phase.
    # They are two views of one table because a "product" and a "project" are
    # the same thing -- the difference is only how deeply we present it.
    #
    # The six products used to be hardcoded in products.html. What made each
    # one feel bespoke was never the markup (five of the six were byte-identical
    # in structure) but about eight values that differed: an accent colour, a
    # badge, a set of section headings and a chart. Those are the fields below,
    # so the theming survives the move and becomes editable instead of being
    # spread across six copies of the same HTML.

    PHASE_COMPLETED = 'completed'
    PHASE_ACTIVE = 'active'
    PHASE_FUTURE = 'future'
    PHASE_CHOICES = [
        (PHASE_COMPLETED, 'Completed & Live'),
        (PHASE_ACTIVE, 'Active Development'),
        (PHASE_FUTURE, 'Future Vision'),
    ]

    # Matches the tab labels on /products/. Kept beside the choices so the
    # filter bar and the group headings cannot drift apart.
    PHASE_TAB_LABELS = {
        PHASE_COMPLETED: '✅ Completed & Live',
        PHASE_ACTIVE: '⚡ Active Development',
        PHASE_FUTURE: '🚀 Future Vision: HoloDesk OS',
    }
    PHASE_GROUP_HEADINGS = {
        PHASE_COMPLETED: 'Phase 1: Completed & Live Deployed Products',
        PHASE_ACTIVE: 'Phase 2: Active In-Development Products',
        PHASE_FUTURE: 'Phase 3: Future Vision & Architecture Specs',
    }
    # Not the card accent: each band has its own dot, and the two unfinished
    # phases animate theirs (a ping for work in flight, a pulse for the
    # roadmap). Kept as (colour, animation class) so the heading markup stays
    # a single loop.
    PHASE_DOTS = {
        PHASE_COMPLETED: ('#00FF94', ''),
        PHASE_ACTIVE: ('#25D366', 'animate-ping'),
        PHASE_FUTURE: ('#38BDF8', 'animate-pulse'),
    }

    VARIANT_DEFAULT = 'default'
    VARIANT_SPOTLIGHT = 'spotlight'
    VARIANT_CHOICES = [
        (VARIANT_DEFAULT, 'Standard card'),
        (VARIANT_SPOTLIGHT, 'Spotlight (gradient, glow, taller gallery)'),
    ]

    slug = models.SlugField(
        max_length=220, blank=True, default='',
        help_text="Anchor id on /products/ (e.g. 'edushare'), so deep links keep working.",
    )
    showcase = models.BooleanField(
        default=False, help_text="Show this project as a full article on /products/.",
    )
    phase = models.CharField(
        max_length=20, choices=PHASE_CHOICES, default=PHASE_COMPLETED,
        help_text="Which /products/ group this appears under.",
    )
    display_order = models.PositiveSmallIntegerField(
        default=0, help_text="Position within its phase. Lower sorts first.",
    )

    # Two shades, not one: the original cards used a lighter colour for text
    # and a deeper one for the 10%-opacity fill and the 20% border
    # (text-purple-400 over bg-purple-500/10). Collapsing them to a single
    # value would visibly flatten the badges.
    accent = models.CharField(
        max_length=7, default='#00FF94', help_text="Hex accent for text and icons.",
    )
    accent_deep = models.CharField(
        max_length=7, blank=True, default='',
        help_text="Hex for badge fills and borders. Defaults to the accent.",
    )

    badge_icon = models.CharField(
        max_length=60, blank=True, default='fas fa-check-circle',
        help_text="Full Font Awesome classes, e.g. 'fab fa-whatsapp'.",
    )
    badge_label = models.CharField(max_length=120, blank=True, default='')

    cta_label = models.CharField(
        max_length=80, blank=True, default='',
        help_text="Button text. Blank hides the button; the link is project_url.",
    )
    cta_icon = models.CharField(
        max_length=60, blank=True, default='fas fa-external-link-alt',
    )

    gallery_heading = models.CharField(max_length=120, blank=True, default='Interface Gallery')
    features_heading = models.CharField(max_length=120, blank=True, default='Core Capabilities & Modules')
    chart_heading = models.CharField(max_length=160, blank=True, default='')
    chart_icon = models.CharField(max_length=60, blank=True, default='fas fa-chart-bar')

    # Chart.js consumes this shape directly: {"type": ..., "data": ..., "options": ...}.
    # JSON rather than columns because a doughnut, a grouped bar and a radar
    # have genuinely different payloads, and Chart.js is the schema.
    chart_spec = models.JSONField(
        blank=True, null=True, help_text="Chart.js config: {type, data, options}.",
    )

    card_variant = models.CharField(max_length=20, choices=VARIANT_CHOICES, default=VARIANT_DEFAULT)

    # Escape hatch for the handful of one-off deviations in the original
    # markup that are not worth a column each -- chip_text, cta_icon_first,
    # cta_extra_classes, chart_heading_accent. Five of the six products carry
    # an empty dict. See products.html for how each key is read.
    style_overrides = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
    
    def get_embedding_text(self) -> str:
        """Return the text to be embedded for this project."""
        parts = [
            f"Project: {self.title}",
            f"Technologies: {self.short_description or ''}",
        ]
        parts.append(_truncate_for_embedding(self.description or "", max_chars=1500))
        return "\n".join(parts)

    def save(self, *args, **kwargs):
        if not self.slug and self.title:
            self.slug = slugify(self.title)[:220]
        super().save(*args, **kwargs)

    @property
    def fill(self) -> str:
        """The deeper shade, falling back to the accent when unset."""
        return self.accent_deep or self.accent

    @property
    def is_spotlight(self) -> bool:
        return self.card_variant == self.VARIANT_SPOTLIGHT

    @property
    def glow(self) -> str:
        """The accent as bare "r,g,b", for the spotlight card's outer glow.

        Tailwind arbitrary values cannot contain spaces, hence no separators.
        The original markup hardcoded rgba(56,189,248,.1), which is exactly
        HoloDesk's accent -- deriving it means a spotlight card in any other
        colour glows in that colour instead of staying blue.
        """
        value = (self.accent or '').lstrip('#')
        if len(value) == 3:
            value = ''.join(c * 2 for c in value)
        if len(value) != 6:
            return '56,189,248'
        try:
            return ','.join(str(int(value[i:i + 2], 16)) for i in (0, 2, 4))
        except ValueError:
            return '56,189,248'

    def style(self, key, default=None):
        """Read one style override, tolerating a null or non-dict column."""
        overrides = self.style_overrides
        if not isinstance(overrides, dict):
            return default
        return overrides.get(key, default)

    # The three feature styles render into three different containers, so the
    # template needs them split. These read the prefetched list rather than
    # filtering the manager, which would fire a query per card and undo the
    # prefetch in the products view.
    @property
    def card_features(self):
        return [f for f in self.features.all() if f.style == ProjectFeature.STYLE_CARD]

    @property
    def chip_features(self):
        return [f for f in self.features.all() if f.style == ProjectFeature.STYLE_CHIP]

    @property
    def check_features(self):
        return [f for f in self.features.all() if f.style == ProjectFeature.STYLE_CHECK]


class ProjectImage(models.Model):
    """One gallery tile on a showcase card.

    Either an uploaded file or a remote URL -- the original cards mixed both,
    using local static art for the deployed products and Unsplash stand-ins
    for the two that have no screenshots yet.

    The thumbnail and the lightbox deliberately get separate URLs: the
    hardcoded markup requested a smaller Unsplash render for the tile
    (w=800) and a larger one for the expanded view (w=1200).
    """

    project = models.ForeignKey(Project, related_name='gallery', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='project_gallery/', blank=True, null=True)
    # The art that shipped with the hardcoded cards lives in static, not media,
    # and is served by WhiteNoise with its own cache headers. Storing the
    # static path keeps those files exactly as they are served today; anything
    # uploaded from the panel lands in `image` instead.
    static_path = models.CharField(
        max_length=300, blank=True, default='',
        help_text="Path under static/, e.g. 'brand/images/edushare.png'.",
    )
    remote_url = models.URLField(blank=True, default='', max_length=500)
    full_url = models.URLField(
        blank=True, default='', max_length=500,
        help_text="Larger render for the lightbox. Defaults to the tile image.",
    )
    alt = models.CharField(max_length=200, blank=True, default='')
    caption = models.CharField(
        max_length=200, blank=True, default='',
        help_text="Shown on hover, after 'Expand Mockup N:'.",
    )
    lightbox_title = models.CharField(max_length=200, blank=True, default='')
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.project.title} image #{self.order}"

    @property
    def src(self) -> str:
        """Resolved tile URL. An upload wins, then bundled art, then remote."""
        if self.image:
            return self.image.url
        if self.static_path:
            return static(self.static_path)
        return self.remote_url

    @property
    def expanded_src(self) -> str:
        return self.full_url or self.src


class ProjectFeature(models.Model):
    """A bullet, chip or check line in a showcase card's left column.

    Three styles because the original markup had three: five products used
    boxed rows with an icon and a bolded label, and HoloDesk used a row of
    technology chips above a plain checklist.
    """

    STYLE_CARD = 'card'
    STYLE_CHIP = 'chip'
    STYLE_CHECK = 'check'
    STYLE_CHOICES = [
        (STYLE_CARD, 'Boxed row with icon and bold label'),
        (STYLE_CHIP, 'Compact chip'),
        (STYLE_CHECK, 'Plain check line'),
    ]

    project = models.ForeignKey(Project, related_name='features', on_delete=models.CASCADE)
    style = models.CharField(max_length=10, choices=STYLE_CHOICES, default=STYLE_CARD)
    icon = models.CharField(max_length=60, blank=True, default='')
    label = models.CharField(
        max_length=120, blank=True, default='', help_text="Bolded lead-in, card style only.",
    )
    text = models.TextField(blank=True, default='')
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.project.title}: {self.label or self.text[:40]}"


class ProjectNote(models.Model):
    """An optional titled panel above the gallery.

    Only HoloDesk uses these today -- its Problem / Solution pair. The other
    five products have none, which is why this is a separate table rather
    than two more nullable columns on Project.
    """

    project = models.ForeignKey(Project, related_name='notes', on_delete=models.CASCADE)
    heading = models.CharField(max_length=120)
    body = models.TextField(blank=True, default='')
    icon = models.CharField(max_length=60, blank=True, default='')
    color = models.CharField(
        max_length=20, blank=True, default='',
        help_text="Hex for the heading, e.g. '#F87171'. Blank uses the accent.",
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.project.title}: {self.heading}"

class Event(models.Model):
    EVENT_TYPES = [
        ('webinar', 'Webinar'),
        ('workshop', 'Workshop'),
        ('conference', 'Conference'),
        ('meetup', 'Meetup'),
        ('launch', 'Product Launch'),
    ]
    
    title = models.CharField(max_length=200)
    description = models.TextField()
    event_type = models.CharField(max_length=20, choices=EVENT_TYPES)
    date = models.DateTimeField()
    location = models.CharField(max_length=200, blank=True, null=True)
    is_online = models.BooleanField(default=False)
    registration_link = models.URLField(blank=True, null=True)
    max_attendees = models.PositiveIntegerField(blank=True, null=True)
    image = models.ImageField(upload_to='event_images/', blank=True, null=True)
    featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']

    def __str__(self):
        return f"{self.title} - {self.date.strftime('%Y-%m-%d')}"


class BlogLike(models.Model):
    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name='likes')
    browser_id = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'browser_id')


class BlogComment(models.Model):
    post = models.ForeignKey(BlogPost, on_delete=models.CASCADE, related_name='comments')
    browser_id = models.CharField(max_length=255)
    user_name = models.CharField(max_length=100, default='Anonymous')
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_approved = models.BooleanField(default=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Comment by {self.user_name} on {self.post.title}"


from django.core.cache import cache
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.templatetags.static import static
from pgvector.django import VectorField

SITE_CONTENT_CACHE_KEY = "brand:site-content"


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


def default_header_links():
    return [
        {"label": "Home", "url": "/"},
        {
            "label": "Products",
            "url": "/products/",
            "children": [
                {"label": "EduShare Africa", "url": "/products/#edushare"},
                {"label": "DOMMaterdei SMS", "url": "/products/#dommaterdei"},
                {"label": "Poise & Purpose", "url": "/products/#poise"},
                {"label": "Kiamiko WhatsApp Commerce", "url": "/products/#kiamiko"},
                {"label": "Campus Fast-Food Delivery", "url": "/products/#campus-food"},
                {"label": "HoloDesk Workspace OS", "url": "/products/#holodesk"},
            ],
        },
        {
            "label": "Solutions",
            "url": "/solutions/",
            "children": [
                {"label": "Education", "url": "/solutions/#education"},
                {"label": "Healthcare", "url": "/solutions/#healthcare"},
                {"label": "Agriculture", "url": "/solutions/#agriculture"},
                {"label": "Business & Corporate", "url": "/solutions/#business"},
                {"label": "Government", "url": "/solutions/#government"},
            ],
        },
        {
            "label": "Research",
            "url": "/research/",
            "children": [
                {"label": "Artificial Intelligence", "url": "/research/#ai"},
                {"label": "Digital Twins", "url": "/research/#digital-twins"},
                {"label": "Spatial Computing", "url": "/research/#spatial"},
                {"label": "Python & React Stack", "url": "/research/#tech-stack"},
                {"label": "Quantum Computing", "url": "/research/#quantum"},
                {"label": "Future of Tech", "url": "/research/#future-tech"},
            ],
        },
        {
            "label": "About",
            "url": "/about/",
            "children": [
                {"label": "Mission & Values", "url": "/about/#mission"},
                {"label": "Partnerships", "url": "/about/#partnerships"},
                {"label": "Volunteer & Learn", "url": "/about/#careers"},
            ],
        },
        {"label": "Blog", "url": "/blog/"},
        {"label": "Contact", "url": "/contacts/"},
    ]


def default_footer_quick_links():
    return [
        {"label": "Home", "url": "/"},
        {"label": "About Us", "url": "/about/"},
        {"label": "Products", "url": "/products/"},
        {"label": "Services", "url": "/solutions/"},
        {"label": "Research", "url": "/research/"},
        {"label": "Blog", "url": "/blog/"},
        {"label": "Contact", "url": "/contacts/"},
        {"label": "Terms & Conditions", "url": "/terms/"},
        {"label": "Privacy Policy", "url": "/privacy/"},
    ]


def default_footer_services():
    return [
        {"label": "Web Design & System Development", "url": "/solutions/#business"},
        {"label": "Mobile Application Development", "url": "/products/#edushare"},
        {"label": "Digital Strategy", "url": "/solutions/"},
        {"label": "Cloud Computing", "url": "/solutions/"},
    ]


def default_footer_legal_links():
    return [
        {"label": "Privacy Policy", "url": "/privacy/"},
        {"label": "Terms & Conditions", "url": "/terms/"},
    ]


def default_footer_social_links():
    return [
        {"label": "LinkedIn", "url": "https://www.linkedin.com/company/brantech-solutions-ke/", "icon": "fab fa-linkedin"},
        {"label": "Facebook", "url": "https://www.facebook.com/", "icon": "fab fa-facebook"},
        {"label": "TikTok", "url": "https://www.tiktok.com/", "icon": "fab fa-tiktok"},
        {"label": "Instagram", "url": "https://www.instagram.com/brantech_solutions", "icon": "fab fa-instagram"},
    ]


def default_story_tabs():
    return [
        {
            "label": "Purpose Before Profit",
            "title": "Technology Built for Lasting Impact",
            "desc": "Teklora exists because off-the-shelf software doesn't fit the realities of African infrastructure, low-bandwidth environments, and rapid enterprise growth. We prioritize deep, enduring impact over quick turnarounds, engineering custom platforms that empower African institutions to lead.",
            "quote": "\"Every application we engineer must deliver tangible, measurable value to African communities and enterprises.\"",
            "author": "Teklora Philosophy",
            "badgeText": "OUR CORE",
            "image": "/static/brand/images/story_purpose_impact.png",
        },
        {
            "label": "African-First Innovation",
            "title": "Tailored for African Infrastructure",
            "desc": "We design systems from the ground up to thrive in low-bandwidth, high-concurrency, and mobile-first African environments. Our zero-rated edge caching and offline-first architectures guarantee 99.98% reliability anywhere.",
            "quote": "\"Resilient infrastructure engineered to perform under extreme regional and bandwidth constraints.\"",
            "author": "Technical Architecture Core",
            "badgeText": "INFRASTRUCTURE",
            "image": "/static/brand/images/story_african_innovation.png",
        },
        {
            "label": "Human-Centered Tech",
            "title": "Apple-Grade UI with Technical Rigor",
            "desc": "Great technology must be intuitive. We merge modern design aesthetics—dark mode elegance, crisp typography, micro-interactions—with deep Python and React engineering to make complex institutional software effortless to use.",
            "quote": "\"Craftsmanship means making high-powered software feel clean, fast, and human-centered.\"",
            "author": "UI/UX Design Principle",
            "badgeText": "CRAFTSMANSHIP",
            "image": "/static/brand/images/story_human_centered_ui.png",
        },
        {
            "label": "Enduring Legacy",
            "title": "Long-Term Support & Continental Scale",
            "desc": "We are not chasing short-lived tech trends. We forge long-term partnerships with universities, NGOs, government agencies, and enterprises to continuously audit, scale, and maintain mission-critical software for decades.",
            "quote": "\"Building technology today that powers Africa's leaders tomorrow.\"",
            "author": "Pan-African Mission",
            "badgeText": "CONTINENTAL LEGACY",
            "image": "/static/brand/images/story_enduring_legacy.png",
        },
    ]


def default_flagship_stats():
    return [
        {"value": "1,000+", "label": "Active Learners"},
        {"value": "74%", "label": "Query Latency Drop"},
        {"value": "99.98%", "label": "System Uptime"},
        {"value": "Zero", "label": "Offline Data Loss"},
    ]


def default_flagship_technologies():
    return [
        {"label": "React", "icon": "fab fa-react"},
        {"label": "Python", "icon": "fab fa-python"},
        {"label": "Django Core", "icon": "fas fa-server"},
        {"label": "PostgreSQL", "icon": "fas fa-database"},
        {"label": "Cloudflare Edge", "icon": "fas fa-bolt"},
    ]


def default_capability_cards():
    return [
        {
            "image": "/static/brand/images/cap_software_dev.png",
            "badge": "BACKEND & APIS",
            "icon": "fas fa-code",
            "title": "Software Development",
            "description": "Custom Python, Django, and React backbones engineered for maximum maintainability, security, and high user concurrency across enterprise systems.",
            "technologies": [
                {"label": "Python", "icon": "fab fa-python"},
                {"label": "Django Core", "icon": "fas fa-server"},
                {"label": "React.js", "icon": "fab fa-react"},
            ],
        },
        {
            "image": "/static/brand/images/cap_ai_solutions.png",
            "badge": "AUTONOMOUS MESH",
            "icon": "fas fa-brain",
            "title": "AI Solutions & Agentic Mesh",
            "description": "Multi-agent network orchestration, pgvector similarity search, and automated research compilation engines that accelerate operations 10x.",
            "technologies": [
                {"label": "Gemini 3.6", "icon": "fas fa-robot"},
                {"label": "pgvector", "icon": "fas fa-database"},
                {"label": "LangGraph", "icon": "fas fa-project-diagram"},
            ],
        },
        {
            "image": "/static/brand/images/cap_cloud_edge.png",
            "badge": "EDGE ARCHITECTURE",
            "icon": "fas fa-cloud",
            "title": "Cloud Applications & Edge",
            "description": "Micro-kernel edge caching structures and high-availability cloud infrastructure running across AWS & DigitalOcean backbones with 99.98% uptime.",
            "technologies": [
                {"label": "Docker", "icon": "fab fa-docker"},
                {"label": "AWS", "icon": "fab fa-aws"},
                {"label": "Nginx", "icon": "fas fa-network-wired"},
            ],
        },
        {
            "image": "/static/brand/images/cap_web_mobile.png",
            "badge": "LUXURY DESIGN",
            "icon": "fas fa-desktop",
            "title": "Web & Mobile Ecosystems",
            "description": "Awwwards-grade web platforms and cross-platform native mobile applications designed with Apple and Stripe design language, smooth animations, and top speed.",
            "technologies": [
                {"label": "React Native", "icon": "fab fa-react"},
                {"label": "TypeScript", "icon": "fab fa-js"},
                {"label": "Tailwind CSS", "icon": "fab fa-css3-alt"},
            ],
        },
        {
            "image": "/static/brand/images/cap_digital_trans.png",
            "badge": "ENTERPRISE MODERNIZATION",
            "icon": "fas fa-sync-alt",
            "title": "Digital Transformation",
            "description": "Modernizing manual institutional workflows for universities, NGOs, state entities, and high-growth African enterprises.",
            "technologies": [
                {"label": "Institutional SaaS", "icon": "fas fa-building"},
                {"label": "Security Audits", "icon": "fas fa-shield-alt"},
            ],
        },
    ]


def default_technology_orbit():
    return [
        {"label": "Python", "icon": "fab fa-python"},
        {"label": "React", "icon": "fab fa-react"},
        {"label": "Django", "icon": "fas fa-server"},
        {"label": "PostgreSQL", "icon": "fas fa-database"},
        {"label": "FastAPI", "icon": "fas fa-bolt"},
        {"label": "TypeScript", "icon": "fab fa-js"},
        {"label": "Docker", "icon": "fab fa-docker"},
        {"label": "Linux OS", "icon": "fab fa-linux"},
        {"label": "Nginx", "icon": "fas fa-network-wired"},
        {"label": "Git & GitHub", "icon": "fab fa-git-alt"},
    ]


def default_technology_groups():
    return [
        {"label": "Backend", "icon": "fab fa-python", "items": ["Python 3.13", "Django Core", "FastAPI", "Flask"]},
        {"label": "Frontend", "icon": "fab fa-react", "items": ["React.js", "TypeScript", "JavaScript (ES6+)", "Tailwind CSS"]},
        {"label": "Databases", "icon": "fas fa-database", "items": ["PostgreSQL", "pgvector (AI)", "MySQL", "SQLite"]},
        {"label": "DevOps", "icon": "fab fa-docker", "items": ["Docker Containers", "Git / GitHub", "Linux Kernels", "Nginx Server"]},
        {"label": "Platforms", "icon": "fas fa-cloud-upload-alt", "items": ["Render Cloud", "DigitalOcean", "Vercel Platform", "AWS Infra"]},
    ]


def default_why_cards():
    return [
        {
            "image": "/static/brand/images/story_purpose_impact.png",
            "alt": "Product-Led Engineering",
            "badge": "PRODUCT COMPANY",
            "title": "Product-Led Engineering",
            "description": "We build and operate enduring technology platforms like EduShare Africa with 99.98% reliability.",
        },
        {
            "image": "/static/brand/images/story_african_innovation.png",
            "alt": "African-First Infrastructure",
            "badge": "PAN-AFRICAN SCALE",
            "title": "African-First Infrastructure",
            "description": "Engineered specifically for zero-rated edge caching and low-bandwidth regional network conditions.",
        },
        {
            "image": "/static/brand/images/story_human_centered_ui.png",
            "alt": "Apple & Stripe Craftsmanship",
            "badge": "ZERO DEV BLOAT",
            "title": "Apple & Stripe Craftsmanship",
            "description": "Hand-crafted Python, React, and PostgreSQL backbones built with sub-100ms response times.",
        },
        {
            "image": "/static/brand/images/story_enduring_legacy.png",
            "alt": "24/7 Strategic Partnership",
            "badge": "LONG-TERM PARTNER",
            "title": "24/7 Strategic Partnership",
            "description": "Continuous active infrastructure monitoring, security patch management, and long-term feature growth.",
        },
    ]


def default_journey_steps():
    return [
        {
            "label": "01. Discovery & Audit",
            "tagline": "STAGE 01 • INITIATION",
            "title": "Discovery & Architecture Audit",
            "summary": "We analyze institutional stakeholders, data flow parameters, legacy codebase vulnerabilities, and African network bandwidth constraints before designing your software architecture.",
            "deliverables": ["Workflow Audits", "Data Flow Mapping", "Bandwidth Specs"],
            "color": "#00FF94",
            "image": "/static/brand/images/cap_digital_trans.png",
        },
        {
            "label": "02. System Strategy",
            "tagline": "STAGE 02 • STRATEGY",
            "title": "System Strategy & Schema Design",
            "summary": "Architecting relational database schemas, RESTful & GraphQL API contracts, and zero-rated edge caching routes tailored for your exact operational requirements.",
            "deliverables": ["Database Schemas", "API Contracts", "Cloud Blueprints"],
            "color": "#007AFF",
            "image": "/static/brand/images/cap_software_dev.png",
        },
        {
            "label": "03. UI/UX Design",
            "tagline": "STAGE 03 • DESIGN",
            "title": "Human-Centered UI/UX Design",
            "summary": "Crafting modern Apple and Stripe-grade user interfaces with dark-mode elegance, micro-interaction fluidity, and intuitive navigation for enterprise software.",
            "deliverables": ["Figma Prototypes", "Design System Tokens", "Micro-Animations"],
            "color": "#A855F7",
            "image": "/static/brand/images/story_human_centered_ui.png",
        },
        {
            "label": "04. Production Build",
            "tagline": "STAGE 04 • ENGINEERING",
            "title": "Python, React & PostgreSQL Build",
            "summary": "Writing clean, maintainable Python and Django backend services alongside high-performance React component trees capable of sub-100ms response times.",
            "deliverables": ["Django Core", "React UI Components", "pgvector Search"],
            "color": "#F59E0B",
            "image": "/static/brand/images/hero.png",
        },
        {
            "label": "05. Security & QA Audit",
            "tagline": "STAGE 05 • VALIDATION",
            "title": "Security & Automated QA Audits",
            "summary": "Rigorous automated unit testing, SQL injection vulnerabilities scanning, CSRF protection validation, and simulated low-bandwidth network stress tests.",
            "deliverables": ["Automated Unit Tests", "Penetration Scans", "Load Testing Reports"],
            "color": "#F43F5E",
            "image": "/static/brand/images/cap_ai_solutions.png",
        },
        {
            "label": "06. Cloud Deployment",
            "tagline": "STAGE 06 • DEPLOYMENT",
            "title": "Zero-Downtime Cloud Deployment",
            "summary": "Containerizing services with Docker and deploying to AWS & DigitalOcean backbones with Nginx edge routing and SSL firewall security.",
            "deliverables": ["Docker Containers", "Nginx Caching", "Zero-Downtime Migration"],
            "color": "#06B6D4",
            "image": "/static/brand/images/cap_cloud_edge.png",
        },
        {
            "label": "07. 24/7 Legacy Support",
            "tagline": "STAGE 07 • STEWARDSHIP",
            "title": "24/7 Continuous Legacy Support",
            "summary": "Providing continuous 24/7 infrastructure uptime monitoring, security patch management, automated backups, and long-term feature expansion for decades.",
            "deliverables": ["24/7 Monitoring Alerting", "Continuous Backups", "Quarterly Audits"],
            "color": "#10B981",
            "image": "/static/brand/images/story_enduring_legacy.png",
        },
    ]


def default_impact_stats():
    return [
        {"key": "metricProjects", "value": 5, "label": "Projects Delivered"},
        {"key": "metricClients", "value": 13, "label": "Satisfied Clients"},
        {"key": "metricTech", "value": 18, "label": "Tech Mastered"},
        {"key": "metricSatisfaction", "value": 99, "label": "Satisfaction %"},
    ]


class SiteContent(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    brand_name = models.CharField(max_length=100, default="Teklora")
    logo_url = models.CharField(max_length=500, default="/static/brand/images/logo.png")
    header_links = models.JSONField(default=default_header_links)
    header_cta_label = models.CharField(max_length=100, default="Book Strategy Consultation")
    header_cta_url = models.CharField(max_length=500, default="/contacts/#book")

    footer_description = models.TextField(
        default="Innovative technology solutions for modern businesses."
    )
    footer_quick_heading = models.CharField(max_length=100, default="Quick Links")
    footer_services_heading = models.CharField(max_length=100, default="Services")
    footer_contact_heading = models.CharField(max_length=100, default="Contact")
    footer_quick_links = models.JSONField(default=default_footer_quick_links)
    footer_services = models.JSONField(default=default_footer_services)
    footer_legal_links = models.JSONField(default=default_footer_legal_links)
    footer_social_links = models.JSONField(default=default_footer_social_links)
    contact_email = models.EmailField(default="teklorasolutionsltd@gmail.com")
    contact_phone = models.CharField(max_length=50, default="+254 704 894220")
    copyright_text = models.CharField(
        max_length=200, default="© 2026 Teklora Solutions. All rights reserved."
    )

    landing_title = models.CharField(
        max_length=200,
        default="Teklora - Building Technology That Leaves a Lasting Legacy Across Africa",
    )
    landing_meta_description = models.TextField(
        default="Teklora is a Kenyan technology company engineering custom software, cloud engines, and AI platforms built to transform businesses, universities, NGOs, and institutions across Africa."
    )

    hero_title_before = models.CharField(
        max_length=180, default="Building Technology That Leaves a "
    )
    hero_title_highlight = models.CharField(max_length=120, default="Lasting Legacy")
    hero_title_after = models.CharField(max_length=120, default=" Across Africa")
    hero_description = models.TextField(
        default="We don't just build websites. We engineer scalable software products, cloud platforms, and intelligent systems that solve real African challenges and empower institutions to lead."
    )
    hero_quote = models.CharField(
        max_length=300,
        default="Building technology that leaves a lasting legacy across Africa.",
    )
    hero_primary_label = models.CharField(max_length=100, default="Book an Appointment")
    hero_primary_url = models.CharField(max_length=500, default="/contacts/#book")
    hero_secondary_label = models.CharField(
        max_length=100, default="Explore EduShare Flagship"
    )
    hero_secondary_url = models.CharField(
        max_length=500, default="#flagship-edushare"
    )
    hero_image_url = models.CharField(
        max_length=500, default="/static/brand/images/HEROO.png"
    )
    hero_scroll_label = models.CharField(max_length=100, default="Discover Our Vision")

    story_label = models.CharField(max_length=100, default="Our Story & Purpose")
    story_heading = models.CharField(
        max_length=250, default="Africa Deserves Technology Built for African Challenges"
    )
    story_tabs = models.JSONField(default=default_story_tabs)

    flagship_label = models.CharField(
        max_length=120, default="Flagship Innovation Spotlight"
    )
    flagship_title = models.CharField(max_length=160, default="EduShare Africa")
    flagship_description = models.TextField(
        default="Proof of Teklora's capability to build scalable, high-impact technology products that transform African education."
    )
    flagship_image_url = models.CharField(
        max_length=500, default="/static/brand/images/edushare.png"
    )
    flagship_badge = models.CharField(max_length=120, default="ZERO-RATED SYLLABUS CDN")
    flagship_subtitle = models.CharField(max_length=180, default="EdTech SaaS Engine")
    flagship_feature_heading = models.CharField(
        max_length=250, default="Decentralized Syllabus Access for African Students"
    )
    flagship_problem_label = models.CharField(max_length=100, default="The Problem:")
    flagship_problem_description = models.TextField(
        default="Students in African universities face prohibitive data costs and slow server connections, causing syllabus access bottlenecks during exam study cycles."
    )
    flagship_solution_label = models.CharField(
        max_length=120, default="The Solution & Impact:"
    )
    flagship_solution_description = models.TextField(
        default="EduShare compresses and caches university study materials, reducing latency by 74% and serving over 50,000 active learners with zero offline interruptions."
    )
    flagship_technology_heading = models.CharField(
        max_length=160, default="Technologies Powering EduShare:"
    )
    flagship_cta_label = models.CharField(max_length=120, default="Explore EduShare Africa")
    flagship_cta_url = models.CharField(max_length=500, default="/products/#edushare")
    flagship_technologies = models.JSONField(default=default_flagship_technologies)
    flagship_stats = models.JSONField(default=default_flagship_stats)
    capabilities_label = models.CharField(
        max_length=120, default="Technical Capabilities"
    )
    capabilities_heading = models.CharField(
        max_length=250, default="Services Delivered as Scalable Solutions"
    )
    capabilities_description = models.TextField(
        default="Explore our specialized technology solutions engineered for maximum performance, security, and continental scale."
    )
    capability_cards = models.JSONField(default=default_capability_cards)

    technology_label = models.CharField(max_length=120, default="Core Tech Stack")
    technology_heading = models.CharField(
        max_length=200, default="Technology We Build With"
    )
    technology_description = models.TextField(
        default="We rely on a battle-tested Python and React stack engineered for security, speed, and massive scale."
    )
    technology_center_caption = models.CharField(
        max_length=120, default="PYTHON & REACT CENTERED"
    )
    technology_orbit = models.JSONField(default=default_technology_orbit)
    technology_groups = models.JSONField(default=default_technology_groups)

    why_label = models.CharField(max_length=100, default="Why Teklora")
    why_heading = models.CharField(
        max_length=300,
        default="We engineer long-term, scalable technology products built for continental impact, not short-term dev hand-offs.",
    )
    why_cards = models.JSONField(default=default_why_cards)

    journey_label = models.CharField(max_length=100, default="Execution Method")
    journey_heading = models.CharField(max_length=200, default="Our Engineering Journey")
    journey_description = models.CharField(
        max_length=300,
        default="Hover over any stage below to explore our structured execution framework.",
    )
    journey_transparency_label = models.CharField(
        max_length=100, default="100% TRANSPARENT"
    )
    journey_steps = models.JSONField(default=default_journey_steps)

    impact_label = models.CharField(max_length=100, default="Impact in Numbers")
    impact_heading = models.CharField(
        max_length=200, default="Our Track Record Across Africa"
    )
    impact_stats = models.JSONField(default=default_impact_stats)

    class Meta:
        verbose_name = "site content"
        verbose_name_plural = "site content"

    def __str__(self):
        return f"Site content — {self.brand_name}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete(SITE_CONTENT_CACHE_KEY)


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
        PHASE_COMPLETED: 'Completed & Live',
        PHASE_ACTIVE: 'Active Development',
        PHASE_FUTURE: 'Future Vision: HoloDesk OS',
    }
    PHASE_ICONS = {
        PHASE_COMPLETED: 'fas fa-check-circle text-emerald-500',
        PHASE_ACTIVE: 'fas fa-bolt text-amber-500',
        PHASE_FUTURE: 'fas fa-rocket text-sky-400',
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

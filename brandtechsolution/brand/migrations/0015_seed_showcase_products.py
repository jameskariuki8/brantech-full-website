"""Move the six hardcoded products out of products.html and into the database.

The page used to carry its own content: six <article> blocks written directly
into the template, each with its own accent colour, badge, gallery, feature
list and Chart.js config. This migration recreates them as Project rows so the
same page can be rendered from a loop and the content edited from the panel.

Written to be reversible and re-runnable: it keys on slug, so a redeploy will
not create a second copy, and unapplying it removes only the rows it created.

Two colour notes. The original markup mixed Tailwind's named shades with
arbitrary hex, and used a *lighter* shade for text than for the badge fill
(text-purple-400 over bg-purple-500/10). The named shades are substituted with
their exact hex here so a single code path renders all six:

    purple-400 #C084FC   purple-500 #A855F7
    amber-400  #FBBF24   amber-500  #F59E0B
    sky-300    #7DD3FC   sky-400    #38BDF8   sky-500 #0EA5E9
"""
from django.db import migrations


PRODUCTS = [
    {
        "slug": "edushare",
        "title": "EduShare Africa — EdTech Marketplace & Progress Infrastructure",
        "short_description": (
            "An all-in-one digital learning platform enabling teachers to monetize notes and "
            "revision materials directly to students, parents to track academic performance in "
            "real time, and schools to deploy AI-assisted learning."
        ),
        "project_url": "https://edushareafrica.com/",
        "phase": "completed",
        "display_order": 1,
        "accent": "#00FF94",
        "badge_icon": "fas fa-check-circle",
        "badge_label": "Deployed SaaS Platform",
        "cta_label": "Visit Platform",
        "features_heading": "Core Capabilities & Modules",
        "chart_heading": "Data Story: Material Distribution & Sales Volume",
        "chart_icon": "fas fa-chart-pie",
        "chart_spec": {
            "type": "doughnut",
            "data": {
                "labels": ["Notes & Revision Kits", "Practice Exams", "AI Micro-Lessons", "School Portals"],
                "datasets": [{
                    "data": [45, 30, 15, 10],
                    "backgroundColor": ["#00FF94", "#007AFF", "#A855F7", "#38BDF8"],
                    "borderWidth": 0,
                }],
            },
            "options": {
                "responsive": True,
                "plugins": {"legend": {"position": "right", "labels": {"boxWidth": 10, "font": {"size": 9}}}},
            },
        },
        "gallery": [
            {
                "static_path": "brand/images/edushare.png",
                "alt": "EduShare Marketplace",
                "caption": "Expand Mockup 1: Educator Marketplace",
                "lightbox_title": "EduShare Africa - Educator Resource Marketplace",
            },
            {
                "static_path": "brand/images/edushare2.png",
                "alt": "EduShare AI Learning",
                "caption": "Expand Mockup 2: AI Learning & Parent Portal",
                "lightbox_title": "EduShare Africa - AI Learning & Parent Progress Analytics",
            },
        ],
        "features": [
            ("fas fa-book-reader", "Teacher Resource Sales",
             "Educators upload and monetize revision notes, past papers, and video guides directly."),
            ("fas fa-chart-line", "Parent Progress Monitoring",
             "Real-time academic scores, assignment completion, and attendance dashboards."),
            ("fas fa-robot", "AI Learning Assistant & Ranking",
             "Onboarded schools gain personalized AI tutoring and automated top-performing teacher leaderboards."),
        ],
    },
    {
        "slug": "dommaterdei",
        "title": "DOMMaterdei School Management System (SMS)",
        "short_description": (
            "Built for DOMMaterdei School in Tharaka Nithi County. A robust operating system "
            "featuring automated report card generation, inventory tracking, fee payments, and "
            "dedicated director/teacher/student portals."
        ),
        "project_url": "https://dommaterdeischool.academy/",
        "phase": "completed",
        "display_order": 2,
        "accent": "#007AFF",
        "badge_icon": "fas fa-school",
        "badge_label": "Deployed School SMS",
        "cta_label": "Visit School Academy",
        "features_heading": "System Modules & Features",
        "chart_heading": "Data Story: Result Generation Speed (Manual vs SMS)",
        "chart_icon": "fas fa-chart-bar",
        "chart_spec": {
            "type": "bar",
            "data": {
                "labels": ["Result Generation", "Fee Reconciliation", "Inventory Audit"],
                "datasets": [
                    {"label": "Legacy Manual (Days)", "data": [14, 7, 5], "backgroundColor": "rgba(239, 68, 68, 0.4)"},
                    {"label": "DOMMaterdei SMS (Secs)", "data": [12, 5, 3], "backgroundColor": "#007AFF"},
                ],
            },
            "options": {"responsive": True, "plugins": {"legend": {"labels": {"font": {"size": 9}}}}},
        },
        "gallery": [
            {
                "static_path": "brand/images/mater dei.png",
                "alt": "DOMMaterdei Portal",
                "caption": "Expand Mockup 1: Director & Inventory Portal",
                "lightbox_title": "DOMMaterdei SMS - Directors Portal & Inventory Management",
            },
            {
                "static_path": "brand/images/materdei2.png",
                "alt": "DOMMaterdei Results",
                "caption": "Expand Mockup 2: Automated Result Generator",
                "lightbox_title": "DOMMaterdei SMS - Result Generator & Student Portal",
            },
        ],
        "features": [
            ("fas fa-boxes-stacked", "Inventory & Asset Management",
             "Real-time tracking of textbooks, laboratory equipment, and school supplies."),
            ("fas fa-bolt", "Automated Result Generation",
             "Instant calculation of grades, class position rankings, and printable PDF report cards."),
            ("fas fa-money-check-dollar", "Fee Payment & Portals",
             "M-Pesa fee reconciliation, Director metrics dashboard, and parent portal access."),
        ],
    },
    {
        "slug": "poise",
        "title": "Poise and Purpose Kenya — Corporate Showcase Platform",
        "short_description": (
            "An executive, well-structured, and visually appealing web platform designed for "
            "Poise & Purpose Kenya to showcase corporate services, consulting portfolios, and "
            "event management capabilities."
        ),
        "project_url": "https://poiseandpurposekenya.org/",
        "phase": "completed",
        "display_order": 3,
        "accent": "#C084FC",
        "accent_deep": "#A855F7",
        "badge_icon": "fas fa-gem",
        "badge_label": "Deployed Brand Showcase",
        "cta_label": "Visit Platform",
        "features_heading": "Design Highlights",
        "chart_heading": "Data Story: Inbound Lead Growth Post-Redesign",
        "chart_icon": "fas fa-chart-line",
        "chart_spec": {
            "type": "line",
            "data": {
                "labels": ["Month 1", "Month 2", "Month 3", "Month 4", "Month 5", "Month 6"],
                "datasets": [{
                    "label": "Inbound Corporate Inquiries",
                    "data": [12, 19, 34, 52, 78, 105],
                    "borderColor": "#A855F7",
                    "backgroundColor": "rgba(168, 85, 247, 0.15)",
                    "fill": True,
                    "tension": 0.4,
                }],
            },
            "options": {"responsive": True, "plugins": {"legend": {"display": False}}},
        },
        "gallery": [
            {
                "static_path": "brand/images/poise.png",
                "alt": "Poise Landing Page",
                "caption": "Expand Mockup 1: Brand Hero & Executive Services",
                "lightbox_title": "Poise & Purpose - Corporate Landing Page",
            },
            {
                "static_path": "brand/images/poise2.png",
                "alt": "Poise Portfolio",
                "caption": "Expand Mockup 2: Portfolio & Consultation Intake",
                "lightbox_title": "Poise & Purpose - Consultation Booking & Portfolio",
            },
        ],
        "features": [
            ("fas fa-paint-brush", "Glassmorphic Aesthetic",
             "Tailored color schemes and fluid micro-animations creating a luxury executive feel."),
            ("fas fa-mobile-screen-button", "Responsive Performance",
             "Optimized asset loading delivering 99+ Google Lighthouse scores across all mobile devices."),
        ],
    },
    {
        "slug": "kiamiko",
        "title": "Kiamiko Meat Selling WhatsApp Automation & Inventory CRM",
        "short_description": (
            "WhatsApp-native order automation enabling customers to select meat cuts, pay via "
            "M-Pesa STK push, and receive doorstep delivery, paired with a real-time CRM tracking "
            "slaughterhouse inventory and daily operations."
        ),
        "project_url": "https://wa.me/254715097128",
        "phase": "active",
        "display_order": 1,
        "accent": "#25D366",
        "badge_icon": "fab fa-whatsapp",
        "badge_label": "In Active Build • Conversational Commerce",
        "cta_label": "Test Bot (+254715097128)",
        "cta_icon": "fab fa-whatsapp text-sm",
        "features_heading": "System Architecture",
        "chart_heading": "Data Story: Order Volume vs Delivery Speed (Minutes)",
        "chart_icon": "fas fa-chart-bar",
        # The WhatsApp card is the one product whose button is brand-coloured
        # rather than the site primary, and whose icon leads the label.
        "style_overrides": {
            "cta_icon_first": True,
            "cta_extra_classes": "bg-[#25D366] hover:bg-emerald-500 text-black",
            "chart_heading_accent": True,
        },
        "chart_spec": {
            "type": "bar",
            "data": {
                "labels": ["9 AM", "12 PM", "3 PM", "6 PM", "8 PM"],
                "datasets": [
                    {"label": "WhatsApp Orders", "data": [45, 120, 85, 160, 90], "backgroundColor": "#25D366"},
                    {"label": "Delivery Time (Mins)", "data": [18, 22, 20, 25, 19], "backgroundColor": "#007AFF"},
                ],
            },
            "options": {"responsive": True, "plugins": {"legend": {"labels": {"font": {"size": 9}}}}},
        },
        "gallery": [
            {
                "static_path": "brand/images/wozapauto.png",
                "alt": "Kiamiko WhatsApp Bot",
                "caption": "Expand Mockup 1: WhatsApp Ordering Bot (+254715097128)",
                "lightbox_title": "Kiamiko - WhatsApp Automated Meat Ordering Bot",
            },
            {
                "static_path": "brand/images/wozapauto2.png",
                "alt": "Kiamiko Inventory CRM",
                "caption": "Expand Mockup 2: Kiamiko Inventory CRM",
                "lightbox_title": "Kiamiko CRM - Slaughterhouse Inventory & Dispatch Dashboard",
            },
        ],
        "features": [
            ("fab fa-whatsapp", "Conversational Bot",
             "Instant meat cut selection, weight calculations, and order confirmation over WhatsApp."),
            ("fas fa-credit-card", "M-Pesa STK Integration",
             "Auto-triggers payment prompts directly on customer mobile devices upon checkout."),
            ("fas fa-warehouse", "Kiamiko Inventory CRM",
             "Real-time tracking of cold-storage stock levels, butchery sales, and delivery rider dispatch."),
        ],
    },
    {
        "slug": "campus-food",
        "title": "Campus Fast-Food Delivery & Student Rider Network",
        "short_description": (
            "A high-throughput food distribution system engineered for university campuses, "
            "connecting canteens to student hostels during peak hours while providing flexible "
            "earning opportunities for student riders."
        ),
        "phase": "active",
        "display_order": 2,
        "accent": "#FBBF24",
        "accent_deep": "#F59E0B",
        "badge_icon": "fas fa-utensils",
        "badge_label": "In Active Build • Campus Logistics",
        "features_heading": "Logistics Features",
        "chart_heading": "Data Story: Peak Hour Delivery Speed (Mins)",
        "chart_icon": "fas fa-chart-line",
        "style_overrides": {"chart_heading_accent": True},
        "chart_spec": {
            "type": "line",
            "data": {
                "labels": ["11 AM", "1 PM", "4 PM", "7 PM", "10 PM"],
                "datasets": [{
                    "label": "Peak Hour Hostel Deliveries",
                    "data": [28, 142, 65, 198, 110],
                    "borderColor": "#F59E0B",
                    "backgroundColor": "rgba(245, 158, 11, 0.15)",
                    "fill": True,
                    "tension": 0.4,
                }],
            },
            "options": {"responsive": True, "plugins": {"legend": {"display": False}}},
        },
        "gallery": [
            {
                "remote_url": "https://images.unsplash.com/photo-1526367790999-0150786686a2?w=800&auto=format&fit=crop&q=80",
                "full_url": "https://images.unsplash.com/photo-1526367790999-0150786686a2?w=1200&auto=format&fit=crop&q=80",
                "alt": "Campus Ordering",
                "caption": "Expand Mockup 1: Student Food Ordering Interface",
                "lightbox_title": "Campus Delivery - Student Food Ordering App",
            },
            {
                "remote_url": "https://images.unsplash.com/photo-1586880244406-556ebe35f282?auto=format&fit=crop&w=800&q=80",
                "full_url": "https://images.unsplash.com/photo-1586880244406-556ebe35f282?auto=format&fit=crop&w=1200&q=80",
                "alt": "Campus Rider App",
                "caption": "Expand Mockup 2: Student Rider Dispatch Telemetry",
                "lightbox_title": "Campus Delivery - Student Rider Dispatch & Earnings",
            },
        ],
        "features": [
            ("fas fa-stopwatch", "Sub-15 Min Campus Delivery",
             "Grouped hostel batching algorithms optimized for peak study hours."),
            ("fas fa-bicycle", "Peer Student Rider Program",
             "Flexible gig opportunities for university students to earn income between lectures."),
        ],
    },
    {
        "slug": "holodesk",
        "title": "HoloDesk Workspace OS — Spatial Learning & Collaboration Platform",
        "short_description": (
            "An AI-native spatial workspace platform engineered for universities (especially ODEL "
            "institutions) and enterprise teams. Users enter persistent virtual campuses, "
            "classrooms, and research labs through any browser while the workspace runs in the cloud."
        ),
        "phase": "future",
        "display_order": 1,
        "accent": "#38BDF8",
        "accent_deep": "#0EA5E9",
        "badge_icon": "fas fa-vr-cardboard",
        "badge_label": "Flagship Future Product Specification",
        "card_variant": "spotlight",
        "gallery_heading": "Spatial Concept Architecture",
        "features_heading": "Features & Technology Stack",
        "chart_heading": "HoloDesk Target Spatial Benchmarks",
        "chart_icon": "fas fa-chart-radar",
        "style_overrides": {"chip_text": "#7DD3FC", "chart_heading_accent": True},
        "chart_spec": {
            "type": "radar",
            "data": {
                "labels": ["Concurrent Classrooms", "WebRTC Latency", "AI Agent Accuracy",
                           "Mobile Optimization", "Persistence"],
                "datasets": [{
                    "label": "HoloDesk OS Spec Target (%)",
                    "data": [99, 95, 98, 95, 100],
                    "borderColor": "#38BDF8",
                    "backgroundColor": "rgba(56, 189, 248, 0.2)",
                    "borderWidth": 2,
                }],
            },
            "options": {
                "responsive": True,
                "scales": {"r": {"grid": {"color": "rgba(255, 255, 255, 0.08)"},
                                 "pointLabels": {"font": {"size": 9}},
                                 "ticks": {"display": False}}},
                "plugins": {"legend": {"display": False}},
            },
        },
        "notes": [
            {
                "heading": "The Problem",
                "icon": "fas fa-triangle-exclamation",
                "color": "#F87171",
                "body": (
                    "Current online education relies on disconnected tools (LMS, Zoom, email). "
                    "Students feel isolated, collaboration is fragmented, and practical laboratory "
                    "learning is non-existent. Enterprises face identical issues with distributed "
                    "remote teams."
                ),
            },
            {
                "heading": "The HoloDesk Solution",
                "icon": "fas fa-circle-check",
                "color": "#00FF94",
                "body": (
                    "HoloDesk replaces fragmented tools with a persistent 3D spatial campus. "
                    "Lecturers teach in virtual halls, researchers collaborate in dedicated spatial "
                    "labs, and learning artifacts remain permanently accessible after meetings."
                ),
            },
        ],
        "gallery": [
            {
                "remote_url": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=800&auto=format&fit=crop&q=80",
                "full_url": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1200&auto=format&fit=crop&q=80",
                "alt": "HoloDesk Campus",
                "caption": "Expand Mockup 1: 3D Persistent Virtual Campus",
                "lightbox_title": "HoloDesk OS - 3D Persistent Virtual Campus & Classrooms",
            },
            {
                "remote_url": "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?w=800&auto=format&fit=crop&q=80",
                "full_url": "https://images.unsplash.com/photo-1634017839464-5c339ebe3cb4?w=1200&auto=format&fit=crop&q=80",
                "alt": "HoloDesk Lab",
                "caption": "Expand Mockup 2: AI Multi-Agent & 3D Lab",
                "lightbox_title": "HoloDesk OS - AI Multi-Agent Assistants & Virtual Science Lab",
            },
        ],
        "chips": [
            "Next.js & React",
            "Three.js 3D Engine",
            "FastAPI & Python",
            "PostgreSQL & Neo4j",
            "WebRTC & WebSockets",
            "Kubernetes & Vector DB",
        ],
        "checks": [
            "Persistent Virtual Campuses & Offices",
            "AI Multi-Agent Teaching Assistants & Auto-Summaries",
            "Virtual 3D Science Laboratories & Whiteboards",
            "Low-Bandwidth Mobile-First Spatial Streaming for Africa",
        ],
    },
]

SLUGS = [p["slug"] for p in PRODUCTS]


def seed(apps, schema_editor):
    Project = apps.get_model("brand", "Project")
    ProjectImage = apps.get_model("brand", "ProjectImage")
    ProjectFeature = apps.get_model("brand", "ProjectFeature")
    ProjectNote = apps.get_model("brand", "ProjectNote")

    for spec in PRODUCTS:
        if Project.objects.filter(slug=spec["slug"]).exists():
            continue

        project = Project.objects.create(
            slug=spec["slug"],
            title=spec["title"],
            short_description=spec["short_description"],
            # The showcase card renders short_description; description is the
            # /projects/ detail page's long text, which these never had.
            description=spec["short_description"],
            project_url=spec.get("project_url") or None,
            showcase=True,
            phase=spec["phase"],
            display_order=spec["display_order"],
            accent=spec["accent"],
            accent_deep=spec.get("accent_deep", ""),
            badge_icon=spec["badge_icon"],
            badge_label=spec["badge_label"],
            cta_label=spec.get("cta_label", ""),
            cta_icon=spec.get("cta_icon", "fas fa-external-link-alt"),
            gallery_heading=spec.get("gallery_heading", "Interface Gallery"),
            features_heading=spec["features_heading"],
            chart_heading=spec.get("chart_heading", ""),
            chart_icon=spec.get("chart_icon", "fas fa-chart-bar"),
            chart_spec=spec.get("chart_spec"),
            card_variant=spec.get("card_variant", "default"),
            style_overrides=spec.get("style_overrides", {}),
        )

        for order, image in enumerate(spec.get("gallery", [])):
            ProjectImage.objects.create(
                project=project,
                static_path=image.get("static_path", ""),
                remote_url=image.get("remote_url", ""),
                full_url=image.get("full_url", ""),
                alt=image.get("alt", ""),
                caption=image.get("caption", ""),
                lightbox_title=image.get("lightbox_title", ""),
                order=order,
            )

        order = 0
        for icon, label, text in spec.get("features", []):
            ProjectFeature.objects.create(
                project=project, style="card", icon=icon,
                label=label, text=text, order=order,
            )
            order += 1
        for chip in spec.get("chips", []):
            ProjectFeature.objects.create(
                project=project, style="chip", text=chip, order=order,
            )
            order += 1
        for check in spec.get("checks", []):
            ProjectFeature.objects.create(
                project=project, style="check", icon="fas fa-check",
                text=check, order=order,
            )
            order += 1

        for order, note in enumerate(spec.get("notes", [])):
            ProjectNote.objects.create(
                project=project,
                heading=note["heading"],
                body=note["body"],
                icon=note.get("icon", ""),
                color=note.get("color", ""),
                order=order,
            )


def unseed(apps, schema_editor):
    Project = apps.get_model("brand", "Project")
    # Children cascade.
    Project.objects.filter(slug__in=SLUGS, showcase=True).delete()


def backfill_slugs(apps, schema_editor):
    """Give pre-existing projects a slug so the column is usable as a key."""
    from django.utils.text import slugify

    Project = apps.get_model("brand", "Project")
    for project in Project.objects.filter(slug=""):
        project.slug = slugify(project.title)[:220] or f"project-{project.pk}"
        project.save(update_fields=["slug"])


class Migration(migrations.Migration):

    dependencies = [
        ("brand", "0014_project_accent_project_accent_deep_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
        migrations.RunPython(seed, unseed),
    ]

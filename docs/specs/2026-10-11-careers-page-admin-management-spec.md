# Careers Page & Admin Management System — Technical Specification

**Date:** 2026-10-11  
**Status:** Planned / Architecture Specification  
**Affected Apps:** `brandtechsolution/brand`, `brandtechsolution/staff`, `docs`

---

## 🎯 1. Executive Summary & Objective

Teklora Solutions currently has an active public route `/careers/` rendered via [careers.html](file:///d:/brantech-full-website-master/brandtechsolution/brand/templates/brand/careers.html) and [views.py](file:///d:/brantech-full-website-master/brandtechsolution/brand/views.py). However, this page currently displays **static, hardcoded HTML job listings** ("Senior Backend Engineer", "UI/UX Product Designer", "Data Scientist"). 

There is currently **no administrative mechanism** within the platform (neither Django Admin nor the custom Teklora Admin panel at `/admin-panel/`) to create, update, publish, unpublish, or archive job openings, nor to configure the headline copy or application endpoints dynamically.

### Objectives:
1. **Dynamic Job Postings Model (`JobOpening` / `CareerPosting`)**: Enable rich metadata for open roles including department, work mode (remote/hybrid/onsite), contract type (full-time/part-time/internship), seniority, detailed descriptions, responsibilities, requirements, and direct application routes.
2. **Teklora Admin Panel Integration (`/admin-panel/?section=careers`)**:
   - Provide administrative listing of all active, draft, and archived positions with real-time counters.
   - Modal-based creation and editing with instant validation.
   - One-click toggle for publishing/archiving roles (`is_active`).
   - Integrated with staff capability permissions (`can.manage_careers` or `can.manage_content`).
3. **Public Page Modernization**:
   - Dynamically load active positions from the database on [careers.html](file:///d:/brantech-full-website-master/brandtechsolution/brand/templates/brand/careers.html).
   - Display department filters and search.
   - Clean drawer / modal or expandable details view for responsibilities and requirements.
   - Graceful fallback state when no positions are open, prompting general candidate resume submissions to `careers@teklora.com`.

---

## 🏗️ 2. Architectural Design & Data Model

### 2.1 Model Definition (`brandtechsolution/brand/models.py`)

```python
class JobOpening(models.Model):
    """
    Job and internship opportunities published by Teklora Solutions Ltd.
    Managed via Teklora Admin (/admin-panel/?section=careers).
    """
    class WorkMode(models.TextChoices):
        REMOTE = "remote", "Remote"
        HYBRID = "hybrid", "Hybrid"
        ONSITE = "onsite", "On-site (Nairobi HQ)"

    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        INTERNSHIP = "internship", "Internship"

    class Department(models.TextChoices):
        ENGINEERING = "engineering", "Engineering & Architecture"
        AI_RESEARCH = "ai_research", "AI & Spatial Research"
        DESIGN = "design", "Product & UI/UX Design"
        OPERATIONS = "operations", "Operations & Growth"
        MARKETING = "marketing", "Brand & Communications"

    title = models.CharField(max_length=200, help_text="Job title, e.g. Senior Backend Engineer (Python/Django)")
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    department = models.CharField(max_length=50, choices=Department.choices, default=Department.ENGINEERING)
    work_mode = models.CharField(max_length=30, choices=WorkMode.choices, default=WorkMode.HYBRID)
    employment_type = models.CharField(max_length=30, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME)
    location = models.CharField(max_length=150, default="Nairobi Office / Hybrid")
    
    summary = models.TextField(help_text="Short teaser displayed on the careers overview card")
    description = models.TextField(help_text="Full role description and mission")
    responsibilities = models.JSONField(default=list, blank=True, help_text="List of key duties and responsibilities")
    requirements = models.JSONField(default=list, blank=True, help_text="Required skills, languages, and qualifications")
    nice_to_have = models.JSONField(default=list, blank=True, help_text="Bonus skills / preferred qualifications")

    application_email = models.EmailField(default="careers@teklora.com")
    application_url = models.URLField(blank=True, default="", help_text="External application portal URL if applicable")
    
    is_active = models.BooleanField(default=True, db_index=True, help_text="Active roles are displayed on the public website")
    featured = models.BooleanField(default=False, help_text="Featured roles highlighted at top of careers page")
    order = models.PositiveIntegerField(default=0, help_text="Custom display order")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-created_at"]
        verbose_name = "Job Opening"
        verbose_name_plural = "Job Openings"

    def __str__(self):
        return f"{self.title} ({self.get_department_display()})"
```

---

## 💻 3. Admin Panel UI & Workflows

### 3.1 Admin Panel Section: `_careers.html`
- Located in `brandtechsolution/brand/templates/brand/admin/_careers.html`.
- Accessible via `/admin-panel/?section=careers` and gated via `can.manage_careers` or `can.manage_blog`.
- Components:
  1. **Metric Overview Cards**:
     - Total Postings
     - Active Open Roles
     - Departments Represented
  2. **Job Postings Data Table / Card Grid**:
     - Status Badge (`Active` / `Draft` / `Archived`)
     - Role Title & Department Chip
     - Work Mode & Employment Type Badges
     - Quick Toggle Action (`Publish` / `Unpublish`)
     - Edit & Delete Actions
  3. **Interactive Modal**:
     - Create / Edit Job Opening modal with form inputs for structured requirements & responsibilities.

### 3.2 REST / Form API Endpoints
- `GET /api/careers/`: List active careers for public or all careers for authenticated staff.
- `POST /api/careers/`: Create new job opening (Admin only).
- `PUT /api/careers/<id>/`: Update job opening details.
- `POST /api/careers/<id>/toggle-active/`: Instant status switch without reloading.
- `DELETE /api/careers/<id>/`: Remove or soft-archive position.

---

## 🌐 4. Public Page Enhancements (`careers.html`)

1. **Context Population in `views.py`**:
   ```python
   def careers(request):
       openings = JobOpening.objects.filter(is_active=True).order_by('order', '-created_at')
       departments = JobOpening.Department.choices
       return render(request, 'brand/careers.html', {
           'openings': openings,
           'departments': departments,
           'site_content': get_site_content(),
       })
   ```
2. **Interactive Client-side Filter**:
   - Filter pills by Department (All, Engineering, AI/Research, Design, Operations).
   - "Apply Now" triggers pre-filled `mailto:` with subject line `Application for {Job Title} - [Your Name]` or external portal URL.

---

## 📅 5. Implementation Roadmap
- **Phase 1**: Model creation, database migration, and Django Admin registration.
- **Phase 2**: Admin panel section (`_careers.html`) and CRUD APIs.
- **Phase 3**: Public template integration with dynamic queryset rendering and fallback states.
- **Phase 4**: Automated testing (`test_careers.py`) and permission verification.

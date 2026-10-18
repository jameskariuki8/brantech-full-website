from django.contrib import admin

from .models import Project, ProjectFeature, ProjectImage, ProjectNote, Career, PartnershipType, PartnerOrganisation


class ManageStaffAdminMixin:
    """Let staff who hold the Manage staff capability use these admin pages.

    Django's admin checks per-model permissions (brand.change_career and so
    on), which the panel's roles never carry: roles hold only staff.*
    capabilities. Without this the "Partnerships & People" link, shown to
    everyone with Manage staff, opened a 403 for every non-superuser. This is
    the same rule that gates Website Content, so the link and the page agree.
    """

    def _allowed(self, request):
        user = request.user
        return user.is_active and user.is_staff and user.has_perm("staff.manage_staff")

    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request)


class ProjectImageInline(admin.TabularInline):
    model = ProjectImage
    extra = 0
    fields = ('order', 'image', 'static_path', 'remote_url', 'full_url', 'alt', 'caption', 'lightbox_title')


class ProjectFeatureInline(admin.TabularInline):
    model = ProjectFeature
    extra = 0
    fields = ('order', 'style', 'icon', 'label', 'text')


class ProjectNoteInline(admin.TabularInline):
    model = ProjectNote
    extra = 0
    fields = ('order', 'heading', 'icon', 'color', 'body')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Deep editing for the showcase.

    The staff panel covers the fields people change week to week. This is the
    full surface -- gallery ordering, the Chart.js config, the style overrides
    -- for the rarer structural edit, so those never require a code change.
    """

    list_display = ('title', 'phase', 'display_order', 'showcase', 'featured', 'is_github_synced')
    list_filter = ('showcase', 'phase', 'featured', 'is_github_synced')
    search_fields = ('title', 'slug', 'short_description')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ProjectNoteInline, ProjectImageInline, ProjectFeatureInline]

    fieldsets = (
        (None, {
            'fields': ('title', 'slug', 'short_description', 'description',
                       'project_url', 'github_url', 'image', 'featured'),
        }),
        ('Showcase placement', {
            'fields': ('showcase', 'phase', 'display_order', 'card_variant'),
            'description': "Only projects with 'showcase' on appear on /products/.",
        }),
        ('Showcase theme', {
            'fields': ('accent', 'accent_deep', 'badge_icon', 'badge_label',
                       'cta_label', 'cta_icon'),
        }),
        ('Showcase sections', {
            'fields': ('gallery_heading', 'features_heading', 'chart_heading',
                       'chart_icon', 'chart_spec'),
        }),
        ('Advanced', {
            'classes': ('collapse',),
            'fields': ('style_overrides',),
        }),
        ('GitHub sync', {
            'classes': ('collapse',),
            'fields': ('is_github_synced', 'github_repo_id', 'github_role',
                       'commit_count', 'last_synced_at'),
        }),
    )
    # Written by the sync job, not by hand.
    readonly_fields = ('last_synced_at',)

@admin.register(Career)
class CareerAdmin(ManageStaffAdminMixin, admin.ModelAdmin):
    list_display = ('title', 'location', 'employment_type', 'status', 'posted_at')
    list_filter = ('status',)
    search_fields = ('title', 'description')
    ordering = ('-posted_at',)


@admin.register(PartnershipType)
class PartnershipTypeAdmin(ManageStaffAdminMixin, admin.ModelAdmin):
    """Admin for partnership categories shown on /partnerships/."""
    list_display  = ('title', 'tagline', 'status', 'order', 'created_at')
    list_filter   = ('status',)
    list_editable = ('status', 'order')
    search_fields = ('title', 'tagline', 'description')
    ordering      = ('order', 'title')
    fieldsets = (
        (None, {
            'fields': ('title', 'icon', 'accent', 'tagline', 'description', 'status', 'order'),
        }),
        ('Benefits & Requirements', {
            'description': 'Enter each item on its own line.',
            'fields': ('benefits', 'requirements'),
        }),
    )


@admin.register(PartnerOrganisation)
class PartnerOrganisationAdmin(ManageStaffAdminMixin, admin.ModelAdmin):
    """Admin for the partner logos showcase strip."""
    list_display  = ('name', 'sector', 'featured', 'order', 'joined_at', 'created_at')
    list_filter   = ('featured', 'sector')
    list_editable = ('featured', 'order')
    search_fields = ('name', 'sector', 'description')
    ordering      = ('order', 'name')

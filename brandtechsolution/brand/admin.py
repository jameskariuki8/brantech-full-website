from django.contrib import admin

from .models import Project, ProjectFeature, ProjectImage, ProjectNote


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

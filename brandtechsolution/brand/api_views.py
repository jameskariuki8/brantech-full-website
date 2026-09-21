import logging
import json
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator, EmptyPage
from .models import BlogPost, Project, ProjectFeature, ProjectImage, ProjectNote

logger = logging.getLogger(__name__)


def capability_required_json(request, codename):
    """Return an error response unless the request carries a capability.

    Returns None when the request may proceed. These are plain JSON views
    rather than DRF, so they return a response instead of raising.
    """
    user = request.user
    if not user.is_authenticated:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    if not (user.is_staff and user.has_perm(f'staff.{codename}')):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    return None


def can_view_drafts(request):
    """Whether the request is allowed to see draft (unpublished) blog posts.

    Only staff with the manage_blog capability get the unfiltered view;
    everyone else (including anonymous visitors and staff lacking that
    capability) only ever sees published posts.
    """
    user = request.user
    return user.is_authenticated and user.is_staff and user.has_perm('staff.manage_blog')


# Helper to parse FormData or JSON
def get_data(request):
    if request.content_type == 'application/json':
        return json.loads(request.body)
    return request.POST


def paginate_queryset(queryset, request, page_size=20):
    """
    Helper function to paginate querysets.
    
    Args:
        queryset: Django queryset to paginate
        request: HTTP request object
        page_size: Items per page (default 20)
    
    Returns:
        Tuple of (paginated_items, pagination_metadata)
    """
    page = request.GET.get('page', 1)
    try:
        page = int(page)
    except (ValueError, TypeError):
        page = 1
    
    paginator = Paginator(queryset, page_size)
    
    try:
        paginated_items = paginator.page(page)
    except EmptyPage:
        # Return last page if page number is too high
        paginated_items = paginator.page(paginator.num_pages)
    
    pagination_metadata = {
        'page': paginated_items.number,
        'page_size': page_size,
        'total_pages': paginator.num_pages,
        'total_items': paginator.count,
        'has_next': paginated_items.has_next(),
        'has_previous': paginated_items.has_previous(),
    }
    
    return paginated_items, pagination_metadata

# --- Blog Post APIs ---

@require_http_methods(["GET", "POST"])
def post_list(request):
    if request.method == "GET":
        posts = BlogPost.objects.all().order_by('-created_at')
        if not can_view_drafts(request):
            posts = posts.filter(status='published')
        # Use only() to fetch only required fields for better performance
        posts = posts.only('id', 'title', 'slug', 'category', 'excerpt', 'content', 'tags', 'featured', 'status', 'view_count', 'created_at', 'image')
        
        # Add pagination support
        paginated_posts, pagination_meta = paginate_queryset(posts, request, page_size=20)
        
        # Build response using list comprehension for better performance
        data = [
            {
                'id': post.id,
                'slug': post.slug,
                'title': post.title,
                'category': post.category,
                'excerpt': post.excerpt,
                'content': post.content,
                'tags': post.tags,
                'featured': post.featured,
                'status': post.status,
                'view_count': post.view_count,
                'created_at': post.created_at.isoformat(),
                'image': post.image.url if post.image else None
            }
            for post in paginated_posts
        ]
        
        return JsonResponse({
            'results': data,
            'pagination': pagination_meta
        }, safe=False)
    
    if request.method == "POST":
        denied = capability_required_json(request, 'manage_blog')
        if denied:
            return denied
        try:
            # Handle FormData
            title = request.POST.get('title')
            category = request.POST.get('category')
            excerpt = request.POST.get('excerpt')
            content = request.POST.get('content')
            tags = request.POST.get('tags', '')
            featured = request.POST.get('featured') == 'true'
            image = request.FILES.get('image')

            # Allow superusers and staff with manage_blog/publish_blog to set status
            status = request.POST.get('status')
            if not status or status.strip() == '':
                status = 'published' if (request.user.is_superuser or request.user.has_perm('staff.publish_blog') or request.user.has_perm('staff.manage_blog')) else 'draft'

            if status not in ('draft', 'published'):
                return JsonResponse({'error': 'Invalid status'}, status=400)
            if status == 'published' and not (request.user.is_superuser or request.user.has_perm('staff.publish_blog') or request.user.has_perm('staff.manage_blog')):
                denied = capability_required_json(request, 'publish_blog')
                if denied:
                    return denied

            post = BlogPost.objects.create(
                title=title,
                category=category,
                excerpt=excerpt,
                content=content,
                tags=tags,
                featured=featured,
                status=status,
                image=image
            )
            return JsonResponse({'id': post.id, 'message': 'Post created successfully'}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

@require_http_methods(["GET", "POST", "PUT", "DELETE"])
def post_detail(request, pk):
    post = get_object_or_404(BlogPost, pk=pk)

    if request.method == "GET":
        if post.status != 'published' and not can_view_drafts(request):
            raise Http404("Post not found")
        data = {
            'id': post.id,
            'slug': post.slug,
            'title': post.title,
            'category': post.category,
            'excerpt': post.excerpt,
            'content': post.content,
            'tags': post.tags,
            'featured': post.featured,
            'status': post.status,
            'view_count': post.view_count,
            'created_at': post.created_at.isoformat(),
            'image': post.image.url if post.image else None
        }
        return JsonResponse(data)

    if request.method == "PUT":
        try:
            # Django's request.POST/FILES only works for POST. For PUT with FormData, it's tricky.
            # However, the JS uses method: 'PUT'. Django doesn't parse multipart/form-data for PUT out of the box.
            # We might need to rely on a workaround or change JS to use POST with a method override, 
            # OR technically, we can parse request.body if it wasn't multipart.
            # Since we have file uploads, multipart is needed. 
            # FIX: We'll construct a mutable copy of GET/POST/bodge it, OR better:
            # For simplicity in this environment, let's assume the user might switch to POST for updates 
            # or we handle it manually. But wait, standard Django `request.PUT` isn't a thing.
            # 
            # Use request.method == 'POST' for updates? No, REST is PUT.
            # Let's try to extract data from request.body if not multipart, but it IS multipart.
            # 
            # A common hack: frontend sends POST but with X-Method-Override or similar? 
            # OR simpler: The JS I wrote sends `method: 'PUT'`.
            # If I can't easily parse multipart PUT in basic Django, I'll update the JS to use POST for updates too?
            # 
            # ACTUALLY: `django-rest-framework` handles this. Pure Django does not populate request.POST for PUT.
            # I will change the JS to use POST for updates as well to save headache, 
            # OR I will try to read from request.GET if I passed params there? No.
            # 
            # Let's keep this view expecting PUT but logic might fail if accessing request.POST.
            # I will modify the JS to send POST for updates to `/api/posts/<id>/update/`? 
            # Or just `/api/posts/<id>/` with POST method?
            # 
            # Let's use `request.method == 'POST'` in `post_update` and change URL routing?
            # 
            # No, let's just stick to "POST" for create and "POST" for update in this specific context 
            # to ensure file uploads work seamlessly without DRF. 
            # 
            # I need to update the JavaScript in admin_panel.html to use POST for updates if I do this.
            # 
            # Let's write the view to accept POST for update if the URL implies update.
            # But the URL is `/posts/<id>/`. 
            # If a POST comes to `/posts/<id>/`, it's an update. That works. Only GET is idempotent.
            # 
            # So I will support POST on `post_detail` for updates.
            pass
        except:
            pass
            
    # Redefining logic to support POST for updates on detail view
    if request.method == "POST" or request.method == "PUT":
        denied = capability_required_json(request, 'manage_blog')
        if denied:
            return denied
        try:
            # If PUT, request.POST might be empty.
            # Let's check if we have data. If not, maybe it's a JSON body?
            # But we are sending FormData.
            # I'll update the JS to send POST. That's the most robust fix.

            requested_status = request.POST.get('status')
            if not requested_status or requested_status.strip() == '':
                requested_status = 'published' if (request.user.is_superuser or request.user.has_perm('staff.publish_blog') or request.user.has_perm('staff.manage_blog')) else post.status
            if requested_status not in ('draft', 'published'):
                return JsonResponse({'error': 'Invalid status'}, status=400)
            if requested_status != post.status and requested_status == 'published':
                if not (request.user.is_superuser or request.user.has_perm('staff.publish_blog') or request.user.has_perm('staff.manage_blog')):
                    denied = capability_required_json(request, 'publish_blog')
                    if denied:
                        return denied
            post.status = requested_status

            post.title = request.POST.get('title', post.title)
            post.category = request.POST.get('category', post.category)
            post.excerpt = request.POST.get('excerpt', post.excerpt)
            post.content = request.POST.get('content', post.content)
            post.tags = request.POST.get('tags', post.tags)
            post.featured = request.POST.get('featured') == 'true'

            if 'image' in request.FILES:
                post.image = request.FILES['image']
                
            post.save()
            return JsonResponse({'id': post.id, 'message': 'Post updated successfully'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    if request.method == "DELETE":
        denied = capability_required_json(request, 'manage_blog')
        if denied:
            return denied
        post.delete()
        return JsonResponse({'message': 'Post deleted successfully'})

# --- Project APIs ---

# ============================================================
# SHOWCASE SERIALISATION
# ============================================================
# The six /products/ articles are Project rows now, so the panel has to be
# able to read and write the fields that used to be markup. Kept here beside
# the rest of the project API rather than in a serializer module, matching how
# the other function-based endpoints in this file are written.

SHOWCASE_SCALARS = [
    'slug', 'showcase', 'phase', 'display_order', 'accent', 'accent_deep',
    'badge_icon', 'badge_label', 'cta_label', 'cta_icon', 'gallery_heading',
    'features_heading', 'chart_heading', 'chart_icon', 'card_variant',
]
_SHOWCASE_BOOLS = {'showcase'}
_SHOWCASE_INTS = {'display_order'}
# An unmodified HTML checkbox posts "on", JSON clients post "true", and
# core.js normalises its own checkboxes to "true"/"false". Accept all three
# rather than silently reading a ticked box as False.
_TRUTHY = {'true', 'on', '1', 'yes'}


def serialize_showcase(project):
    """The showcase half of a project, including its child collections."""
    data = {field: getattr(project, field) for field in SHOWCASE_SCALARS}
    data['chart_spec'] = project.chart_spec
    data['style_overrides'] = project.style_overrides
    data['gallery'] = [
        {
            'id': i.id, 'src': i.src, 'expanded_src': i.expanded_src,
            'static_path': i.static_path, 'remote_url': i.remote_url,
            'full_url': i.full_url, 'alt': i.alt, 'caption': i.caption,
            'lightbox_title': i.lightbox_title, 'order': i.order,
        }
        for i in project.gallery.all()
    ]
    data['features'] = [
        {
            'id': f.id, 'style': f.style, 'icon': f.icon,
            'label': f.label, 'text': f.text, 'order': f.order,
        }
        for f in project.features.all()
    ]
    data['notes'] = [
        {
            'id': n.id, 'heading': n.heading, 'body': n.body,
            'icon': n.icon, 'color': n.color, 'order': n.order,
        }
        for n in project.notes.all()
    ]
    return data


def apply_showcase_fields(project, post):
    """Copy any showcase fields present in the payload onto the project.

    Absent keys are left alone so a form that only posts the basic fields --
    which is every caller that predates the showcase -- cannot blank the
    theming. Booleans are the exception: an HTML checkbox sends nothing when
    unticked, so `showcase` is only read when the form declares it did send
    the field, via the `has_showcase_fields` marker.
    """
    declares_showcase = post.get('has_showcase_fields') == 'true'

    for field in SHOWCASE_SCALARS:
        if field in _SHOWCASE_BOOLS:
            if declares_showcase:
                raw = (post.get(field) or '').strip().lower()
                setattr(project, field, raw in _TRUTHY)
            continue
        if field not in post:
            continue
        value = post.get(field)
        if field in _SHOWCASE_INTS:
            try:
                value = int(value or 0)
            except (TypeError, ValueError):
                continue
        setattr(project, field, value)

    for field in ('chart_spec', 'style_overrides'):
        if field not in post:
            continue
        raw = (post.get(field) or '').strip()
        if not raw:
            setattr(project, field, None if field == 'chart_spec' else {})
            continue
        try:
            setattr(project, field, json.loads(raw))
        except ValueError as exc:
            raise ValueError(f"{field} is not valid JSON: {exc}") from exc


def replace_showcase_children(project, post):
    """Replace gallery / features / notes wholesale when the payload has them.

    Replace rather than patch: the panel edits these as ordered lists, and
    diffing three collections by id from a multipart form is far more code
    than deleting and recreating rows that carry no foreign keys of their own.
    A collection the payload does not mention is left untouched.
    """
    specs = [
        ('gallery', ProjectImage, ('static_path', 'remote_url', 'full_url',
                                   'alt', 'caption', 'lightbox_title')),
        ('features', ProjectFeature, ('style', 'icon', 'label', 'text')),
        ('notes', ProjectNote, ('heading', 'body', 'icon', 'color')),
    ]
    for key, model, fields in specs:
        if key not in post:
            continue
        raw = (post.get(key) or '').strip()
        try:
            rows = json.loads(raw) if raw else []
        except ValueError as exc:
            raise ValueError(f"{key} is not valid JSON: {exc}") from exc
        if not isinstance(rows, list):
            raise ValueError(f"{key} must be a list")

        getattr(project, key).all().delete()
        for order, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(f"{key} entries must be objects")
            model.objects.create(
                project=project, order=order,
                **{f: row.get(f) or '' for f in fields},
            )


@require_http_methods(["GET", "POST"])
def project_list(request):
    if request.method == "GET":
        projects = Project.objects.all().order_by('-created_at')
        # Include GitHub-specific fields alongside standard ones
        projects = projects.prefetch_related('gallery', 'features', 'notes')
        
        # Add pagination support
        paginated_projects, pagination_meta = paginate_queryset(projects, request, page_size=20)
        
        # Build response using list comprehension for better performance
        data = [
            {
                'id': p.id,
                'title': p.title,
                'short_description': p.short_description,
                'description': p.description,
                'project_url': p.project_url,
                'github_url': p.github_url,
                'featured': p.featured,
                'image': p.image.url if p.image else None,
                'is_github_synced': p.is_github_synced,
                'commit_count': p.commit_count,
                'github_role': p.github_role,
                **serialize_showcase(p),
            }
            for p in paginated_projects
        ]
        
        return JsonResponse(data, safe=False)
    
    if request.method == "POST":
        denied = capability_required_json(request, 'manage_projects')
        if denied:
            return denied
        try:
            title = request.POST.get('title')
            short_description = request.POST.get('short_description')
            description = request.POST.get('description')
            project_url = request.POST.get('project_url')
            github_url = request.POST.get('github_url')
            featured = request.POST.get('featured') == 'true'
            image = request.FILES.get('image')

            project = Project(
                title=title,
                short_description=short_description,
                description=description,
                project_url=project_url,
                github_url=github_url,
                featured=featured,
                image=image
            )
            apply_showcase_fields(project, request.POST)
            project.save()
            replace_showcase_children(project, request.POST)
            return JsonResponse({'id': project.id, 'message': 'Project created successfully'}, status=201)
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

@require_http_methods(["GET", "POST", "PUT", "DELETE"])
def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    
    if request.method == "GET":
        data = {
            'id': project.id,
            'title': project.title,
            'short_description': project.short_description,
            'description': project.description,
            'project_url': project.project_url,
            'github_url': project.github_url,
            'featured': project.featured,
            'image': project.image.url if project.image else None,
            'is_github_synced': project.is_github_synced,
            'commit_count': project.commit_count,
            'github_role': project.github_role,
            'readme_content': project.readme_content,
            **serialize_showcase(project),
        }
        return JsonResponse(data)

    if request.method == "POST" or request.method == "PUT":
        denied = capability_required_json(request, 'manage_projects')
        if denied:
            return denied
        try:
            project.title = request.POST.get('title', project.title)
            project.short_description = request.POST.get('short_description', project.short_description)
            project.description = request.POST.get('description', project.description)
            project.project_url = request.POST.get('project_url', project.project_url)
            project.github_url = request.POST.get('github_url', project.github_url)
            project.featured = request.POST.get('featured') == 'true'
            
            if 'image' in request.FILES:
                project.image = request.FILES['image']

            apply_showcase_fields(project, request.POST)
            project.save()
            replace_showcase_children(project, request.POST)
            return JsonResponse({'id': project.id, 'message': 'Project updated successfully'})
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    if request.method == "DELETE":
        denied = capability_required_json(request, 'manage_projects')
        if denied:
            return denied
        project.delete()
        return JsonResponse({'message': 'Project deleted successfully'})

# --- GitHub Integration APIs ---
from .github_service import GitHubService

def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)

@login_required
@require_http_methods(["GET"])
def github_repos_list(request):
    if not is_admin(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        service = GitHubService()
        repos = service.get_user_repositories()
        return JsonResponse({'results': repos})
    except Exception:
        # Never echo the exception. GitHubService carries an API token, and
        # request failures from the client library routinely put the URL -
        # token and all - into the message.
        logger.exception('github_repos_list failed')
        return JsonResponse({'error': 'Could not reach GitHub.'}, status=500)

@login_required
@require_http_methods(["POST"])
def github_sync_selected(request):
    if not is_admin(request.user):
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    try:
        data = get_data(request)
        repo_ids = data.get('repo_ids', [])
        if not repo_ids:
            return JsonResponse({'error': 'No repository IDs provided'}, status=400)
            
        service = GitHubService()
        result = service.sync_repositories(repo_ids)
        if result.get("success"):
            return JsonResponse(result)
        else:
            return JsonResponse({'error': result.get("error")}, status=500)
    except Exception:
        logger.exception('github_sync_selected failed')
        return JsonResponse({'error': 'Could not sync repositories.'}, status=500)

@require_http_methods(["GET"])
def project_commits(request, pk):
    """
    Returns last 10 commits for a GitHub-synced project.

    Normal: served instantly from DB (cached_commits field).
    ?refresh=1: forces a live GitHub fetch and updates the DB cache.
    """
    project = get_object_or_404(Project, pk=pk)
    if not project.is_github_synced or not project.github_repo_id:
        return JsonResponse({'error': 'This project is not linked to GitHub.'}, status=400)
    try:
        force_refresh = request.GET.get('refresh') == '1'
        service = GitHubService()
        result = service.get_recent_commits(
            github_repo_id=project.github_repo_id,
            force_refresh=force_refresh,
        )
        return JsonResponse(result)
    except Exception:
        # This view has no @login_required, so its error body is public.
        logger.exception('project_commits failed for project %s', pk)
        return JsonResponse({'error': 'Could not fetch commits.'}, status=500)

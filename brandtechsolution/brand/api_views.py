import json
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from .models import BlogPost, Project

# Helper to parse FormData or JSON
def get_data(request):
    if request.content_type == 'application/json':
        return json.loads(request.body)
    return request.POST

# --- Blog Post APIs ---

@require_http_methods(["GET", "POST"])
def post_list(request):
    if request.method == "GET":
        posts = BlogPost.objects.all().order_by('-created_at')
        # Use only() to fetch only required fields for better performance
        posts = posts.only('id', 'title', 'category', 'excerpt', 'content', 'tags', 'featured', 'view_count', 'created_at', 'image')
        
        # Build response using list comprehension for better performance
        data = [
            {
                'id': post.id,
                'title': post.title,
                'category': post.category,
                'excerpt': post.excerpt,
                'content': post.content,
                'tags': post.tags,
                'featured': post.featured,
                'view_count': post.view_count,
                'created_at': post.created_at.isoformat(),
                'image': post.image.url if post.image else None
            }
            for post in posts
        ]
        return JsonResponse(data, safe=False)
    
    if request.method == "POST":
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        try:
            # Handle FormData
            title = request.POST.get('title')
            category = request.POST.get('category')
            excerpt = request.POST.get('excerpt')
            content = request.POST.get('content')
            tags = request.POST.get('tags', '')
            featured = request.POST.get('featured') == 'true'
            image = request.FILES.get('image')

            post = BlogPost.objects.create(
                title=title,
                category=category,
                excerpt=excerpt,
                content=content,
                tags=tags,
                featured=featured,
                image=image
            )
            return JsonResponse({'id': post.id, 'message': 'Post created successfully'}, status=201)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

@require_http_methods(["GET", "POST", "PUT", "DELETE"])
def post_detail(request, pk):
    post = get_object_or_404(BlogPost, pk=pk)
    
    if request.method == "GET":
        data = {
            'id': post.id,
            'title': post.title,
            'category': post.category,
            'excerpt': post.excerpt,
            'content': post.content,
            'tags': post.tags,
            'featured': post.featured,
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
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        try:
            # If PUT, request.POST might be empty. 
            # Let's check if we have data. If not, maybe it's a JSON body?
            # But we are sending FormData. 
            # I'll update the JS to send POST. That's the most robust fix.
            
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
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        post.delete()
        return JsonResponse({'message': 'Post deleted successfully'})

# --- Project APIs ---

@require_http_methods(["GET", "POST"])
def project_list(request):
    if request.method == "GET":
        projects = Project.objects.all().order_by('-created_at')
        # Use only() to fetch only required fields for better performance
        projects = projects.only('id', 'title', 'short_description', 'description', 'project_url', 'github_url', 'featured', 'image')
        
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
                'image': p.image.url if p.image else None
            }
            for p in projects
        ]
        return JsonResponse(data, safe=False)
    
    if request.method == "POST":
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        try:
            title = request.POST.get('title')
            short_description = request.POST.get('short_description')
            description = request.POST.get('description')
            project_url = request.POST.get('project_url')
            github_url = request.POST.get('github_url')
            featured = request.POST.get('featured') == 'true'
            image = request.FILES.get('image')

            project = Project.objects.create(
                title=title,
                short_description=short_description,
                description=description,
                project_url=project_url,
                github_url=github_url,
                featured=featured,
                image=image
            )
            return JsonResponse({'id': project.id, 'message': 'Project created successfully'}, status=201)
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
            'image': project.image.url if project.image else None
        }
        return JsonResponse(data)

    if request.method == "POST" or request.method == "PUT":
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        try:
            project.title = request.POST.get('title', project.title)
            project.short_description = request.POST.get('short_description', project.short_description)
            project.description = request.POST.get('description', project.description)
            project.project_url = request.POST.get('project_url', project.project_url)
            project.github_url = request.POST.get('github_url', project.github_url)
            project.featured = request.POST.get('featured') == 'true'
            
            if 'image' in request.FILES:
                project.image = request.FILES['image']
                
            project.save()
            return JsonResponse({'id': project.id, 'message': 'Project updated successfully'})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    if request.method == "DELETE":
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Unauthorized'}, status=401)
        project.delete()
        return JsonResponse({'message': 'Project deleted successfully'})

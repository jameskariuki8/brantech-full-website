import json
from types import SimpleNamespace
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import models
from django.db.models import F, Count
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from staff.capabilities import CODENAMES
from .models import BlogPost, BlogLike, BlogComment, Project
from .markdown_utils import render_markdown


def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)


def index(request):
    """Home page view"""
    return render(request, 'brand/index.html')


def about(request):
    """About page view"""
    return render(request, 'brand/about.html')


def products(request):
    """Products showcase view"""
    return render(request, 'brand/products.html')


def projects(request):
    """Projects view (alias for products)"""
    return render(request, 'brand/products.html')


def donate(request):
    """Donate page view"""
    return render(request, 'brand/donate.html')


def research(request):
    """Research & Engineering Tech Innovation page view"""
    return render(request, 'brand/research.html')


def faq(request):
    """FAQ page view"""
    return render(request, 'brand/faq.html')


def contacts(request):
    """Contact page view"""
    return render(request, 'brand/contacts.html')


def solutions(request):
    """Solutions page view"""
    return render(request, 'brand/solutions.html')


def privacy_policy(request):
    """Privacy Policy page view"""
    return render(request, 'brand/privacy.html')


def terms_conditions(request):
    """Terms & Conditions page view"""
    return render(request, 'brand/terms.html')



def blog(request):
    """Blog list page (server-rendered, paginated, sorted)."""
    sort_by = request.GET.get('sort', 'latest')
    
    queryset = BlogPost.objects.filter(status='published').annotate(
        likes_count=Count('likes', distinct=True),
        comments_count=Count('comments', distinct=True)
    )
    
    if sort_by == 'popular':
        queryset = queryset.order_by('-likes_count', '-created_at')
    else:
        queryset = queryset.order_by('-created_at')
        
    paginator = Paginator(queryset, 9)
    posts = paginator.get_page(request.GET.get("page"))
    return render(request, 'brand/blog.html', {
        'posts': posts,
        'sort_by': sort_by,
    })


def blog_detail(request, slug):
    """Server-rendered individual blog post at /blog/<slug>/."""
    post = get_object_or_404(BlogPost, slug=slug, status='published')
    BlogPost.objects.filter(pk=post.pk).update(view_count=F('view_count') + 1)
    content_html = render_markdown(post.content)
    
    likes_count = post.likes.count()
    comments = post.comments.filter(is_approved=True)
    
    return render(request, 'brand/blog_detail.html', {
        'post': post,
        'content_html': content_html,
        'likes_count': likes_count,
        'comments': comments,
    })


@login_required(login_url='/login/')
@user_passes_test(is_admin, login_url='/login/')
def admin_panel_page(request):
    """The panel shell.

    `capabilities` is the held set, serialised to JavaScript via json_script;
    `can` is the same set as an object so templates can write `{% if can.x %}`.
    Superusers pass has_perm() unconditionally, so they hold everything.
    This gating is cosmetic - each API enforces its own capability.
    """
    held = sorted(c for c in CODENAMES if request.user.has_perm(f'staff.{c}'))
    return render(request, 'brand/admin_panel.html', {
        'capabilities': held,
        'can': SimpleNamespace(**{c: True for c in held}),
    })


def projects(request):
    """Projects page view - public access"""
    return render(request, 'brand/projects.html')


def project_page(request, pk):
    """Single project detail page."""
    project = get_object_or_404(Project, pk=pk)
    return render(request, 'brand/project_detail.html', {'project': project})


def signup_view(request):
    """User signup view"""
    if request.method == 'POST':
        first_name = request.POST.get('firstName')
        last_name = request.POST.get('lastName')
        email = request.POST.get('email')
        password = request.POST.get('password')
        confirm_password = request.POST.get('confirmPassword')
        
        # Validation
        if not all([first_name, last_name, email, password, confirm_password]):
            messages.error(request, 'Please fill in all fields.')
            return render(request, 'brand/signup.html')
        
        if password != confirm_password:
            messages.error(request, 'Passwords do not match.')
            return render(request, 'brand/signup.html')
        
        # Check if user exists with this email or username in a single query
        if User.objects.filter(models.Q(email=email) | models.Q(username=email)).exists():
            messages.error(request, 'An account with this email already exists.')
            return render(request, 'brand/signup.html')
        
        # Create user
        try:
            user = User.objects.create_user(
                username=email,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )
            messages.success(request, 'Account created successfully! Please log in.')
            return redirect('login')
        except Exception as e:
            messages.error(request, f'Error creating account: {str(e)}')
            return render(request, 'brand/signup.html')
    
    return render(request, 'brand/signup.html')


def login_view(request):
    """User login view"""
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        remember_me = request.POST.get('remember')
        next_url = request.POST.get('next') or request.GET.get('next', '/')
        
        if not email or not password:
            messages.error(request, 'Please fill in all fields.')
            return render(request, 'brand/login.html', {'next': next_url})
        
        # Authenticate user (support both email and username)
        user = authenticate(request, username=email, password=password)
        
        # If authentication fails, try finding user by email or username in a single query
        if user is None:
            try:
                user_obj = User.objects.filter(
                    models.Q(username=email) | models.Q(email=email)
                ).first()
                
                if user_obj:
                    user = authenticate(request, username=user_obj.username, password=password)
            except Exception:
                pass

        if user is not None:
            login(request, user)
            if not remember_me:
                request.session.set_expiry(0)
            else:
                request.session.set_expiry(1209600)
            
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid email/username or password.')
            return render(request, 'brand/login.html', {'next': next_url})
    
    next_url = request.GET.get('next', '/')
    return render(request, 'brand/login.html', {'next': next_url})


def logout_view(request):
    """User logout view"""
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('index')


@csrf_exempt
def like_blog_post(request, post_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)
    
    try:
        data = json.loads(request.body)
        browser_id = data.get('browser_id')
    except Exception:
        browser_id = request.POST.get('browser_id')
        
    if not browser_id:
        return JsonResponse({'error': 'browser_id required'}, status=400)
        
    post = get_object_or_404(BlogPost, pk=post_id)
    
    like_qs = BlogLike.objects.filter(post=post, browser_id=browser_id)
    if like_qs.exists():
        like_qs.delete()
        liked = False
    else:
        BlogLike.objects.create(post=post, browser_id=browser_id)
        liked = True
        
    likes_count = post.likes.count()
    return JsonResponse({
        'liked': liked,
        'likes_count': likes_count
    })


@csrf_exempt
def comment_blog_post(request, post_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'POST request required'}, status=400)
        
    try:
        data = json.loads(request.body)
        browser_id = data.get('browser_id')
        user_name = data.get('user_name', 'Anonymous')
        content = data.get('content')
    except Exception:
        browser_id = request.POST.get('browser_id')
        user_name = request.POST.get('user_name', 'Anonymous')
        content = request.POST.get('content')
        
    if not browser_id or not content:
        return JsonResponse({'error': 'browser_id and content required'}, status=400)
        
    post = get_object_or_404(BlogPost, pk=post_id)
    
    comment = BlogComment.objects.create(
        post=post,
        browser_id=browser_id,
        user_name=user_name or 'Anonymous',
        content=content
    )
    
    return JsonResponse({
        'status': 'success',
        'comment': {
            'id': comment.id,
            'user_name': comment.user_name,
            'content': comment.content,
            'created_at': comment.created_at.strftime('%b %d, %Y at %H:%M')
        }
    })


def get_blog_comments(request, post_id):
    post = get_object_or_404(BlogPost, pk=post_id)
    comments = post.comments.all()
    comments_list = [
        {
            'id': c.id,
            'user_name': c.user_name,
            'content': c.content,
            'created_at': c.created_at.strftime('%b %d, %Y at %H:%M')
        }
        for c in comments
    ]
    return JsonResponse({'comments': comments_list})


def blog_json(request, post_id):
    post = get_object_or_404(BlogPost, pk=post_id)
    content_html = render_markdown(post.content)
    likes_count = post.likes.count()
    
    browser_id = request.GET.get('browser_id')
    user_liked = post.likes.filter(browser_id=browser_id).exists() if browser_id else False
    
    comments = [
        {
            'user_name': c.user_name,
            'content': c.content,
            'created_at': c.created_at.strftime('%b %d, %Y at %H:%M')
        } for c in post.comments.filter(is_approved=True)
    ]
    
    return JsonResponse({
        'id': post.id,
        'title': post.title,
        'category': post.category,
        'image': post.image.url if post.image else None,
        'created_at': post.created_at.strftime('%B %d, %Y'),
        'content_html': content_html,
        'likes_count': likes_count,
        'user_liked': user_liked,
        'comments': comments
    })

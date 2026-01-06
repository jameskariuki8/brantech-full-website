from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.contrib.auth.models import User
from django.db import models

# Create your views here.

def is_admin(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)

def index(request):
    """Home page view"""
    return render(request, 'brand/index.html')

def about(request):
    """About page view"""
    return render(request, 'brand/about.html')



def blog(request):
    """Blog page view"""
    return render(request, 'brand/blog.html')

def faq(request):
    """FAQ page view"""
    return render(request, 'brand/faq.html')

def contacts(request):
    """Contact page view"""
    return render(request, 'brand/contacts.html')

@login_required(login_url='/login/')
@user_passes_test(is_admin, login_url='/login/')
def admin_panel_page(request):
    return render(request, 'brand/admin_panel.html')



def projects(request):
    """Projects page view - public access"""
    return render(request, 'brand/projects.html')

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
                # Use Q object for a single database query
                user_obj = User.objects.filter(
                    models.Q(username=email) | models.Q(email=email)
                ).first()
                
                if user_obj:
                    # Authenticate with the found username
                    user = authenticate(request, username=user_obj.username, password=password)
            except Exception:
                pass


        if user is not None:
            login(request, user)
            if not remember_me:
                # Set session to expire when browser closes
                request.session.set_expiry(0)
            else:
                # Set session to expire in 2 weeks
                request.session.set_expiry(1209600)
            
            # Redirect to next page if specified, otherwise to home
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid email/username or password.')
            return render(request, 'brand/login.html', {'next': next_url})
    
    next_url = request.GET.get('next', '/')
    return render(request, 'brand/login.html', {'next': next_url})

def logout_view(request):
    """User logout view"""
    from django.contrib.auth import logout
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('index')
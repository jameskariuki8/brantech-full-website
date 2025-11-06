from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User

# Create your views here.

def index(request):
    """Home page view"""
    return render(request, 'brand/index.html')

def about(request):
    """About page view"""
    return render(request, 'brand/about.html')

def services(request):
    """Services page view"""
    return render(request, 'brand/services.html')

def blog(request):
    """Blog page view"""
    return render(request, 'brand/blog.html')

def faq(request):
    """FAQ page view"""
    return render(request, 'brand/faq.html')

def contacts(request):
    """Contact page view"""
    return render(request, 'brand/contacts.html')

def admin_panel_page(request):
    return render(request, 'brand/admin_panel.html')

@login_required(login_url='/login/')
def events(request):
    """Events page view - requires login"""
    return render(request, 'brand/events.html')

@login_required(login_url='/login/')
def projects(request):
    """Projects page view - requires login"""
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
        
        if User.objects.filter(email=email).exists():
            messages.error(request, 'An account with this email already exists.')
            return render(request, 'brand/signup.html')
        
        if User.objects.filter(username=email).exists():
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
        
        # Authenticate user (username is email in our case)
        user = authenticate(request, username=email, password=password)
        
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
            messages.error(request, 'Invalid email or password.')
            return render(request, 'brand/login.html', {'next': next_url})
    
    next_url = request.GET.get('next', '/')
    return render(request, 'brand/login.html', {'next': next_url})

def logout_view(request):
    """User logout view"""
    from django.contrib.auth import logout
    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('index')
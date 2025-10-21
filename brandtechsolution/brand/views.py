from django.shortcuts import render

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
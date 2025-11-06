from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .models import BlogPost, Project, Event
from .serializers import BlogPostSerializer, ProjectSerializer, EventSerializer

@method_decorator(csrf_exempt, name='dispatch')
class BlogPostViewSet(viewsets.ModelViewSet):
    queryset = BlogPost.objects.all().order_by('-updated_at')
    serializer_class = BlogPostSerializer
    
    @action(detail=True, methods=['post'])
    def increment_view(self, request, pk=None):
        post = get_object_or_404(BlogPost, pk=pk)
        post.view_count += 1
        post.save()
        return Response({'view_count': post.view_count})

@method_decorator(csrf_exempt, name='dispatch')
class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.all()
    serializer_class = ProjectSerializer

@method_decorator(csrf_exempt, name='dispatch')
class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

@api_view(['GET'])
def blog_posts_api(request):
    posts = BlogPost.objects.all().order_by('-updated_at')
    serializer = BlogPostSerializer(posts, many=True)
    return Response(serializer.data)

@csrf_exempt
def admin_panel(request):
    return render(request, 'admin_panel.html')
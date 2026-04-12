from rest_framework import viewsets
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from .models import BlogPost, Project, Event
from .serializers import BlogPostSerializer, ProjectSerializer, EventSerializer

@method_decorator(csrf_exempt, name='dispatch')
class BlogPostViewSet(viewsets.ModelViewSet):
    # Optimize queryset by selecting only frequently accessed fields
    queryset = BlogPost.objects.all().order_by('-updated_at').only(
        'id', 'title', 'excerpt', 'content', 'image', 'tags', 
        'category', 'featured', 'view_count', 'created_at', 'updated_at'
    )
    serializer_class = BlogPostSerializer
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    
    @action(detail=True, methods=['post'])
    def increment_view(self, request, pk=None):
        post = get_object_or_404(BlogPost, pk=pk)
        post.view_count += 1
        post.save(update_fields=['view_count'])
        return Response({'view_count': post.view_count})

@method_decorator(csrf_exempt, name='dispatch')
class ProjectViewSet(viewsets.ModelViewSet):
    # Optimize queryset by selecting only frequently accessed fields
    queryset = Project.objects.all().only(
        'id', 'title', 'short_description', 'description', 
        'project_url', 'github_url', 'image', 'featured', 'created_at', 'updated_at'
    )
    serializer_class = ProjectSerializer
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

@method_decorator(csrf_exempt, name='dispatch')
class EventViewSet(viewsets.ModelViewSet):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

@api_view(['GET'])
def blog_posts_api(request):
    # Optimize by selecting only required fields
    posts = BlogPost.objects.all().order_by('-updated_at').only(
        'id', 'title', 'excerpt', 'content', 'image', 'tags', 
        'category', 'featured', 'view_count', 'created_at', 'updated_at'
    )
    serializer = BlogPostSerializer(posts, many=True, context={'request': request})
    return Response(serializer.data)



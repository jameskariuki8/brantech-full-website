from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import BlogPost
from .serializers import BlogPostSerializer


@api_view(['GET'])
def blog_posts_api(request):
    # Optimize by selecting only required fields
    posts = BlogPost.objects.all().order_by('-updated_at').only(
        'id', 'title', 'excerpt', 'content', 'image', 'tags',
        'category', 'featured', 'view_count', 'created_at', 'updated_at'
    )
    serializer = BlogPostSerializer(posts, many=True, context={'request': request})
    return Response(serializer.data)

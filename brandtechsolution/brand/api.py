
from rest_framework import viewsets
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from .models import BlogPost
from .serializers import BlogPostSerializer


@api_view(['GET'])
def blog_posts_api(request):
    # Optimize by selecting only required fields
    posts = BlogPost.objects.filter(status='published').order_by('-updated_at').only(
        'id', 'title', 'excerpt', 'content', 'image', 'tags',
        'category', 'featured', 'view_count', 'created_at', 'updated_at'
    )
    serializer = BlogPostSerializer(posts, many=True, context={'request': request})
    return Response(serializer.data)




@api_view(['GET'])
@permission_classes([IsAdminUser])
def dashboard_stats(request):
    from appointments.models import Appointment
    from messaging.models import Inquiry, EmailTemplate, Campaign
    from brand.models import BlogPost, Project, Event, BlogLike, BlogComment
    from django.db.models import Sum

    total_blogs = BlogPost.objects.count()
    total_projects = Project.objects.count()
    total_events = Event.objects.count()
    total_templates = EmailTemplate.objects.count()
    total_campaigns = Campaign.objects.count()
    total_inquiries = Inquiry.objects.count()
    total_appointments = Appointment.objects.count()
    total_likes = BlogLike.objects.count()
    total_comments = BlogComment.objects.count()
    
    total_blog_views = BlogPost.objects.aggregate(total_views=Sum('view_count'))['total_views'] or 0

    # Top performing blogs by view count
    top_blogs = BlogPost.objects.order_by('-view_count')[:5]
    top_blogs_data = [
        {'title': post.title[:30] + '...' if len(post.title) > 30 else post.title, 'views': post.view_count}
        for post in top_blogs
    ]

    # Appointments by status
    appointment_stats = {}
    for status, label in Appointment.APPOINTMENT_STATUS_CHOICES:
        appointment_stats[status] = Appointment.objects.filter(status=status).count()

    # Inquiries by status
    inquiry_stats = {}
    for status in ['new', 'read', 'replied', 'archived']:
        inquiry_stats[status] = Inquiry.objects.filter(status=status).count()

    # Campaigns by status
    campaign_stats = {}
    for status in ['draft', 'queued', 'sending', 'sent', 'paused', 'failed']:
        campaign_stats[status] = Campaign.objects.filter(status=status).count()

    return Response({
        'metrics': {
            'total_blogs': total_blogs,
            'total_projects': total_projects,
            'total_events': total_events,
            'total_templates': total_templates,
            'total_campaigns': total_campaigns,
            'total_inquiries': total_inquiries,
            'total_appointments': total_appointments,
            'total_blog_views': total_blog_views,
            'total_likes': total_likes,
            'total_comments': total_comments,
        },
        'charts': {
            'top_blogs': top_blogs_data,
            'appointments': appointment_stats,
            'inquiries': inquiry_stats,
            'campaigns': campaign_stats,
        }
    })




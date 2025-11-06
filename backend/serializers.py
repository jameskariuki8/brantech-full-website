from rest_framework import serializers
from .models import BlogPost, Project, Event

class BlogPostSerializer(serializers.ModelSerializer):
    tags_list = serializers.SerializerMethodField()
    tags = serializers.CharField(required=False, allow_blank=True, default='')
    category = serializers.CharField(required=False, allow_blank=True, default='General')
    
    class Meta:
        model = BlogPost
        fields = ['id', 'title', 'excerpt', 'content', 'image', 'tags', 'tags_list', 
                 'category', 'featured', 'view_count', 'created_at', 'updated_at']
    
    def get_tags_list(self, obj):
        return obj.get_tags_list()

class ProjectSerializer(serializers.ModelSerializer):
    technologies_list = serializers.SerializerMethodField()
    
    class Meta:
        model = Project
        fields = ['id', 'title', 'description', 'client', 'status', 'start_date', 'end_date',
                 'budget', 'technologies', 'technologies_list', 'project_url', 'image', 'featured', 
                 'created_at', 'updated_at']
    
    def get_technologies_list(self, obj):
        return obj.get_technologies_list()

class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = ['id', 'title', 'description', 'event_type', 'date', 'location', 
                 'is_online', 'registration_link', 'max_attendees', 'image', 'featured',
                 'created_at', 'updated_at']
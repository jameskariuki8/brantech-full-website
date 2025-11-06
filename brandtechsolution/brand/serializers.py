from rest_framework import serializers
from django.conf import settings
from .models import BlogPost, Project, Event

class BlogPostSerializer(serializers.ModelSerializer):
    tags_list = serializers.SerializerMethodField()
    tags = serializers.CharField(required=False, allow_blank=True, default='')
    category = serializers.CharField(required=False, allow_blank=True, default='General')
    image = serializers.SerializerMethodField()
    
    class Meta:
        model = BlogPost
        fields = ['id', 'title', 'excerpt', 'content', 'image', 'tags', 'tags_list', 
                 'category', 'featured', 'view_count', 'created_at', 'updated_at']
    
    def get_tags_list(self, obj):
        return obj.get_tags_list()
    
    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

class ProjectSerializer(serializers.ModelSerializer):
    technologies_list = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    
    class Meta:
        model = Project
        fields = ['id', 'title', 'description', 'client', 'status', 'start_date', 'end_date',
                 'budget', 'technologies', 'technologies_list', 'project_url', 'github_url', 'image', 'featured', 
                 'created_at', 'updated_at']
    
    def get_technologies_list(self, obj):
        return obj.get_technologies_list()
    
    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None

class EventSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()
    
    class Meta:
        model = Event
        fields = ['id', 'title', 'description', 'event_type', 'date', 'location', 
                 'is_online', 'registration_link', 'max_attendees', 'image', 'featured',
                 'created_at', 'updated_at']
    
    def get_image(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return None



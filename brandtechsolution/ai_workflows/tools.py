"""
RAG tools for retrieving blog posts and projects using pgvector and Django ORM.
"""
from langchain.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from django.contrib.auth.models import User
from brandtechsolution.config import config
from brand.models import BlogPost, Project
from pgvector.django import L2Distance
import logging

logger = logging.getLogger(__name__)


# Singleton embedding instance
_embeddings = None


def get_embeddings():
    """Get or create embeddings instance using HuggingFace sentence-transformers (free, local)."""
    global _embeddings
    if _embeddings is None:
        # all-mpnet-base-v2 produces 768-dimensional vectors (matches our VectorField)
        # Runs locally - no API costs or rate limits
        _embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-mpnet-base-v2"
        )
    return _embeddings


class BlogRetrieverTool:
    """Tool for retrieving relevant blog posts using pgvector."""
    
    def __init__(self):
        self.embeddings = get_embeddings()
    
    def search(self, query: str, k: int = 3) -> str:
        """Search blog posts and return relevant content using vector similarity."""
        try:
            # Generate embedding for the query
            query_embedding = self.embeddings.embed_query(query)
            
            # Query Django ORM using L2Distance for vector similarity
            # Only search posts that have embeddings
            results = (
                BlogPost.objects
                .exclude(embedding__isnull=True)
                .order_by(L2Distance('embedding', query_embedding))[:k]
            )
            
            if not results:
                return "No relevant blog posts found. The blog posts may not have been indexed yet."
            
            output = []
            for post in results:
                content_preview = post.content[:500]
                output.append(f"Title: {post.title}\nCategory: {post.category}\n{content_preview}...")
            
            return "\n\n---\n\n".join(output)
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error searching blog posts: {error_str}", exc_info=True)
            
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str or "quota" in error_str.lower():
                return "I'm currently unable to search blog posts due to API rate limits. Please try again in a moment."
            elif "embed" in error_str.lower() or "embedding" in error_str.lower():
                return "I'm having trouble accessing the blog post search feature at the moment. Please try again later."
            else:
                return "I encountered an issue searching blog posts. Please try again or ask about something else."


class ProjectRetrieverTool:
    """Tool for retrieving relevant projects using pgvector."""
    
    def __init__(self):
        self.embeddings = get_embeddings()
    
    def search(self, query: str, k: int = 3) -> str:
        """Search projects and return relevant content using vector similarity."""
        try:
            # Generate embedding for the query
            query_embedding = self.embeddings.embed_query(query)
            
            # Query Django ORM using L2Distance for vector similarity
            # Only search projects that have embeddings
            results = (
                Project.objects
                .exclude(embedding__isnull=True)
                .order_by(L2Distance('embedding', query_embedding))[:k]
            )
            
            if not results:
                return "No relevant projects found. The projects may not have been indexed yet."
            
            output = []
            for project in results:
                content_preview = project.description[:500]
                output.append(f"Project: {project.title}\n{content_preview}...")
            
            return "\n\n---\n\n".join(output)
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error searching projects: {error_str}", exc_info=True)
            
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str or "quota" in error_str.lower():
                return "I'm currently unable to search projects due to API rate limits. Please try again in a moment."
            elif "embed" in error_str.lower() or "embedding" in error_str.lower():
                return "I'm having trouble accessing the project search feature at the moment. Please try again later."
            else:
                return "I encountered an issue searching projects. Please try again or ask about something else."


# Singleton instances
_blog_retriever = None
_project_retriever = None


def get_blog_retriever():
    """Get or create blog retriever instance."""
    global _blog_retriever
    if _blog_retriever is None:
        _blog_retriever = BlogRetrieverTool()
    return _blog_retriever


def get_project_retriever():
    """Get or create project retriever instance."""
    global _project_retriever
    if _project_retriever is None:
        _project_retriever = ProjectRetrieverTool()
    return _project_retriever


@tool
def search_blog_posts(query: str) -> str:
    """Search blog posts for information about services, technologies, or topics.
    
    Use this when users ask about blog content, articles, or written resources.
    
    Args:
        query: The search query to find relevant blog posts
    """
    blog_tool = get_blog_retriever()
    return blog_tool.search(query)


@tool
def search_projects(query: str) -> str:
    """Search completed projects for information about work done, technologies used, or client projects.
    
    Use this when users ask about past work or project examples.
    
    Args:
        query: The search query to find relevant projects
    """
    project_tool = get_project_retriever()
    return project_tool.search(query)


def create_user_info_tool(user_id: int):
    """
    Create a tool to get user's basic information from the database.
    
    Args:
        user_id: The user ID to fetch information for
        
    Returns:
        A LangChain tool bound to this user_id
    """
    @tool
    def get_user_info() -> str:
        """Get the current user's basic information from the database.
        
        Use this when you need to know the user's name, email, or other account details.
        This tool automatically uses the logged-in user's information.
        
        Returns:
            String containing user's basic information
        """
        try:
            user = User.objects.get(pk=user_id)
            
            info_parts = [
                f"Username: {user.username}",
                f"Email: {user.email}",
            ]
            
            # Add first/last name if available
            if user.first_name:
                info_parts.append(f"First Name: {user.first_name}")
            if user.last_name:
                info_parts.append(f"Last Name: {user.last_name}")
            
            # Add full name if both are available
            if user.first_name and user.last_name:
                info_parts.append(f"Full Name: {user.get_full_name()}")
            
            # Add date joined
            if user.date_joined:
                info_parts.append(f"Member Since: {user.date_joined.strftime('%Y-%m-%d')}")
            
            # Add active status
            info_parts.append(f"Account Active: {'Yes' if user.is_active else 'No'}")
            
            return "\n".join(info_parts)
            
        except User.DoesNotExist:
            return f"User with ID {user_id} not found."
        except Exception as e:
            logger.error(f"Error fetching user info: {e}", exc_info=True)
            return f"Error retrieving user information: {str(e)}"
    
    # Update the tool name to be more descriptive
    get_user_info.name = "get_user_info"
    get_user_info.description = "Get the current logged-in user's basic information (name, email, account details). Use this when you need to personalize responses or reference the user's account."
    
    return get_user_info


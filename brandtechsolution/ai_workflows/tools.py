"""
RAG tools for retrieving blog posts and projects
"""
from langchain.tools import tool
from langchain_chroma import Chroma
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from django.contrib.auth.models import User
from brandtechsolution.config import config
import logging

logger = logging.getLogger(__name__)


class BlogRetrieverTool:
    """Tool for retrieving relevant blog posts"""
    
    def __init__(self):
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=config.gemini_embedding_model,
            google_api_key=config.google_api_key
        )
        self.vectorstore = self._load_existing_vectorstore()
    
    def _load_existing_vectorstore(self):
        """Load prebuilt vector store; create empty collection if missing."""
        try:
            return Chroma(
                collection_name="blog_posts",
                embedding_function=self.embeddings,
                persist_directory=config.chroma_persist_directory
            )
        except Exception as e:
            logger.warning("Blog vectorstore load failed: %s", e)
            return None
    
    def search(self, query: str) -> str:
        """Search blog posts and return relevant content"""
        if not self.vectorstore:
            self.vectorstore = self._load_existing_vectorstore()
        if not self.vectorstore:
            return "No blog posts available. Try initializing vector stores."
        
        try:
            docs = self.vectorstore.similarity_search(query, k=3)
            
            results = []
            for doc in docs:
                title = doc.metadata.get('title', 'Unknown')
                content = doc.page_content[:500]
                results.append(f"Title: {title}\n{content}...")
            
            return "\n\n---\n\n".join(results) if results else "No relevant blog posts found."
        except Exception as e:
            error_str = str(e)
            # Log full error for debugging
            logger.error(f"Error searching blog posts: {error_str}", exc_info=True)
            
            # Return user-friendly error message without exposing full error details
            if "RESOURCE_EXHAUSTED" in error_str or "429" in error_str or "quota" in error_str.lower():
                return "I'm currently unable to search blog posts due to API rate limits. Please try again in a moment."
            elif "embed" in error_str.lower() or "embedding" in error_str.lower():
                return "I'm having trouble accessing the blog post search feature at the moment. Please try again later."
            else:
                return "I encountered an issue searching blog posts. Please try again or ask about something else."


class ProjectRetrieverTool:
    """Tool for retrieving relevant projects"""
    
    def __init__(self):
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=config.gemini_embedding_model,
            google_api_key=config.google_api_key
        )
        self.vectorstore = self._load_existing_vectorstore()
    
    def _load_existing_vectorstore(self):
        """Load prebuilt vector store; create empty collection if missing."""
        try:
            return Chroma(
                collection_name="projects",
                embedding_function=self.embeddings,
                persist_directory=config.chroma_persist_directory
            )
        except Exception as e:
            logger.warning("Project vectorstore load failed: %s", e)
            return None
    
    def search(self, query: str) -> str:
        """Search projects and return relevant content"""
        if not self.vectorstore:
            self.vectorstore = self._load_existing_vectorstore()
        if not self.vectorstore:
            return "No projects available. Try initializing vector stores."
        
        try:
            docs = self.vectorstore.similarity_search(query, k=3)
            
            results = []
            for doc in docs:
                title = doc.metadata.get('title', 'Unknown')
                content = doc.page_content[:500]
                results.append(f"Project: {title}\n{content}...")
            
            return "\n\n---\n\n".join(results) if results else "No relevant projects found."
        except Exception as e:
            error_str = str(e)
            # Log full error for debugging
            logger.error(f"Error searching projects: {error_str}", exc_info=True)
            
            # Return user-friendly error message without exposing full error details
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
    """Get or create blog retriever instance"""
    global _blog_retriever
    if _blog_retriever is None:
        _blog_retriever = BlogRetrieverTool()
    return _blog_retriever


def get_project_retriever():
    """Get or create project retriever instance"""
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


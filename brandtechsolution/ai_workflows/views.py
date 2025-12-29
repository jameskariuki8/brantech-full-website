from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from django.conf import settings
from .service import get_chatbot_response, ChatAssistant
from .models import ConversationThread, ConversationCheckpoint
import uuid
import json
import traceback
import logging

logger = logging.getLogger(__name__)


@ensure_csrf_cookie
@require_http_methods(["POST"])
def chat_endpoint(request):
    """Chatbot endpoint using Django sessions"""
    
    try:
        data = json.loads(request.body)
        message = data.get('message')
        
        logger.info(f"[chat_endpoint] Received message request")
        logger.debug(f"[chat_endpoint] Message: {message[:100] if message else 'None'}...")
        
        if not message:
            logger.warning("[chat_endpoint] No message provided")
            return JsonResponse(
                {"error": "Message is required"},
                status=400
            )
        
        user = request.user
        is_authenticated = user.is_authenticated
        logger.debug(f"[chat_endpoint] User authenticated: {is_authenticated}, user_id: {user.id if is_authenticated else 'None'}")
        
        # Get or create thread_id
        if is_authenticated:
            # For logged-in users, use database
            thread_id = data.get('thread_id')
            if thread_id:
                # Check if thread exists and is linked to this user
                try:
                    thread = ConversationThread.objects.get(thread_id=thread_id)
                    # If thread exists but isn't linked to this user, link it
                    if thread.user != user:
                        thread.user = user
                        thread.save()
                except ConversationThread.DoesNotExist:
                    # Thread doesn't exist, create it and link to user
                    thread = ConversationThread.objects.create(
                        thread_id=thread_id,
                        user=user,
                        workflow_type='chatbot'
                    )
            else:
                # No thread_id provided, create or get existing thread for user
                thread, created = ConversationThread.objects.get_or_create(
                    user=user,
                    workflow_type='chatbot',
                    defaults={'thread_id': f"user_{user.id}_{uuid.uuid4().hex[:8]}"}
                )
                thread_id = thread.thread_id
        else:
            # For anonymous users, use session
            if 'chat_thread_id' not in request.session:
                request.session['chat_thread_id'] = f"anon_{uuid.uuid4().hex[:12]}"
            thread_id = request.session['chat_thread_id']
        
        logger.info(f"[chat_endpoint] Using thread_id={thread_id}")
        
        # Get chatbot response
        result = get_chatbot_response(
            message=message,
            thread_id=thread_id,
            user_id=user.id if is_authenticated else None,
        )
        
        logger.info(f"[chat_endpoint] Response generated successfully")
        
        # Store in session for anonymous users (for history)
        if not is_authenticated:
            if 'chat_messages' not in request.session:
                request.session['chat_messages'] = []
            request.session['chat_messages'].append({
                'role': 'user',
                'content': message,
            })
            request.session['chat_messages'].append({
                'role': 'assistant',
                'content': result['response'],
            })
            # Keep only last 20 messages in session
            if len(request.session['chat_messages']) > 20:
                request.session['chat_messages'] = request.session['chat_messages'][-20:]
            request.session.modified = True
        
        return JsonResponse({
            "response": result['response'],
            "thread_id": thread_id,
        })
        
    except Exception as e:
        # Log the full traceback for debugging
        error_traceback = traceback.format_exc()
        logger.error(f"[chat_endpoint] Error: {str(e)}\n{error_traceback}")
        
        return JsonResponse(
            {
                "error": str(e),
                "traceback": error_traceback if settings.DEBUG else None
            },
            status=500
        )


@ensure_csrf_cookie
@require_http_methods(["GET"])
def chat_history(request):
    """Get conversation history"""
    
    logger.info(f"[chat_history] Getting conversation history")
    
    user = request.user
    is_authenticated = user.is_authenticated
    thread_id = None

    if is_authenticated:
        thread_id = request.GET.get('thread_id')
        if thread_id:
            # Check if thread exists and is linked to this user
            try:
                thread = ConversationThread.objects.get(thread_id=thread_id)
                # If thread exists but isn't linked to this user, link it
                if thread.user != user:
                    thread.user = user
                    thread.save()
            except ConversationThread.DoesNotExist:
                # Thread doesn't exist, create it and link to user
                thread = ConversationThread.objects.create(
                    thread_id=thread_id,
                    user=user,
                    workflow_type='chatbot'
                )
        else:
            # Try to find the most recent thread for the user
            thread = ConversationThread.objects.filter(
                user=user,
                workflow_type='chatbot'
            ).order_by('-updated_at').first()
            
            if thread:
                thread_id = thread.thread_id
            else:
                # If no thread exists, generate a new ID
                thread_id = f"user_{user.id}_{uuid.uuid4().hex[:8]}"
    else:
        # For anonymous users, get from request or session
        thread_id = request.GET.get('thread_id')
        if not thread_id:
            if 'chat_thread_id' not in request.session:
                request.session['chat_thread_id'] = f"anon_{uuid.uuid4().hex[:12]}"
                request.session.modified = True
            thread_id = request.session['chat_thread_id']

    logger.info(f"[chat_history] Using thread_id={thread_id}")
    
    # Use ChatAssistant to retrieve history consistently
    assistant = ChatAssistant(
        thread_id=thread_id,
        user_id=user.id if is_authenticated else None
    )
    history = assistant.get_history()
    
    logger.info(f"[chat_history] Returning {len(history)} messages")
    
    return JsonResponse({
        "thread_id": thread_id,
        "messages": history,
    })
    
    # if is_authenticated:
    #     # Get from database
    #     thread_id = request.GET.get('thread_id')
    #     if not thread_id:
    #         # Get user's most recent thread
    #         thread = ConversationThread.objects.filter(
    #             user=user,
    #             workflow_type='chatbot'
    #         ).order_by('-updated_at').first()
            
    #         if not thread:
    #             # Create a new thread for the user
    #             thread = ConversationThread.objects.create(
    #                 user=user,
    #                 workflow_type='chatbot',
    #                 thread_id=f"user_{user.id}_{uuid.uuid4().hex[:8]}"
    #             )
    #         thread_id = thread.thread_id
        
    #     try:
    #         thread = ConversationThread.objects.get(
    #             thread_id=thread_id,
    #             user=user
    #         )
            
    #         checkpoints = ConversationCheckpoint.objects.filter(
    #             thread=thread
    #         ).order_by('created_at')
            
    #         messages = []
    #         for checkpoint in checkpoints:
    #             state = checkpoint.state
    #             if "messages" in state:
    #                 for msg in state["messages"]:
    #                     if isinstance(msg, dict):
    #                         role = msg.get("role", msg.get("type", "unknown"))
    #                         content = msg.get("content", msg.get("text", ""))
    #                         if isinstance(content, list):
    #                             text_parts = []
    #                             for part in content:
    #                                 if isinstance(part, dict) and "text" in part:
    #                                     text_parts.append(part["text"])
    #                                 elif isinstance(part, str):
    #                                     text_parts.append(part)
    #                             content = "\n".join(text_parts) if text_parts else str(content)
                            
    #                         if role in ['user', 'assistant', 'human', 'ai']:
    #                             messages.append({
    #                                 "role": "user" if role in ['user', 'human'] else "assistant",
    #                                 "content": content,
    #                                 "timestamp": checkpoint.created_at.isoformat(),
    #                             })
            
    #         return JsonResponse({
    #             "thread_id": thread_id,
    #             "messages": messages,
    #         })
            
    #     except ConversationThread.DoesNotExist:
    #         return JsonResponse({
    #             "thread_id": thread_id,
    #             "messages": []
    #         })
    # else:
    #     # Get from session - create if doesn't exist
    #     if 'chat_thread_id' not in request.session:
    #         request.session['chat_thread_id'] = f"anon_{uuid.uuid4().hex[:12]}"
    #         request.session.modified = True
    #     thread_id = request.session['chat_thread_id']
    #     messages = request.session.get('chat_messages', [])
        
    #     return JsonResponse({
    #         "thread_id": thread_id,
    #         "messages": messages,
    #     })


@ensure_csrf_cookie
@require_http_methods(["POST"])
def clear_chat_history(request):
    """Clear conversation history"""
    
    user = request.user
    is_authenticated = user.is_authenticated
    
    if is_authenticated:
        thread_id = json.loads(request.body).get('thread_id')
        if thread_id:
            try:
                thread = ConversationThread.objects.get(
                    thread_id=thread_id,
                    user=user
                )
                thread.delete()
                return JsonResponse({"success": True})
            except ConversationThread.DoesNotExist:
                return JsonResponse({"error": "Thread not found"}, status=404)
        else:
            # Delete all user's threads
            ConversationThread.objects.filter(
                user=user,
                workflow_type='chatbot'
            ).delete()
            return JsonResponse({"success": True})
    else:
        # Clear session
        if 'chat_thread_id' in request.session:
            del request.session['chat_thread_id']
        if 'chat_messages' in request.session:
            del request.session['chat_messages']
        request.session.modified = True
        return JsonResponse({"success": True})

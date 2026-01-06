from typing import Optional, Dict, Any, List, Sequence, Tuple
from collections import ChainMap
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
from django.db import transaction
from django.utils import timezone
from asgiref.sync import sync_to_async
from .models import ConversationThread, ConversationCheckpoint
import uuid
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


class DjangoCheckpointer(BaseCheckpointSaver):
    """
    Custom Django checkpointer implementing LangGraph's BaseCheckpointSaver interface.
    Stores checkpoint data in Django models for persistence and querying.
    """
    
    def __init__(self, thread_id: str):
        super().__init__()
        # required default thread_id (used if config doesn't provide one)
        self.thread_id = thread_id
        logger.debug(f"[DjangoCheckpointer] Initialized with thread_id={thread_id}")
    
    def _to_jsonable(self, obj: Any) -> Any:
        """Convert common LangGraph/Django objects (e.g., ChainMap) to JSON-safe structures."""
        # Handle LangChain message objects first
        if isinstance(obj, BaseMessage):
            # Determine message type
            if isinstance(obj, HumanMessage):
                msg_type = "human"
            elif isinstance(obj, AIMessage):
                msg_type = "ai"
            elif isinstance(obj, SystemMessage):
                msg_type = "system"
            elif isinstance(obj, ToolMessage):
                msg_type = "tool"
            else:
                msg_type = getattr(obj, "type", "unknown")
            
            # Extract content - handle list content (Gemini format)
            content = obj.content
            if isinstance(content, list):
                # Extract text from list of dicts
                text_parts = []
                for part in content:
                    if isinstance(part, dict) and "text" in part:
                        text_parts.append(part["text"])
                    elif isinstance(part, str):
                        text_parts.append(part)
                content = "\n".join(text_parts) if text_parts else str(content)
            
            serialized = {
                "type": msg_type,
                "content": content,
                "id": getattr(obj, "id", None),
                "name": getattr(obj, "name", None),
            }
            
            # Serialize additional fields based on message type
            if isinstance(obj, ToolMessage):
                serialized["tool_call_id"] = obj.tool_call_id
                if obj.artifact:
                    serialized["artifact"] = self._to_jsonable(obj.artifact)
            
            elif isinstance(obj, AIMessage):
                if obj.tool_calls:
                    serialized["tool_calls"] = self._to_jsonable(obj.tool_calls)
                if obj.usage_metadata:
                    serialized["usage_metadata"] = self._to_jsonable(obj.usage_metadata)
            
            # Include additional_kwargs if present
            if obj.additional_kwargs:
                serialized["additional_kwargs"] = self._to_jsonable(obj.additional_kwargs)
            
            return serialized
        
        if isinstance(obj, ChainMap):
            return self._to_jsonable(dict(obj))
        if isinstance(obj, dict):
            return {k: self._to_jsonable(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [self._to_jsonable(v) for v in obj]
        if isinstance(obj, datetime):
            return obj.isoformat()
        try:
            json.dumps(obj)
            return obj
        except TypeError:
            return str(obj)

    def _sanitize_checkpoint_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure checkpoint state is valid for LangGraph, patching legacy data if needed."""
        if not isinstance(state, dict):
            return state
            
        channel_values = state.get("channel_values", {})
        if not channel_values:
            return state
            
        messages = channel_values.get("messages", [])
        if not messages:
            return state
            
        sanitized_messages = []
        modified = False
        for msg in messages:
            if isinstance(msg, dict):
                # Fix ToolMessages missing tool_call_id
                if msg.get("type") == "tool" and "tool_call_id" not in msg:
                    # Don't log on every access to avoid spam, but patch it
                    msg_copy = msg.copy()
                    msg_copy["tool_call_id"] = "legacy_missing_id"
                    sanitized_messages.append(msg_copy)
                    modified = True
                    continue
            sanitized_messages.append(msg)
            
        if modified:
            # Create a shallow copy structure to return modified state
            new_state = state.copy()
            new_state["channel_values"] = channel_values.copy()
            new_state["channel_values"]["messages"] = sanitized_messages
            return new_state
            
        return state

    def _extract_checkpoint_id(self, checkpoint: Any, config: Dict[str, Any]) -> str:
        """Get a checkpoint id from checkpoint/config, or generate one."""
        if isinstance(checkpoint, dict) and (checkpoint.get("id") or checkpoint.get("checkpoint_id")):
            return checkpoint.get("id") or checkpoint.get("checkpoint_id")
        if hasattr(checkpoint, "get"):
            cid = checkpoint.get("id") or checkpoint.get("checkpoint_id")
            if cid:
                return cid
        cid = config.get("configurable", {}).get("checkpoint_id")
        return cid or str(uuid.uuid4())

    def _get_version(self, checkpoint: Any) -> int:
        """Safely extract version from checkpoint."""
        if isinstance(checkpoint, dict):
            return checkpoint.get("version", 1)
        if hasattr(checkpoint, "get"):
            return checkpoint.get("version", 1)
        return 1

    def _get_thread_id(self, config: Dict[str, Any]) -> str:
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            raise ValueError("thread_id is required in config['configurable']")
        return thread_id

    def _get_user_id(self, config: Dict[str, Any]) -> Optional[int]:
        return config.get("user_id")

    def _get_workflow_type(self, config: Dict[str, Any]) -> str:
        return config.get("workflow_type", "chatbot")

    def _get_or_create_thread(self, config: Dict[str, Any]) -> ConversationThread:
        thread_id = self._get_thread_id(config)
        user_id = self._get_user_id(config)
        workflow_type = self._get_workflow_type(config)
        safe_metadata = self._to_jsonable(config.get("metadata", {}))

        thread, created = ConversationThread.objects.get_or_create(
            thread_id=thread_id,
            defaults={
                "user_id": user_id,
                "workflow_type": workflow_type,
                "metadata": safe_metadata,
            },
        )

        # Attach user if thread was anonymous and we now have one
        if not created and user_id and thread.user_id is None:
            thread.user_id = user_id
            thread.save(update_fields=["user_id"])

        # Merge metadata if provided
        if not created and config.get("metadata"):
            thread.metadata.update(safe_metadata)
            thread.save(update_fields=["metadata"])

        return thread
    
    @transaction.atomic
    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> CheckpointTuple:
        """
        Save a checkpoint to the database.
        
        Args:
            config: Configuration dict containing thread_id
            checkpoint: Checkpoint data to save
            metadata: Metadata associated with checkpoint
            new_versions: New version information
            
        Returns:
            CheckpointTuple with saved checkpoint data
        """
        thread_id = self._get_thread_id(config)
        logger.info(f"[DjangoCheckpointer] Saving checkpoint for thread_id={thread_id}")
        
        thread = self._get_or_create_thread(config)
        logger.debug(f"[DjangoCheckpointer] Thread: id={thread.id}, thread_id={thread.thread_id}, user_id={thread.user_id}")
        
        # Generate checkpoint ID
        checkpoint_id = self._extract_checkpoint_id(checkpoint, config)
        logger.debug(f"[DjangoCheckpointer] Checkpoint ID: {checkpoint_id}")
        
        # Get parent checkpoint if exists
        parent_checkpoint = None
        parent_id = checkpoint.get("parent_checkpoint_id")
        if parent_id:
            try:
                parent_checkpoint = ConversationCheckpoint.objects.get(
                    checkpoint_id=parent_id,
                    thread=thread
                )
                logger.debug(f"[DjangoCheckpointer] Found parent checkpoint: {parent_id}")
            except ConversationCheckpoint.DoesNotExist:
                logger.debug(f"[DjangoCheckpointer] Parent checkpoint {parent_id} not found")
        
        # Determine version
        version = self._get_version(checkpoint)
        if new_versions:
            version = max(new_versions.values()) if new_versions.values() else version
        logger.debug(f"[DjangoCheckpointer] Checkpoint version: {version}")
        
        # JSON-safe checkpoint and metadata
        safe_checkpoint_state = self._to_jsonable(checkpoint)
        safe_checkpoint_metadata = self._to_jsonable(metadata)
        
        # Log message count if available
        if isinstance(safe_checkpoint_state, dict):
            channel_values = safe_checkpoint_state.get("channel_values", {})
            messages = channel_values.get("messages", [])
            logger.info(f"[DjangoCheckpointer] Saving checkpoint with {len(messages)} messages")

        # Create checkpoint record
        checkpoint_obj, created = ConversationCheckpoint.objects.update_or_create(
            thread=thread,
            checkpoint_id=checkpoint_id,
            defaults={
                "parent_checkpoint": parent_checkpoint,
                "state": safe_checkpoint_state,
                "checkpoint_metadata": safe_checkpoint_metadata,
                "version": version,
            },
        )
        
        logger.info(f"[DjangoCheckpointer] Checkpoint {'created' if created else 'updated'}: id={checkpoint_obj.id}, checkpoint_id={checkpoint_id}")
        
        # Update thread updated_at
        thread.updated_at = timezone.now()
        thread.save()
        
        return CheckpointTuple(
            config=config,
            checkpoint={
                **safe_checkpoint_state,
                "id": checkpoint_id,
            },
            metadata=safe_checkpoint_metadata,
        )

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        Put writes to the checkpoint.
        
        Following WozapAuto pattern: just log writes for now.
        In a full implementation, you might want to store these writes.
        """
        try:
            logger.info(f"Put writes: {len(writes)} writes for task {task_id}")
        except Exception as e:
            logger.error(f"Error putting writes: {e}")
    
    def get(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        """
        Retrieve a checkpoint from the database.
        
        Args:
            config: Configuration dict containing thread_id and optionally checkpoint_id
            
        Returns:
            CheckpointTuple if found, None otherwise
        """
        return self.get_tuple(config)
    
    def get_tuple(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        """
        Retrieve a checkpoint tuple from the database.
        This is the method called by LangGraph internally.
        
        Args:
            config: Configuration dict containing thread_id and optionally checkpoint_id
            
        Returns:
            CheckpointTuple if found, None otherwise
        """
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        
        try:
            thread_id = self._get_thread_id(config)
            logger.debug(f"[DjangoCheckpointer] Getting checkpoint for thread_id={thread_id}, checkpoint_id={checkpoint_id}")
        except ValueError as e:
            logger.warning(f"[DjangoCheckpointer] No thread_id in config: {e}")
            return None
        
        try:
            thread = ConversationThread.objects.get(thread_id=thread_id)
            logger.debug(f"[DjangoCheckpointer] Found thread: id={thread.id}, user_id={thread.user_id}")
        except ConversationThread.DoesNotExist:
            logger.info(f"[DjangoCheckpointer] Thread not found: thread_id={thread_id}")
            return None
        
        # Get specific checkpoint or latest
        if checkpoint_id:
            try:
                checkpoint_obj = ConversationCheckpoint.objects.get(
                    thread=thread,
                    checkpoint_id=checkpoint_id
                )
                logger.debug(f"[DjangoCheckpointer] Found specific checkpoint: {checkpoint_id}")
            except ConversationCheckpoint.DoesNotExist:
                logger.info(f"[DjangoCheckpointer] Checkpoint not found: checkpoint_id={checkpoint_id}")
                return None
        else:
            checkpoint_obj = ConversationCheckpoint.objects.filter(
                thread=thread
            ).order_by('-created_at').first()
            
            if not checkpoint_obj:
                logger.info(f"[DjangoCheckpointer] No checkpoints found for thread_id={thread_id}")
                return None
            logger.debug(f"[DjangoCheckpointer] Found latest checkpoint: {checkpoint_obj.checkpoint_id}")
        
        # Log message count if available
        if isinstance(checkpoint_obj.state, dict):
            channel_values = checkpoint_obj.state.get("channel_values", {})
            messages = channel_values.get("messages", [])
            logger.info(f"[DjangoCheckpointer] Retrieved checkpoint with {len(messages)} messages")
        
        # Sanitize state to ensure compatibility (e.g., missing tool_call_id)
        sanitized_state = self._sanitize_checkpoint_state(checkpoint_obj.state)

        return CheckpointTuple(
            config=config,
            checkpoint={
                **sanitized_state,
                "id": checkpoint_obj.checkpoint_id,
            },
            metadata=checkpoint_obj.checkpoint_metadata,
        )
    
    def list(
        self,
        config: Dict[str, Any],
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[CheckpointTuple]:
        """
        List checkpoints for a thread.
        
        Args:
            config: Configuration dict containing thread_id
            filter: Optional filter dict
            before: Optional timestamp to filter checkpoints before this time
            limit: Optional limit on number of checkpoints
            
        Returns:
            List of CheckpointTuple objects
        """
        try:
            thread_id = self._get_thread_id(config)
        except ValueError:
            return []
        
        try:
            thread = ConversationThread.objects.get(thread_id=thread_id)
        except ConversationThread.DoesNotExist:
            return []
        
        queryset = ConversationCheckpoint.objects.filter(thread=thread)
        
        # Apply filters
        if before:
            try:
                before_dt = datetime.fromisoformat(before.replace('Z', '+00:00'))
                queryset = queryset.filter(created_at__lt=before_dt)
            except ValueError:
                pass
        
        # Apply custom filters
        if filter:
            # Example: filter by version
            if "version" in filter:
                queryset = queryset.filter(version=filter["version"])
        
        # Order by creation time
        queryset = queryset.order_by('-created_at')
        
        # Apply limit
        if limit:
            queryset = queryset[:limit]
        
        # Convert to CheckpointTuple list
        checkpoints = []
        for checkpoint_obj in queryset:
            # Sanitize state
            sanitized_state = self._sanitize_checkpoint_state(checkpoint_obj.state)
            
            checkpoints.append(
                CheckpointTuple(
                    config=config,
                    checkpoint={
                        **sanitized_state,
                        "id": checkpoint_obj.checkpoint_id,
                    },
                    metadata=checkpoint_obj.checkpoint_metadata,
                )
            )
        
        return checkpoints

    #
    # Async wrappers
    #

    async def aput(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> CheckpointTuple:
        return await sync_to_async(self.put)(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return await sync_to_async(self.put_writes)(config, writes, task_id, task_path)

    async def aget_tuple(self, config: Dict[str, Any]) -> Optional[CheckpointTuple]:
        return await sync_to_async(self.get_tuple)(config)

    async def alist(
        self,
        config: Dict[str, Any],
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[CheckpointTuple]:
        return await sync_to_async(self.list)(config, filter, before, limit)


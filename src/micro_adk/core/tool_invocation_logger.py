"""Tool Invocation Logger Plugin - Intercepts and logs all tool calls.

This module provides an ADK plugin that logs all tool invocations
to the PostgreSQL database for observability and debugging.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

if TYPE_CHECKING:
    from micro_adk.core.postgres_session_service import PostgresSessionService

logger = logging.getLogger(__name__)


class ToolInvocationLoggerPlugin(BasePlugin):
    """ADK Plugin that logs all tool invocations to the database.
    
    This plugin implements the before_tool_callback and after_tool_callback
    to track all tool invocations, their arguments, results, and timing.
    
    Example:
        ```python
        session_service = PostgresSessionService(db_url)
        logger_plugin = ToolInvocationLoggerPlugin(session_service)
        
        agent = LlmAgent(
            name="my_agent",
            model=LiteLlm(model="gemini/gemini-2.0-flash"),
            tools=[...],
            plugins=[logger_plugin],
        )
        ```
    """
    
    def __init__(
        self,
        session_service: "PostgresSessionService",
        *,
        log_args: bool = True,
        log_results: bool = True,
        on_invocation_start: Optional[Callable[[str, str, Dict], None]] = None,
        on_invocation_end: Optional[Callable[[str, str, Any, Optional[str]], None]] = None,
    ):
        """Initialize the tool invocation logger plugin.
        
        Args:
            session_service: The PostgreSQL session service for logging.
            log_args: Whether to log tool arguments.
            log_results: Whether to log tool results.
            on_invocation_start: Optional callback when invocation starts.
            on_invocation_end: Optional callback when invocation ends.
        """
        super().__init__(name="tool_invocation_logger")
        self._session_service = session_service
        self._log_args = log_args
        self._log_results = log_results
        self._on_invocation_start = on_invocation_start
        self._on_invocation_end = on_invocation_end
        
        # Track in-flight invocations: function_call_id -> (record_id, start_time)
        self._pending: Dict[str, tuple[uuid.UUID, float]] = {}
    
    def _get_tool_id(self, tool: BaseTool) -> str:
        """Get the tool ID from a tool instance."""
        # Check if it's a ContainerTool with a tool_id
        if hasattr(tool, "tool_id"):
            return tool.tool_id
        # Fall back to the tool name
        return tool.name
    
    async def before_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: Dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[Dict]:
        """Callback invoked before a tool is executed.
        
        This method logs the start of a tool invocation.
        
        Args:
            tool: The tool being invoked.
            tool_args: The arguments passed to the tool.
            tool_context: The tool context.
            
        Returns:
            None to continue with normal execution.
        """
        start_time = time.time()
        function_call_id = tool_context.function_call_id or str(uuid.uuid4())
        
        tool_id = self._get_tool_id(tool)
        tool_name = tool.name
        
        logger.debug(
            f"Tool invocation started: {tool_name} (id={tool_id}, "
            f"function_call_id={function_call_id})"
        )
        
        # Get session info from context - ADK's ToolContext.session property
        try:
            session = tool_context.session
            app_name = session.app_name
            user_id = session.user_id
            session_id = session.id
            logger.debug(f"Session info: app={app_name}, user={user_id}, session={session_id}")
        except Exception as e:
            logger.warning(f"Could not get session info from tool_context: {e}")
            app_name = "__unknown__"
            user_id = "__unknown__"
            session_id = "__unknown__"
        
        event_id = getattr(tool_context, "event_id", None)
        
        # Create a pending record
        try:
            record_id = await self._session_service.log_tool_invocation_start(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
                tool_id=tool_id,
                tool_name=tool_name,
                invocation_id=function_call_id,
                args=tool_args if self._log_args else {},
            )
            
            # Store for completion
            self._pending[function_call_id] = (record_id, start_time)
            
            # Call user callback if provided
            if self._on_invocation_start:
                self._on_invocation_start(tool_id, function_call_id, tool_args)
                
        except Exception as e:
            logger.error(f"Failed to log tool invocation start: {e}")
        
        # Return None to continue with normal execution
        return None
    
    async def after_tool_callback(
        self,
        *,
        tool: BaseTool,
        tool_args: Dict[str, Any],
        tool_context: ToolContext,
        result: Dict,
    ) -> Optional[Dict]:
        """Callback invoked after a tool is executed.
        
        This method logs the completion of a tool invocation.
        
        Args:
            tool: The tool that was invoked.
            tool_args: The arguments that were passed to the tool.
            tool_context: The tool context.
            result: The result from the tool.
            
        Returns:
            None to use the original result.
        """
        function_call_id = tool_context.function_call_id or str(uuid.uuid4())
        
        tool_id = self._get_tool_id(tool)
        tool_name = tool.name
        
        # Get pending record
        pending_info = self._pending.pop(function_call_id, None)
        
        if pending_info:
            record_id, start_time = pending_info
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Check for errors in result
            error = None
            if isinstance(result, dict) and "error" in result:
                error = str(result["error"])
            
            logger.debug(
                f"Tool invocation completed: {tool_name} "
                f"(duration={duration_ms}ms, error={error is not None})"
            )
            
            try:
                await self._session_service.log_tool_invocation_end(
                    record_id=record_id,
                    result=result if self._log_results else None,
                    error=error,
                    duration_ms=duration_ms,
                )
                
                # Call user callback if provided
                if self._on_invocation_end:
                    self._on_invocation_end(tool_id, function_call_id, result, error)
                    
            except Exception as e:
                logger.error(f"Failed to log tool invocation end: {e}")
        else:
            logger.warning(
                f"No pending invocation found for function_call_id={function_call_id}"
            )
        
        # Return None to use the original result
        return None


# Legacy class for backward compatibility
class ToolInvocationLogger:
    """Legacy wrapper for tool invocation logging.
    
    For new code, use ToolInvocationLoggerPlugin directly.
    """
    
    def __init__(
        self,
        session_service: "PostgresSessionService",
        **kwargs,
    ):
        """Initialize the legacy logger."""
        self._plugin = ToolInvocationLoggerPlugin(session_service, **kwargs)
        self._session_service = session_service
    
    def create_plugin(self) -> ToolInvocationLoggerPlugin:
        """Create the plugin instance."""
        return self._plugin
    
    async def before_tool(
        self,
        tool: BaseTool,
        args: Dict[str, Any],
        tool_context: ToolContext,
    ) -> Optional[Dict]:
        """Legacy before_tool callback."""
        return await self._plugin.before_tool_callback(
            tool=tool,
            tool_args=args,
            tool_context=tool_context,
        )
    
    async def after_tool(
        self,
        tool: BaseTool,
        args: Dict[str, Any],
        tool_context: ToolContext,
        result: Dict,
    ) -> Optional[Dict]:
        """Legacy after_tool callback."""
        return await self._plugin.after_tool_callback(
            tool=tool,
            tool_args=args,
            tool_context=tool_context,
            result=result,
        )
    
    def get_callbacks(self) -> tuple[Callable, Callable]:
        """Get the callback functions for use with ADK.
        
        Returns:
            Tuple of (before_tool_callback, after_tool_callback).
        """
        return self.before_tool, self.after_tool

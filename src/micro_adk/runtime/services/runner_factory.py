"""Runner factory for creating ADK Runner instances.

This module provides a factory for creating configured ADK Runner
instances with custom session services and tool injection.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from micro_adk.core.config import LiteLLMConfig
from micro_adk.core.postgres_session_service import PostgresSessionService
from micro_adk.core.tool_invocation_logger import (
    ToolInvocationLogger,
    ToolInvocationLoggerPlugin,
)
from micro_adk.core.tool_registry import ToolRegistry

if TYPE_CHECKING:
    from micro_adk.runtime.services.agent_loader import AgentLoader

logger = logging.getLogger(__name__)


class RunnerFactory:
    """Factory for creating ADK Runner instances.
    
    This factory configures runners with:
    - Custom PostgresSessionService for persistence
    - Tool invocation logging via plugins
    - LiteLLM model configuration
    """
    
    def __init__(
        self,
        session_service: PostgresSessionService,
        tool_registry: ToolRegistry,
        litellm_config: LiteLLMConfig,
    ):
        """Initialize the runner factory.
        
        Args:
            session_service: Session service for persistence.
            tool_registry: Registry for resolving tools.
            litellm_config: LiteLLM configuration.
        """
        self.session_service = session_service
        self.tool_registry = tool_registry
        self.litellm_config = litellm_config
        
        self._runners: Dict[str, Any] = {}
        self._tool_logger = ToolInvocationLogger(session_service)
        self._logger_plugin = ToolInvocationLoggerPlugin(session_service)
    
    async def get_runner(
        self,
        agent_id: str,
        agent_loader: "AgentLoader",
        force_new: bool = False,
    ) -> Any:
        """Get or create a Runner for an agent.
        
        Args:
            agent_id: The agent ID.
            agent_loader: Agent loader for creating agents.
            force_new: Force creation of a new runner.
            
        Returns:
            An ADK Runner instance.
            
        Raises:
            ValueError: If agent not found.
        """
        if not force_new and agent_id in self._runners:
            return self._runners[agent_id]
        
        # Create the agent
        agent = agent_loader.create_agent(agent_id)
        
        # Create the runner with the tool invocation logger plugin
        # Plugins are passed to Runner, not to the agent
        from google.adk.runners import Runner
        from google.adk.artifacts import InMemoryArtifactService
        
        runner = Runner(
            agent=agent,
            app_name=agent_id,
            session_service=self.session_service,
            artifact_service=InMemoryArtifactService(),
            plugins=[self._logger_plugin],
        )
        
        self._runners[agent_id] = runner
        return runner
    
    def clear_runners(self) -> None:
        """Clear all cached runners."""
        self._runners.clear()
    
    def get_tool_logger(self) -> ToolInvocationLogger:
        """Get the tool invocation logger."""
        return self._tool_logger
    
    def get_logger_plugin(self) -> ToolInvocationLoggerPlugin:
        """Get the tool invocation logger plugin."""
        return self._logger_plugin

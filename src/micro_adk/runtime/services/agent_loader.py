"""Agent loader service for discovering and loading agent definitions.

This module provides functionality to load agent configurations from
a directory structure where each agent is defined in its own folder.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

from micro_adk.core.tool_registry import ToolRegistry
from micro_adk.runtime.api.schemas import AgentInfo

logger = logging.getLogger(__name__)


class AgentConfig(BaseModel):
    """Configuration for an agent loaded from YAML."""
    
    agent_id: str = Field(..., description="Unique agent identifier")
    name: str = Field(..., description="Human-readable agent name")
    description: Optional[str] = Field(default=None, description="Agent description")
    model: str = Field(default="gemini/gemini-2.0-flash", description="LLM model to use via LiteLLM (format: provider/model)")
    instruction: str = Field(default="You are a helpful assistant.", description="Agent instruction/system prompt")
    tools: List[str] = Field(default_factory=list, description="Tool IDs from the tool registry")
    sub_agents: List[str] = Field(default_factory=list, description="Sub-agent IDs for multi-agent")
    
    # Advanced configuration
    generate_content_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom generate_content_config for the LLM"
    )
    before_model_callback: Optional[str] = Field(
        default=None,
        description="Path to before_model_callback function"
    )
    after_model_callback: Optional[str] = Field(
        default=None,
        description="Path to after_model_callback function"
    )


class AgentLoader:
    """Loads and manages agent definitions from a directory.
    
    The agent directory structure should look like:
    
    agents/
    ├── my_agent/
    │   ├── agent.yaml      # Agent configuration
    │   ├── __init__.py     # Optional Python code
    │   └── tools.py        # Optional custom tools
    └── another_agent/
        └── agent.yaml
    
    Supports hot reload - call reload_agents() to refresh configurations.
    """
    
    def __init__(
        self,
        agents_dir: str,
        tool_registry: ToolRegistry,
        auto_reload: bool = False,
    ):
        """Initialize the agent loader.
        
        Args:
            agents_dir: Path to the directory containing agent definitions.
            tool_registry: Registry for resolving tool references.
            auto_reload: If True, automatically reload agents on each access (dev mode).
        """
        self.agents_dir = Path(agents_dir)
        self.tool_registry = tool_registry
        self.auto_reload = auto_reload
        
        self._agents: Dict[str, AgentConfig] = {}
        self._agent_instances: Dict[str, Any] = {}
        self._last_load_times: Dict[str, float] = {}
        
        # Load agents on init
        self._discover_agents()
    
    def _discover_agents(self) -> None:
        """Discover and load all agent configurations."""
        if not self.agents_dir.exists():
            logger.warning(f"Agents directory not found: {self.agents_dir}")
            return
        
        for agent_path in self.agents_dir.iterdir():
            if not agent_path.is_dir():
                continue
            
            config_file = agent_path / "agent.yaml"
            if not config_file.exists():
                config_file = agent_path / "agent.yml"
            
            if config_file.exists():
                try:
                    self._load_agent_config(agent_path.name, config_file)
                except Exception as e:
                    logger.error(f"Failed to load agent {agent_path.name}: {e}")
    
    def _load_agent_config(self, agent_id: str, config_file: Path) -> None:
        """Load an agent configuration from a YAML file."""
        with open(config_file, "r") as f:
            data = yaml.safe_load(f)
        
        # Set agent_id from directory name if not specified
        if "agent_id" not in data:
            data["agent_id"] = agent_id
        
        config = AgentConfig(**data)
        self._agents[config.agent_id] = config
        self._last_load_times[config.agent_id] = config_file.stat().st_mtime
        
        logger.info(f"Loaded agent: {config.agent_id} ({config.name})")
    
    def reload_agents(self) -> List[str]:
        """Reload all agent configurations from disk.
        
        Returns:
            List of agent IDs that were reloaded.
        """
        # Clear cached instances
        self._agent_instances.clear()
        
        old_agents = set(self._agents.keys())
        self._agents.clear()
        self._last_load_times.clear()
        
        # Rediscover
        self._discover_agents()
        
        new_agents = set(self._agents.keys())
        reloaded = list(new_agents | old_agents)
        
        logger.info(f"Reloaded {len(reloaded)} agents: {reloaded}")
        return reloaded
    
    def reload_agent(self, agent_id: str) -> bool:
        """Reload a specific agent configuration.
        
        Args:
            agent_id: The agent ID to reload.
            
        Returns:
            True if agent was reloaded, False if not found.
        """
        agent_path = self.agents_dir / agent_id
        if not agent_path.exists():
            return False
        
        config_file = agent_path / "agent.yaml"
        if not config_file.exists():
            config_file = agent_path / "agent.yml"
        
        if not config_file.exists():
            return False
        
        # Clear cached instance
        self._agent_instances.pop(agent_id, None)
        
        try:
            self._load_agent_config(agent_id, config_file)
            logger.info(f"Reloaded agent: {agent_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to reload agent {agent_id}: {e}")
            return False
    
    def _check_agent_changed(self, agent_id: str) -> bool:
        """Check if an agent's config file has changed since last load."""
        agent_path = self.agents_dir / agent_id
        config_file = agent_path / "agent.yaml"
        if not config_file.exists():
            config_file = agent_path / "agent.yml"
        
        if not config_file.exists():
            return False
        
        current_mtime = config_file.stat().st_mtime
        last_mtime = self._last_load_times.get(agent_id, 0)
        
        return current_mtime > last_mtime
    
    def list_agents(self) -> List[AgentInfo]:
        """List all available agents."""
        return [
            AgentInfo(
                agent_id=config.agent_id,
                name=config.name,
                description=config.description,
                tools=config.tools,
                model=config.model,
            )
            for config in self._agents.values()
        ]
    
    def get_agent_config(self, agent_id: str) -> Optional[AgentConfig]:
        """Get an agent configuration by ID.
        
        If auto_reload is enabled, checks for file changes before returning.
        """
        # Auto-reload if enabled and file changed
        if self.auto_reload and agent_id in self._agents:
            if self._check_agent_changed(agent_id):
                logger.info(f"Auto-reloading agent {agent_id} (file changed)")
                self.reload_agent(agent_id)
        
        return self._agents.get(agent_id)
    
    def get_agent_info(self, agent_id: str) -> Optional[AgentInfo]:
        """Get agent info by ID."""
        config = self._agents.get(agent_id)
        if not config:
            return None
        
        return AgentInfo(
            agent_id=config.agent_id,
            name=config.name,
            description=config.description,
            tools=config.tools,
            model=config.model,
        )
    
    def create_agent(self, agent_id: str) -> Any:
        """Create an ADK Agent instance from configuration.
        
        Args:
            agent_id: The agent ID to create.
            
        Returns:
            An ADK LlmAgent instance.
            
        Raises:
            ValueError: If agent not found.
        """
        config = self._agents.get(agent_id)
        if not config:
            raise ValueError(f"Agent not found: {agent_id}")
        
        # Import ADK components
        from google.adk.agents import LlmAgent
        from google.adk.models.lite_llm import LiteLlm
        
        # Create the model
        model = LiteLlm(model=config.model)
        
        # Get tools from registry
        tools = []
        for tool_id in config.tools:
            try:
                tool = self.tool_registry.get_tool(tool_id)
                tools.append(tool)
            except ValueError:
                logger.warning(f"Tool not found for agent {agent_id}: {tool_id}")
        
        # Load callbacks if specified
        before_model_callback = None
        after_model_callback = None
        
        if config.before_model_callback:
            before_model_callback = self._load_callback(
                agent_id, config.before_model_callback
            )
        
        if config.after_model_callback:
            after_model_callback = self._load_callback(
                agent_id, config.after_model_callback
            )
        
        # Recursively create sub-agents
        sub_agents = []
        for sub_agent_id in config.sub_agents:
            try:
                sub_agent = self.create_agent(sub_agent_id)
                sub_agents.append(sub_agent)
            except ValueError:
                logger.warning(f"Sub-agent not found for {agent_id}: {sub_agent_id}")
        
        # Create the agent
        agent = LlmAgent(
            name=config.agent_id,
            model=model,
            instruction=config.instruction,
            tools=tools if tools else None,
            sub_agents=sub_agents,
            before_model_callback=before_model_callback,
            after_model_callback=after_model_callback,
            generate_content_config=config.generate_content_config,
        )
        
        return agent
    
    def _load_callback(self, agent_id: str, callback_path: str) -> Optional[Callable]:
        """Load a callback function from a module path.
        
        Args:
            agent_id: The agent ID.
            callback_path: Path like "tools.my_callback" or "module:function".
            
        Returns:
            The callback function or None.
        """
        try:
            agent_dir = self.agents_dir / agent_id
            
            if ":" in callback_path:
                # Full module path
                module_path, func_name = callback_path.rsplit(":", 1)
            else:
                # Relative path within agent directory
                parts = callback_path.rsplit(".", 1)
                if len(parts) == 2:
                    module_path, func_name = parts
                else:
                    logger.warning(f"Invalid callback path: {callback_path}")
                    return None
                
                # Load from agent directory
                module_file = agent_dir / f"{module_path}.py"
                if not module_file.exists():
                    logger.warning(f"Callback module not found: {module_file}")
                    return None
                
                spec = importlib.util.spec_from_file_location(
                    f"agents.{agent_id}.{module_path}",
                    module_file
                )
                if not spec or not spec.loader:
                    return None
                
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                
                return getattr(module, func_name, None)
            
            # Import from full module path
            module = importlib.import_module(module_path)
            return getattr(module, func_name, None)
        
        except Exception as e:
            logger.error(f"Failed to load callback {callback_path}: {e}")
            return None

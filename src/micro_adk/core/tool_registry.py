"""Tool Registry - Manages tool manifests and container tool instances.

This module provides the registry that loads tool definitions from YAML
manifests and creates ContainerTool instances for use by agents.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

import yaml
from pydantic import BaseModel, Field, model_validator

from micro_adk.core.container_tool import (
    ContainerTool, 
    ContainerToolConfig, 
    ContainerToolFactory,
    RoutedContainerTool,
)

logger = logging.getLogger(__name__)


class AutoscalingConfig(BaseModel):
    """Autoscaling configuration for a tool."""
    
    min_replicas: int = Field(default=1, ge=1)
    max_replicas: int = Field(default=5, ge=1)
    cpu_target: int = Field(default=50, ge=1, le=100, description="Target CPU utilization %")
    memory_target: Optional[int] = Field(default=None, ge=1, le=100, description="Target memory utilization %")


class ResourceConfig(BaseModel):
    """Resource limits and requests for a tool container."""
    
    cpu_request: str = Field(default="100m")
    cpu_limit: str = Field(default="500m")
    memory_request: str = Field(default="128Mi")
    memory_limit: str = Field(default="512Mi")


class ToolManifestEntry(BaseModel):
    """A single tool definition in the manifest."""
    
    tool_id: str = Field(..., description="Unique identifier for the tool")
    name: str = Field(..., description="Display name of the tool")
    description: str = Field(..., description="Description of what the tool does")
    
    # Container configuration
    image: str = Field(..., description="Docker image for the tool")
    port: int = Field(default=8080, description="Port the tool listens on")
    
    # Optional direct service URL (for external tools or local development)
    service_url: Optional[str] = Field(default=None, description="Direct URL to the tool service")
    
    # Environment variables
    env: Dict[str, str] = Field(default_factory=dict, description="Environment variables")
    
    # Resources
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    
    # Autoscaling
    autoscaling: AutoscalingConfig = Field(default_factory=AutoscalingConfig)
    
    # Schema - simplified format from manifest (property_name -> schema)
    # This is the user-friendly format in the YAML
    schema_: Dict[str, Any] = Field(
        default_factory=dict,
        alias="schema",
        description="Simplified schema from manifest",
    )
    
    # Parameters schema for LLM function calling (computed from schema)
    parameters: Dict[str, Any] = Field(
        default=None,
        description="JSON Schema for tool parameters",
    )
    
    model_config = {"populate_by_name": True}
    
    @model_validator(mode="after")
    def convert_schema_to_parameters(self) -> "ToolManifestEntry":
        """Convert simplified schema to proper JSON Schema parameters format."""
        # If parameters already set explicitly, use that
        if self.parameters is not None and self.parameters.get("properties"):
            return self
        
        # Convert schema to JSON Schema format
        if self.schema_:
            properties = {}
            required = []
            
            for prop_name, prop_schema in self.schema_.items():
                # Handle both dict format and simple type
                if isinstance(prop_schema, dict):
                    properties[prop_name] = prop_schema
                    # Properties without a default are required
                    if "default" not in prop_schema:
                        required.append(prop_name)
                else:
                    properties[prop_name] = {"type": str(prop_schema)}
                    required.append(prop_name)
            
            self.parameters = {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        else:
            self.parameters = {"type": "object", "properties": {}}
        
        return self
    
    # Health check
    health_check_path: str = Field(default="/health")
    health_check_interval: int = Field(default=30, description="Seconds between health checks")
    
    # Request configuration
    timeout: float = Field(default=30.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts")
    
    def to_container_tool_config(self) -> ContainerToolConfig:
        """Convert to ContainerToolConfig."""
        return ContainerToolConfig(
            tool_id=self.tool_id,
            name=self.name,
            description=self.description,
            service_url=self.service_url,
            service_name=self.tool_id,  # Use tool_id as K8s service name
            service_port=self.port,
            parameters=self.parameters,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )


class ToolManifest(BaseModel):
    """Complete tool manifest containing all tool definitions."""
    
    version: str = Field(default="1.0", description="Manifest version")
    namespace: str = Field(default="micro-adk-tools", description="Kubernetes namespace")
    tools: List[ToolManifestEntry] = Field(default_factory=list)
    
    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "ToolManifest":
        """Load manifest from a YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolManifest":
        """Load manifest from a dictionary."""
        return cls(**data)
    
    def to_yaml(self, path: Union[str, Path]) -> None:
        """Save manifest to a YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)
    
    def get_tool(self, tool_id: str) -> Optional[ToolManifestEntry]:
        """Get a tool entry by ID."""
        for tool in self.tools:
            if tool.tool_id == tool_id:
                return tool
        return None


class ToolRegistry:
    """Registry that manages tools and their container configurations.
    
    The registry loads tool definitions from manifests and creates
    ContainerTool or RoutedContainerTool instances that can be used by agents.
    
    The registry supports two modes:
    - Direct mode: Tools call tool containers directly (embedded router)
    - Routed mode: Tools call through a separate Tool Router service
    
    Example:
        ```python
        # Direct mode (tools call containers directly)
        registry = ToolRegistry()
        registry.load_manifest("./config/tool_manifest.yaml")
        
        # Routed mode (tools call through Tool Router)
        registry = ToolRegistry(router_url="http://tool-router:8081")
        registry.load_manifest("./config/tool_manifest.yaml")
        
        # Get tools for an agent
        tools = registry.get_tools(["calculator", "weather_api"])
        ```
    """
    
    def __init__(
        self,
        service_resolver: Optional[Callable[[str], str]] = None,
        router_url: Optional[str] = None,
    ):
        """Initialize the tool registry.
        
        Args:
            service_resolver: Optional function to resolve service names to URLs.
            router_url: If provided, tools will route through this Tool Router 
                        service instead of calling tool containers directly.
        """
        self._manifests: Dict[str, ToolManifest] = {}
        self._tool_entries: Dict[str, ToolManifestEntry] = {}
        self._factory = ContainerToolFactory(service_resolver=service_resolver)
        self._tools: Dict[str, ContainerTool] = {}
        self._routed_tools: Dict[str, RoutedContainerTool] = {}
        self._router_url = router_url
        
        if router_url:
            logger.info(f"Tool Registry using Router at: {router_url}")
        else:
            logger.info("Tool Registry using direct tool invocation")
    
    def load_manifest(
        self,
        path: Union[str, Path],
        manifest_id: Optional[str] = None,
    ) -> ToolManifest:
        """Load a tool manifest from a YAML file.
        
        Args:
            path: Path to the manifest file.
            manifest_id: Optional ID for the manifest (defaults to filename).
            
        Returns:
            The loaded ToolManifest.
        """
        path = Path(path)
        manifest_id = manifest_id or path.stem
        
        manifest = ToolManifest.from_yaml(path)
        self._manifests[manifest_id] = manifest
        
        # Index all tools
        for tool in manifest.tools:
            self._tool_entries[tool.tool_id] = tool
            logger.info(f"Registered tool: {tool.tool_id}")
        
        logger.info(f"Loaded manifest '{manifest_id}' with {len(manifest.tools)} tools")
        return manifest
    
    def register_tool(self, entry: ToolManifestEntry) -> None:
        """Register a single tool entry.
        
        Args:
            entry: The tool manifest entry to register.
        """
        self._tool_entries[entry.tool_id] = entry
        logger.info(f"Registered tool: {entry.tool_id}")
    
    def get_tool_entry(self, tool_id: str) -> Optional[ToolManifestEntry]:
        """Get a tool manifest entry by ID."""
        return self._tool_entries.get(tool_id)
    
    def get_tool(self, tool_id: str) -> Optional[Union[ContainerTool, RoutedContainerTool]]:
        """Get or create a tool by ID.
        
        If router_url is configured, returns a RoutedContainerTool that calls
        the Tool Router service. Otherwise, returns a direct ContainerTool.
        
        Args:
            tool_id: The tool ID to look up.
            
        Returns:
            A tool instance, or None if not found.
        """
        # If using router, check routed tools cache
        if self._router_url:
            if tool_id in self._routed_tools:
                return self._routed_tools[tool_id]
            
            # Get the manifest entry
            entry = self._tool_entries.get(tool_id)
            if entry is None:
                logger.warning(f"Tool not found in registry: {tool_id}")
                return None
            
            # Create routed tool
            tool = RoutedContainerTool(
                tool_id=entry.tool_id,
                name=entry.name,
                description=entry.description,
                router_url=self._router_url,
                parameters=entry.parameters,
                timeout=entry.timeout,
            )
            self._routed_tools[tool_id] = tool
            logger.debug(f"Created RoutedContainerTool: {tool_id}")
            return tool
        
        # Direct mode: check cache first
        if tool_id in self._tools:
            return self._tools[tool_id]
        
        # Get the manifest entry
        entry = self._tool_entries.get(tool_id)
        if entry is None:
            logger.warning(f"Tool not found in registry: {tool_id}")
            return None
        
        # Create the tool
        config = entry.to_container_tool_config()
        tool = self._factory.create(config)
        self._tools[tool_id] = tool
        
        logger.debug(f"Created ContainerTool: {tool_id}")
        return tool
    
    def get_tools(self, tool_ids: List[str]) -> List[Union[ContainerTool, RoutedContainerTool]]:
        """Get multiple tools by their IDs.
        
        Args:
            tool_ids: List of tool IDs to look up.
            
        Returns:
            List of tool instances (skips missing tools).
        """
        tools = []
        for tool_id in tool_ids:
            tool = self.get_tool(tool_id)
            if tool:
                tools.append(tool)
        return tools
    
    def list_tools(self) -> List[str]:
        """List all registered tool IDs."""
        return list(self._tool_entries.keys())
    
    def list_tool_entries(self) -> List[ToolManifestEntry]:
        """List all registered tool entries."""
        return list(self._tool_entries.values())
    
    @property
    def is_routed(self) -> bool:
        """Check if this registry uses router-based tools."""
        return self._router_url is not None
    
    async def close(self) -> None:
        """Close all tool resources."""
        await self._factory.close_all()
        self._tools.clear()
        
        # Close routed tools
        for tool in self._routed_tools.values():
            await tool.close()
        self._routed_tools.clear()


def create_manifest_example() -> ToolManifest:
    """Create an example tool manifest for reference."""
    return ToolManifest(
        version="1.0",
        namespace="micro-adk-tools",
        tools=[
            ToolManifestEntry(
                tool_id="calculator",
                name="calculator",
                description="Performs arithmetic calculations (add, subtract, multiply, divide)",
                image="micro-adk/calculator:latest",
                port=8080,
                parameters={
                    "type": "object",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["add", "subtract", "multiply", "divide"],
                            "description": "The arithmetic operation to perform",
                        },
                        "a": {
                            "type": "number",
                            "description": "First operand",
                        },
                        "b": {
                            "type": "number",
                            "description": "Second operand",
                        },
                    },
                    "required": ["operation", "a", "b"],
                },
                resources=ResourceConfig(
                    cpu_request="50m",
                    cpu_limit="200m",
                    memory_request="64Mi",
                    memory_limit="128Mi",
                ),
                autoscaling=AutoscalingConfig(
                    min_replicas=1,
                    max_replicas=3,
                    cpu_target=50,
                ),
            ),
            ToolManifestEntry(
                tool_id="weather_api",
                name="get_weather",
                description="Gets current weather for a location",
                image="micro-adk/weather-api:latest",
                port=8080,
                env={"API_KEY": "${WEATHER_API_KEY}"},
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City name or coordinates",
                        },
                        "units": {
                            "type": "string",
                            "enum": ["metric", "imperial"],
                            "default": "metric",
                        },
                    },
                    "required": ["location"],
                },
            ),
        ],
    )

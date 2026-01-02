"""Micro ADK Framework - Run Google ADK agents as HTTP APIs with containerized tools.

This framework provides:
- Agent-as-API: Each agent is callable via REST endpoint
- Tools as Containers: Every tool runs in its own container behind /invoke
- Internal Orchestration: Framework deploys tools and configures autoscaling
- Session Persistence: All conversations + tool calls stored in Postgres
- LiteLLM Integration: All LLM calls go through LiteLLM
"""

__version__ = "0.1.0"

# Core components
from micro_adk.core.config import (
    FrameworkConfig,
    DatabaseConfig,
    LiteLLMConfig,
    ServerConfig,
    ToolOrchestratorConfig,
    ToolRouterConfig,
    load_config,
)
from micro_adk.core.container_tool import (
    ContainerTool,
    ContainerToolConfig,
    ContainerToolFactory,
)
from micro_adk.core.postgres_session_service import PostgresSessionService
from micro_adk.core.tool_invocation_logger import ToolInvocationLogger, ToolInvocationLoggerPlugin
from micro_adk.core.tool_registry import (
    ToolRegistry,
    ToolManifest,
    ToolManifestEntry,
    AutoscalingConfig,
    ResourceConfig,
)

# Router components
from micro_adk.router.tool_router import ToolRouter, ToolRoutingConfig
from micro_adk.router.service_discovery import ServiceDiscovery, ServiceInfo, DiscoveryMode

# Orchestrator components
from micro_adk.orchestrator.kubernetes_orchestrator import (
    KubernetesOrchestrator,
    OrchestratorConfig,
)
from micro_adk.orchestrator.deployment_manager import (
    DeploymentManager,
    DeploymentSpec,
    DeploymentStatus,
)
from micro_adk.orchestrator.autoscaler import (
    AutoscalerManager,
    HPASpec,
    ScalingMetrics,
)

# Runtime components
from micro_adk.runtime import create_app, get_app

__all__ = [
    # Version
    "__version__",
    
    # Config
    "FrameworkConfig",
    "DatabaseConfig",
    "LiteLLMConfig",
    "ServerConfig",
    "ToolOrchestratorConfig",
    "ToolRouterConfig",
    "load_config",
    
    # Container Tool
    "ContainerTool",
    "ContainerToolConfig",
    "ContainerToolFactory",
    
    # Session Service
    "PostgresSessionService",
    
    # Tool Logging
    "ToolInvocationLogger",
    "ToolInvocationMetrics",
    
    # Tool Registry
    "ToolRegistry",
    "ToolManifest",
    "ToolManifestEntry",
    "AutoscalingConfig",
    "ResourceConfig",
    
    # Router
    "ToolRouter",
    "ToolRoutingConfig",
    "ServiceDiscovery",
    "ServiceInfo",
    "DiscoveryMode",
    
    # Orchestrator
    "KubernetesOrchestrator",
    "OrchestratorConfig",
    "DeploymentManager",
    "DeploymentSpec",
    "DeploymentStatus",
    "AutoscalerManager",
    "HPASpec",
    "ScalingMetrics",
    
    # Runtime
    "create_app",
    "get_app",
]

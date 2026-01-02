"""Kubernetes orchestrator for managing tool deployments.

This module provides the main orchestrator interface for deploying
and managing containerized tools in Kubernetes.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from micro_adk.core.tool_registry import ToolManifestEntry, ToolRegistry
from micro_adk.orchestrator.autoscaler import AutoscalerManager, HPASpec
from micro_adk.orchestrator.deployment_manager import (
    DeploymentManager,
    DeploymentSpec,
    DeploymentStatus,
)

logger = logging.getLogger(__name__)


class OrchestratorConfig(BaseModel):
    """Configuration for the Kubernetes orchestrator."""
    
    # Kubernetes settings
    namespace: str = Field(default="default", description="Kubernetes namespace")
    kubeconfig_path: Optional[str] = Field(default=None, description="Path to kubeconfig")
    in_cluster: bool = Field(default=False, description="Running inside cluster")
    
    # Deployment defaults
    default_image_pull_policy: str = Field(default="IfNotPresent")
    default_restart_policy: str = Field(default="Always")
    
    # Resource defaults
    default_cpu_request: str = Field(default="100m")
    default_cpu_limit: str = Field(default="500m")
    default_memory_request: str = Field(default="128Mi")
    default_memory_limit: str = Field(default="512Mi")
    
    # Autoscaling defaults
    default_min_replicas: int = Field(default=1)
    default_max_replicas: int = Field(default=10)
    default_target_cpu_percent: int = Field(default=80)
    
    # Service settings
    service_type: str = Field(default="ClusterIP")
    
    # Labels
    common_labels: Dict[str, str] = Field(default_factory=dict)


class KubernetesOrchestrator:
    """Orchestrates tool deployments in Kubernetes.
    
    This class provides the high-level interface for:
    - Deploying containerized tools from the tool registry
    - Managing horizontal pod autoscaling
    - Health monitoring and status tracking
    - Cleanup and resource management
    """
    
    def __init__(
        self,
        config: Optional[OrchestratorConfig] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        """Initialize the orchestrator.
        
        Args:
            config: Orchestrator configuration.
            tool_registry: Tool registry for reading tool manifests.
        """
        self.config = config or OrchestratorConfig()
        self.tool_registry = tool_registry
        
        # Initialize managers
        self.deployment_manager = DeploymentManager(
            namespace=self.config.namespace,
            kubeconfig_path=self.config.kubeconfig_path,
            in_cluster=self.config.in_cluster,
        )
        
        self.autoscaler_manager = AutoscalerManager(
            namespace=self.config.namespace,
            kubeconfig_path=self.config.kubeconfig_path,
            in_cluster=self.config.in_cluster,
        )
        
        # Track deployed tools
        self._deployed_tools: Dict[str, DeploymentStatus] = {}
    
    async def initialize(self) -> None:
        """Initialize the orchestrator and connect to Kubernetes."""
        await self.deployment_manager.initialize()
        await self.autoscaler_manager.initialize()
        logger.info(f"Orchestrator initialized for namespace: {self.config.namespace}")
    
    async def deploy_tool(
        self,
        tool_id: str,
        tool_entry: Optional[ToolManifestEntry] = None,
    ) -> DeploymentStatus:
        """Deploy a tool from the registry.
        
        Args:
            tool_id: Tool identifier.
            tool_entry: Optional tool manifest entry. If not provided,
                       looks up from the tool registry.
                       
        Returns:
            Deployment status.
            
        Raises:
            ValueError: If tool not found.
        """
        if tool_entry is None:
            if self.tool_registry is None:
                raise ValueError("No tool registry configured")
            
            entries = [e for e in self.tool_registry.list_tool_entries() if e.tool_id == tool_id]
            if not entries:
                raise ValueError(f"Tool not found in registry: {tool_id}")
            tool_entry = entries[0]
        
        # Create deployment spec
        deployment_spec = self._create_deployment_spec(tool_entry)
        
        # Deploy
        status = await self.deployment_manager.deploy(deployment_spec)
        
        # Set up autoscaling if configured
        if tool_entry.autoscaling and tool_entry.autoscaling.enabled:
            hpa_spec = self._create_hpa_spec(tool_entry)
            await self.autoscaler_manager.create_or_update_hpa(hpa_spec)
        
        self._deployed_tools[tool_id] = status
        return status
    
    async def deploy_all_tools(self) -> Dict[str, DeploymentStatus]:
        """Deploy all tools from the registry.
        
        Returns:
            Mapping of tool_id to deployment status.
        """
        if self.tool_registry is None:
            raise ValueError("No tool registry configured")
        
        results = {}
        
        for entry in self.tool_registry.list_tool_entries():
            try:
                status = await self.deploy_tool(entry.tool_id, entry)
                results[entry.tool_id] = status
            except Exception as e:
                logger.error(f"Failed to deploy tool {entry.tool_id}: {e}")
                results[entry.tool_id] = DeploymentStatus(
                    name=entry.name,
                    namespace=self.config.namespace,
                    ready=False,
                    available_replicas=0,
                    error=str(e),
                )
        
        return results
    
    async def undeploy_tool(self, tool_id: str) -> bool:
        """Remove a tool deployment.
        
        Args:
            tool_id: Tool identifier.
            
        Returns:
            True if successful.
        """
        deployment_name = self._get_deployment_name(tool_id)
        
        # Remove HPA if exists
        await self.autoscaler_manager.delete_hpa(deployment_name)
        
        # Remove deployment
        result = await self.deployment_manager.delete(deployment_name)
        
        if tool_id in self._deployed_tools:
            del self._deployed_tools[tool_id]
        
        return result
    
    async def undeploy_all_tools(self) -> None:
        """Remove all tool deployments."""
        for tool_id in list(self._deployed_tools.keys()):
            await self.undeploy_tool(tool_id)
    
    async def get_tool_status(self, tool_id: str) -> Optional[DeploymentStatus]:
        """Get the status of a tool deployment.
        
        Args:
            tool_id: Tool identifier.
            
        Returns:
            Deployment status or None if not deployed.
        """
        deployment_name = self._get_deployment_name(tool_id)
        return await self.deployment_manager.get_status(deployment_name)
    
    async def get_all_tool_statuses(self) -> Dict[str, DeploymentStatus]:
        """Get status of all deployed tools.
        
        Returns:
            Mapping of tool_id to status.
        """
        results = {}
        
        for tool_id in self._deployed_tools:
            status = await self.get_tool_status(tool_id)
            if status:
                results[tool_id] = status
        
        return results
    
    async def scale_tool(
        self,
        tool_id: str,
        replicas: int,
    ) -> bool:
        """Manually scale a tool deployment.
        
        Args:
            tool_id: Tool identifier.
            replicas: Desired replica count.
            
        Returns:
            True if successful.
        """
        deployment_name = self._get_deployment_name(tool_id)
        return await self.deployment_manager.scale(deployment_name, replicas)
    
    async def get_service_url(self, tool_id: str) -> Optional[str]:
        """Get the service URL for a deployed tool.
        
        Args:
            tool_id: Tool identifier.
            
        Returns:
            Service URL or None.
        """
        service_name = self._get_service_name(tool_id)
        
        # In Kubernetes, services are accessible via DNS
        return f"http://{service_name}.{self.config.namespace}.svc.cluster.local"
    
    async def close(self) -> None:
        """Clean up resources."""
        await self.deployment_manager.close()
        await self.autoscaler_manager.close()
    
    def _create_deployment_spec(self, entry: ToolManifestEntry) -> DeploymentSpec:
        """Create a deployment spec from a tool entry."""
        # Resource configuration
        resources = entry.resources or {}
        cpu_request = resources.get("cpu_request", self.config.default_cpu_request)
        cpu_limit = resources.get("cpu_limit", self.config.default_cpu_limit)
        memory_request = resources.get("memory_request", self.config.default_memory_request)
        memory_limit = resources.get("memory_limit", self.config.default_memory_limit)
        
        # Replicas
        replicas = 1
        if entry.autoscaling:
            replicas = entry.autoscaling.min_replicas or self.config.default_min_replicas
        
        # Labels
        labels = {
            "app": entry.name,
            "tool-id": entry.tool_id,
            "managed-by": "micro-adk",
            **self.config.common_labels,
        }
        
        return DeploymentSpec(
            name=self._get_deployment_name(entry.tool_id),
            image=entry.image,
            replicas=replicas,
            container_port=entry.port,
            labels=labels,
            env_vars=entry.env_vars or {},
            cpu_request=cpu_request,
            cpu_limit=cpu_limit,
            memory_request=memory_request,
            memory_limit=memory_limit,
            image_pull_policy=self.config.default_image_pull_policy,
            health_check_path=entry.health_check_path or "/health",
        )
    
    def _create_hpa_spec(self, entry: ToolManifestEntry) -> HPASpec:
        """Create an HPA spec from a tool entry."""
        autoscaling = entry.autoscaling
        
        return HPASpec(
            name=self._get_deployment_name(entry.tool_id),
            deployment_name=self._get_deployment_name(entry.tool_id),
            min_replicas=autoscaling.min_replicas or self.config.default_min_replicas,
            max_replicas=autoscaling.max_replicas or self.config.default_max_replicas,
            target_cpu_percent=autoscaling.target_cpu_percent or self.config.default_target_cpu_percent,
        )
    
    def _get_deployment_name(self, tool_id: str) -> str:
        """Get the deployment name for a tool."""
        # Kubernetes names must be lowercase and valid DNS
        return f"tool-{tool_id.lower().replace('_', '-')}"
    
    def _get_service_name(self, tool_id: str) -> str:
        """Get the service name for a tool."""
        return self._get_deployment_name(tool_id)

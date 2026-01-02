"""Service discovery for containerized tools.

This module provides service discovery mechanisms for locating
tool services in different environments:
- Kubernetes: DNS-based discovery
- Docker Compose: Service name resolution
- Local: Explicit URL configuration
"""

from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DiscoveryMode(str, Enum):
    """Service discovery mode."""
    
    STATIC = "static"           # Explicit URL configuration
    KUBERNETES = "kubernetes"   # Kubernetes DNS
    DOCKER = "docker"           # Docker Compose networking
    CONSUL = "consul"           # Consul service discovery (future)


@dataclass
class ServiceInfo:
    """Information about a discovered service."""
    
    tool_id: str
    name: str
    host: str
    port: int
    healthy: bool = True
    metadata: Dict[str, str] = field(default_factory=dict)
    
    @property
    def url(self) -> str:
        """Get the service URL."""
        return f"http://{self.host}:{self.port}"


class ServiceDiscovery:
    """Discovers tool services in the deployment environment.
    
    This class abstracts service discovery across different environments,
    allowing the tool router to locate containerized tool services.
    """
    
    def __init__(
        self,
        mode: DiscoveryMode = DiscoveryMode.STATIC,
        namespace: str = "default",
        service_suffix: str = "",
    ):
        """Initialize service discovery.
        
        Args:
            mode: Discovery mode.
            namespace: Kubernetes namespace (for K8s mode).
            service_suffix: Suffix for service DNS names.
        """
        self.mode = mode
        self.namespace = namespace
        self.service_suffix = service_suffix
        
        # Static service registry
        self._static_services: Dict[str, ServiceInfo] = {}
        
        # Service cache
        self._cache: Dict[str, ServiceInfo] = {}
        self._cache_ttl = 60  # seconds
    
    def register_static(
        self,
        tool_id: str,
        name: str,
        host: str,
        port: int,
        metadata: Optional[Dict[str, str]] = None,
    ) -> None:
        """Register a static service entry.
        
        Args:
            tool_id: Tool identifier.
            name: Service name.
            host: Service host.
            port: Service port.
            metadata: Optional metadata.
        """
        self._static_services[tool_id] = ServiceInfo(
            tool_id=tool_id,
            name=name,
            host=host,
            port=port,
            metadata=metadata or {},
        )
    
    async def discover(self, tool_id: str, service_name: str) -> Optional[ServiceInfo]:
        """Discover a service by tool ID.
        
        Args:
            tool_id: Tool identifier.
            service_name: Service name for discovery.
            
        Returns:
            ServiceInfo if found, None otherwise.
        """
        if self.mode == DiscoveryMode.STATIC:
            return self._static_services.get(tool_id)
        
        if self.mode == DiscoveryMode.KUBERNETES:
            return await self._discover_kubernetes(tool_id, service_name)
        
        if self.mode == DiscoveryMode.DOCKER:
            return await self._discover_docker(tool_id, service_name)
        
        return None
    
    async def _discover_kubernetes(
        self,
        tool_id: str,
        service_name: str,
    ) -> Optional[ServiceInfo]:
        """Discover a service via Kubernetes DNS.
        
        In Kubernetes, services are accessible via:
        <service-name>.<namespace>.svc.cluster.local
        """
        # Construct the DNS name
        fqdn = f"{service_name}.{self.namespace}.svc.cluster.local"
        if self.service_suffix:
            fqdn = f"{service_name}{self.service_suffix}.{self.namespace}.svc.cluster.local"
        
        try:
            # Resolve the DNS name
            loop = asyncio.get_event_loop()
            addr = await loop.run_in_executor(
                None,
                socket.gethostbyname,
                fqdn,
            )
            
            return ServiceInfo(
                tool_id=tool_id,
                name=service_name,
                host=fqdn,  # Use FQDN for robustness
                port=80,    # Default HTTP port
                metadata={"discovered_via": "kubernetes_dns"},
            )
        
        except socket.gaierror as e:
            logger.warning(f"DNS resolution failed for {fqdn}: {e}")
            return None
    
    async def _discover_docker(
        self,
        tool_id: str,
        service_name: str,
    ) -> Optional[ServiceInfo]:
        """Discover a service via Docker Compose networking.
        
        In Docker Compose, services are accessible by their service name
        on the default network.
        """
        # In Docker Compose, services can be reached by name
        host = service_name
        if self.service_suffix:
            host = f"{service_name}{self.service_suffix}"
        
        try:
            # Try to resolve the service name
            loop = asyncio.get_event_loop()
            addr = await loop.run_in_executor(
                None,
                socket.gethostbyname,
                host,
            )
            
            return ServiceInfo(
                tool_id=tool_id,
                name=service_name,
                host=host,
                port=80,
                metadata={"discovered_via": "docker_compose"},
            )
        
        except socket.gaierror:
            # Service not resolvable, might be starting up
            return ServiceInfo(
                tool_id=tool_id,
                name=service_name,
                host=host,
                port=80,
                healthy=False,
                metadata={"discovered_via": "docker_compose", "dns_resolved": "false"},
            )
    
    async def discover_all(
        self,
        tools: Dict[str, str],
    ) -> Dict[str, Optional[ServiceInfo]]:
        """Discover all tool services.
        
        Args:
            tools: Mapping of tool_id to service_name.
            
        Returns:
            Mapping of tool_id to ServiceInfo.
        """
        results = {}
        
        for tool_id, service_name in tools.items():
            results[tool_id] = await self.discover(tool_id, service_name)
        
        return results
    
    def list_services(self) -> List[ServiceInfo]:
        """List all known services."""
        if self.mode == DiscoveryMode.STATIC:
            return list(self._static_services.values())
        
        return list(self._cache.values())
    
    def clear_cache(self) -> None:
        """Clear the service cache."""
        self._cache.clear()

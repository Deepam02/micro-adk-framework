"""Tool router for routing invocations to containerized tool services.

This module provides the HTTP client layer for invoking tools deployed
as containerized microservices.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Union

import httpx
from pydantic import BaseModel, Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class ToolRoutingConfig(BaseModel):
    """Configuration for tool routing."""
    
    # HTTP client settings
    timeout_seconds: float = Field(default=30.0, description="Request timeout")
    connect_timeout_seconds: float = Field(default=5.0, description="Connection timeout")
    
    # Retry settings
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_min_wait: float = Field(default=0.1, description="Minimum wait between retries")
    retry_max_wait: float = Field(default=10.0, description="Maximum wait between retries")
    
    # Circuit breaker (placeholder for future implementation)
    circuit_breaker_enabled: bool = Field(default=False)
    circuit_breaker_threshold: int = Field(default=5)
    circuit_breaker_timeout: float = Field(default=60.0)
    
    # Load balancing
    load_balance_strategy: str = Field(
        default="round_robin",
        description="Load balancing strategy: round_robin, random, least_connections"
    )


class ToolInvokeRequest(BaseModel):
    """Request payload for tool invocation."""
    
    args: Dict[str, Any] = Field(default_factory=dict)
    context: Optional[Dict[str, Any]] = Field(default=None)


class ToolInvokeResponse(BaseModel):
    """Response from tool invocation."""
    
    result: Any = Field(default=None)
    error: Optional[str] = Field(default=None)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ToolRouter:
    """Routes tool invocations to containerized services.
    
    This class handles the HTTP communication layer between the agent
    runtime and the containerized tool services. It supports:
    
    - Service discovery (via Kubernetes DNS or explicit URLs)
    - Retry logic with exponential backoff
    - Timeout handling
    - Error translation
    """
    
    def __init__(
        self,
        config: Optional[ToolRoutingConfig] = None,
    ):
        """Initialize the tool router.
        
        Args:
            config: Routing configuration.
        """
        self.config = config or ToolRoutingConfig()
        
        # Service URL cache (tool_id -> URL)
        self._service_urls: Dict[str, str] = {}
        
        # Round-robin counters for load balancing
        self._rr_counters: Dict[str, int] = {}
        
        # HTTP client (lazy initialization)
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    self.config.timeout_seconds,
                    connect=self.config.connect_timeout_seconds,
                ),
            )
        return self._client
    
    def register_service(self, tool_id: str, service_url: str) -> None:
        """Register a service URL for a tool.
        
        Args:
            tool_id: Tool identifier.
            service_url: Base URL of the tool service.
        """
        self._service_urls[tool_id] = service_url.rstrip("/")
        logger.info(f"Registered service for tool {tool_id}: {service_url}")
    
    def register_services(self, services: Dict[str, str]) -> None:
        """Register multiple service URLs.
        
        Args:
            services: Mapping of tool_id to service_url.
        """
        for tool_id, url in services.items():
            self.register_service(tool_id, url)
    
    def get_service_url(self, tool_id: str) -> Optional[str]:
        """Get the service URL for a tool.
        
        Args:
            tool_id: Tool identifier.
            
        Returns:
            Service URL or None if not registered.
        """
        return self._service_urls.get(tool_id)
    
    async def invoke(
        self,
        tool_id: str,
        args: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolInvokeResponse:
        """Invoke a tool via its containerized service.
        
        Args:
            tool_id: Tool identifier.
            args: Tool arguments.
            context: Optional invocation context.
            
        Returns:
            Tool invocation response.
            
        Raises:
            ValueError: If tool service not registered.
            httpx.HTTPError: If HTTP request fails after retries.
        """
        service_url = self._service_urls.get(tool_id)
        if not service_url:
            raise ValueError(f"No service registered for tool: {tool_id}")
        
        invoke_url = f"{service_url}/invoke"
        request = ToolInvokeRequest(args=args, context=context)
        
        return await self._invoke_with_retry(
            tool_id=tool_id,
            url=invoke_url,
            request=request,
        )
    
    async def _invoke_with_retry(
        self,
        tool_id: str,
        url: str,
        request: ToolInvokeRequest,
    ) -> ToolInvokeResponse:
        """Invoke with retry logic."""
        
        @retry(
            retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
            stop=stop_after_attempt(self.config.max_retries),
            wait=wait_exponential(
                min=self.config.retry_min_wait,
                max=self.config.retry_max_wait,
            ),
            reraise=True,
        )
        async def _do_invoke():
            client = await self._get_client()
            
            logger.debug(f"Invoking tool {tool_id} at {url}")
            
            response = await client.post(
                url,
                json=request.model_dump(exclude_none=True),
            )
            
            if response.status_code >= 500:
                # Retry on server errors
                response.raise_for_status()
            
            if response.status_code >= 400:
                # Client errors - don't retry
                return ToolInvokeResponse(
                    error=f"Tool error: {response.status_code} - {response.text}"
                )
            
            data = response.json()
            return ToolInvokeResponse(**data)
        
        try:
            return await _do_invoke()
        except httpx.HTTPError as e:
            logger.error(f"Tool invocation failed for {tool_id}: {e}")
            return ToolInvokeResponse(error=str(e))
    
    async def invoke_batch(
        self,
        invocations: List[Dict[str, Any]],
    ) -> List[ToolInvokeResponse]:
        """Invoke multiple tools in parallel.
        
        Args:
            invocations: List of dicts with tool_id, args, context.
            
        Returns:
            List of responses in same order as invocations.
        """
        tasks = [
            self.invoke(
                tool_id=inv["tool_id"],
                args=inv.get("args", {}),
                context=inv.get("context"),
            )
            for inv in invocations
        ]
        
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    async def health_check(self, tool_id: str) -> bool:
        """Check if a tool service is healthy.
        
        Args:
            tool_id: Tool identifier.
            
        Returns:
            True if healthy, False otherwise.
        """
        service_url = self._service_urls.get(tool_id)
        if not service_url:
            return False
        
        try:
            client = await self._get_client()
            response = await client.get(f"{service_url}/health")
            return response.status_code == 200
        except Exception:
            return False
    
    async def health_check_all(self) -> Dict[str, bool]:
        """Check health of all registered tool services.
        
        Returns:
            Mapping of tool_id to health status.
        """
        results = {}
        
        tasks = {
            tool_id: self.health_check(tool_id)
            for tool_id in self._service_urls
        }
        
        for tool_id, task in tasks.items():
            results[tool_id] = await task
        
        return results
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    def list_services(self) -> Dict[str, str]:
        """List all registered services.
        
        Returns:
            Mapping of tool_id to service_url.
        """
        return dict(self._service_urls)

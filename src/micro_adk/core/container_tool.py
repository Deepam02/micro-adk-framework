"""ContainerTool - A tool that invokes containerized microservices.

This module provides a custom tool type that extends Google ADK's BaseTool
to call containerized services via a standard /invoke HTTP API.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Union

import httpx
from google.genai import types
from pydantic import BaseModel, Field, model_validator
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from typing_extensions import override

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger(__name__)


class ToolInvokeRequest(BaseModel):
    """Standard request format for tool invocation."""
    
    session_id: str = Field(..., description="The session ID")
    tool_name: str = Field(..., description="Name of the tool being invoked")
    args: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class ToolInvokeResponse(BaseModel):
    """Standard response format from tool invocation."""
    
    ok: bool = Field(default=True, description="Whether the invocation was successful")
    result: Optional[Any] = Field(default=None, description="The result of the invocation")
    error: Optional[str] = Field(default=None, description="Error message if not ok")
    
    @model_validator(mode="after")
    def infer_ok_from_error(self) -> "ToolInvokeResponse":
        """Infer 'ok' value based on 'error' if not explicitly set."""
        # If error is present, set ok to False
        if self.error:
            self.ok = False
        return self


class ContainerToolConfig(BaseModel):
    """Configuration for a container tool."""
    
    tool_id: str = Field(..., description="Unique identifier for the tool")
    name: str = Field(..., description="Display name of the tool")
    description: str = Field(..., description="Description of what the tool does")
    
    # Service endpoint
    service_url: Optional[str] = Field(
        default=None, 
        description="Direct URL to the tool service (overrides discovery)"
    )
    service_name: Optional[str] = Field(
        default=None,
        description="Kubernetes service name for discovery"
    )
    service_port: int = Field(default=8080, description="Port the service listens on")
    
    # Parameters schema for LLM function calling
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for tool parameters"
    )
    
    # Request configuration
    timeout: float = Field(default=30.0, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts")
    
    # Headers
    headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Additional headers to send with requests"
    )


class ContainerTool(BaseTool):
    """A tool that invokes a containerized microservice.
    
    This tool makes HTTP POST requests to a containerized service's /invoke
    endpoint following a standard request/response contract.
    
    Example:
        ```python
        tool = ContainerTool(
            config=ContainerToolConfig(
                tool_id="calculator",
                name="calculator",
                description="Performs arithmetic calculations",
                service_url="http://calculator:8080",
                parameters={
                    "type": "object",
                    "properties": {
                        "operation": {"type": "string", "enum": ["add", "subtract", "multiply", "divide"]},
                        "a": {"type": "number"},
                        "b": {"type": "number"}
                    },
                    "required": ["operation", "a", "b"]
                }
            )
        )
        ```
    """
    
    def __init__(
        self,
        config: ContainerToolConfig,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
        service_resolver: Optional[Callable[[str], str]] = None,
    ):
        """Initialize the ContainerTool.
        
        Args:
            config: Configuration for the container tool.
            http_client: Optional pre-configured HTTP client.
            service_resolver: Optional callable to resolve service names to URLs.
        """
        super().__init__(
            name=config.name,
            description=config.description,
        )
        self.config = config
        self._http_client = http_client
        self._service_resolver = service_resolver
        self._owns_client = http_client is None
        
    @property
    def tool_id(self) -> str:
        """Get the tool ID."""
        return self.config.tool_id
    
    def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout),
                headers=self.config.headers,
            )
        return self._http_client
    
    def _resolve_service_url(self) -> str:
        """Resolve the service URL.
        
        Returns:
            The URL to invoke the tool service.
            
        Raises:
            ValueError: If no URL can be resolved.
        """
        if self.config.service_url:
            return self.config.service_url
        
        if self.config.service_name and self._service_resolver:
            return self._service_resolver(self.config.service_name)
        
        if self.config.service_name:
            # Default Kubernetes DNS resolution
            return f"http://{self.config.service_name}:{self.config.service_port}"
        
        raise ValueError(
            f"Cannot resolve service URL for tool '{self.name}'. "
            "Provide either service_url or service_name."
        )
    
    @override
    def _get_declaration(self) -> Optional[types.FunctionDeclaration]:
        """Get the function declaration for LLM tool calling."""
        # Build parameters schema
        parameters = self.config.parameters or {
            "type": "object",
            "properties": {},
        }
        
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=parameters,
        )
    
    async def _invoke_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        request: ToolInvokeRequest,
    ) -> ToolInvokeResponse:
        """Invoke the tool with retry logic."""
        
        @retry(
            retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
            stop=stop_after_attempt(self.config.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            reraise=True,
        )
        async def _do_invoke() -> ToolInvokeResponse:
            response = await client.post(
                url,
                json=request.model_dump(),
            )
            response.raise_for_status()
            return ToolInvokeResponse.model_validate(response.json())
        
        return await _do_invoke()
    
    @override
    async def run_async(
        self,
        *,
        args: Dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        """Execute the tool by calling the containerized service.
        
        Args:
            args: The arguments passed by the LLM.
            tool_context: The context for the tool invocation.
            
        Returns:
            The result from the containerized service.
        """
        # Get session ID from context
        session_id = tool_context.session.id if tool_context.session else "unknown"
        
        # Build the request
        request = ToolInvokeRequest(
            session_id=session_id,
            tool_name=self.name,
            args=args,
            metadata={
                "tool_id": self.tool_id,
                "invocation_id": tool_context.invocation_id if hasattr(tool_context, 'invocation_id') else None,
            },
        )
        
        # Resolve service URL
        try:
            base_url = self._resolve_service_url()
            invoke_url = f"{base_url.rstrip('/')}/invoke"
        except ValueError as e:
            logger.error(f"Failed to resolve service URL: {e}")
            return {"error": str(e)}
        
        logger.info(
            f"Invoking container tool '{self.name}' at {invoke_url}",
            extra={
                "tool_id": self.tool_id,
                "session_id": session_id,
                "tool_args": args,
            },
        )
        
        # Make the request
        client = self._get_http_client()
        try:
            response = await self._invoke_with_retry(client, invoke_url, request)
            
            if not response.ok:
                logger.error(
                    f"Tool '{self.name}' returned error: {response.error}",
                    extra={"tool_id": self.tool_id, "error": response.error},
                )
                return {"error": response.error}
            
            logger.info(
                f"Tool '{self.name}' completed successfully",
                extra={"tool_id": self.tool_id},
            )
            return response.result
            
        except httpx.HTTPStatusError as e:
            logger.error(
                f"HTTP error invoking tool '{self.name}': {e}",
                extra={"tool_id": self.tool_id, "status_code": e.response.status_code},
            )
            return {"error": f"HTTP {e.response.status_code}: {e.response.text}"}
            
        except httpx.TimeoutException:
            logger.error(
                f"Timeout invoking tool '{self.name}'",
                extra={"tool_id": self.tool_id, "timeout": self.config.timeout},
            )
            return {"error": f"Request timed out after {self.config.timeout}s"}
            
        except Exception as e:
            logger.exception(f"Unexpected error invoking tool '{self.name}'")
            return {"error": str(e)}
    
    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
    
    def __repr__(self) -> str:
        return f"ContainerTool(name={self.name!r}, tool_id={self.tool_id!r})"


class ContainerToolFactory:
    """Factory for creating ContainerTool instances from configuration."""
    
    def __init__(
        self,
        http_client: Optional[httpx.AsyncClient] = None,
        service_resolver: Optional[Callable[[str], str]] = None,
    ):
        """Initialize the factory.
        
        Args:
            http_client: Shared HTTP client for all tools.
            service_resolver: Service name to URL resolver.
        """
        self._http_client = http_client
        self._service_resolver = service_resolver
        self._tools: Dict[str, ContainerTool] = {}
    
    def create(self, config: ContainerToolConfig) -> ContainerTool:
        """Create a ContainerTool from configuration.
        
        Args:
            config: The tool configuration.
            
        Returns:
            A configured ContainerTool instance.
        """
        tool = ContainerTool(
            config=config,
            http_client=self._http_client,
            service_resolver=self._service_resolver,
        )
        self._tools[config.tool_id] = tool
        return tool
    
    def get(self, tool_id: str) -> Optional[ContainerTool]:
        """Get a previously created tool by ID."""
        return self._tools.get(tool_id)
    
    def all(self) -> list[ContainerTool]:
        """Get all created tools."""
        return list(self._tools.values())
    
    async def close_all(self) -> None:
        """Close all tools and their resources."""
        for tool in self._tools.values():
            await tool.close()
        self._tools.clear()


# =============================================================================
# RoutedContainerTool - Routes through the Tool Router service
# =============================================================================

class RoutedContainerTool(BaseTool):
    """A tool that routes invocations through the Tool Router service.
    
    This tool makes HTTP POST requests to the Tool Router's /route endpoint,
    which then forwards the request to the appropriate tool container.
    
    This separates concerns:
    - Agent Runtime: Handles agent logic and LLM calls
    - Tool Router: Handles routing and communication with tool containers
    - Tool Containers: Handle actual tool execution
    
    Example:
        ```python
        tool = RoutedContainerTool(
            tool_id="calculator",
            name="calculator",
            description="Performs arithmetic calculations",
            router_url="http://tool-router:8081",
            parameters={
                "type": "object",
                "properties": {
                    "operation": {"type": "string"},
                    "a": {"type": "number"},
                    "b": {"type": "number"}
                }
            }
        )
        ```
    """
    
    def __init__(
        self,
        tool_id: str,
        name: str,
        description: str,
        router_url: str,
        parameters: Dict[str, Any],
        *,
        timeout: float = 30.0,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        """Initialize the RoutedContainerTool.
        
        Args:
            tool_id: Unique identifier for the tool.
            name: Display name of the tool.
            description: Description of what the tool does.
            router_url: URL of the Tool Router service.
            parameters: JSON Schema for tool parameters.
            timeout: Request timeout in seconds.
            http_client: Optional pre-configured HTTP client.
        """
        super().__init__(
            name=name,
            description=description,
        )
        self._tool_id = tool_id
        self._router_url = router_url.rstrip("/")
        self._parameters = parameters
        self._timeout = timeout
        self._http_client = http_client
        self._owns_client = http_client is None
    
    @property
    def tool_id(self) -> str:
        """Get the tool ID."""
        return self._tool_id
    
    def _get_http_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
            )
        return self._http_client
    
    @override
    def _get_declaration(self) -> Optional[types.FunctionDeclaration]:
        """Get the function declaration for LLM tool calling."""
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=self._parameters or {"type": "object", "properties": {}},
        )
    
    @override
    async def run_async(
        self,
        *,
        args: Dict[str, Any],
        tool_context: ToolContext,
    ) -> Any:
        """Execute the tool by calling the Tool Router service.
        
        Args:
            args: The arguments passed by the LLM.
            tool_context: The context for the tool invocation.
            
        Returns:
            The result from the tool via the Router.
        """
        session_id = tool_context.session.id if tool_context.session else "unknown"
        
        # Build request for the Router
        route_request = {
            "tool_id": self._tool_id,
            "args": args,
            "session_id": session_id,
            "context": {
                "invocation_id": getattr(tool_context, 'invocation_id', None),
            },
        }
        
        route_url = f"{self._router_url}/route"
        
        logger.info(
            f"Routing tool '{self.name}' through {route_url}",
            extra={"tool_id": self._tool_id, "session_id": session_id},
        )
        
        client = self._get_http_client()
        try:
            response = await client.post(route_url, json=route_request)
            response.raise_for_status()
            
            result = response.json()
            
            if not result.get("ok", True):
                error = result.get("error", "Unknown error")
                logger.error(f"Tool '{self.name}' failed: {error}")
                return {"error": error}
            
            logger.info(
                f"Tool '{self.name}' completed via router",
                extra={"tool_id": self._tool_id, "duration_ms": result.get("duration_ms")},
            )
            return result.get("result")
            
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error from router: {e}")
            return {"error": f"Router error: HTTP {e.response.status_code}"}
            
        except httpx.TimeoutException:
            logger.error(f"Router timeout for tool '{self.name}'")
            return {"error": f"Router timeout after {self._timeout}s"}
            
        except Exception as e:
            logger.exception(f"Error routing tool '{self.name}'")
            return {"error": str(e)}
    
    async def close(self) -> None:
        """Close the HTTP client if we own it."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

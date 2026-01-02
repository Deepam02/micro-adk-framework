"""Tool Router Service - FastAPI application.

This is a standalone service that handles routing tool calls
to the appropriate tool containers. It acts as the "Data Plane"
in the architecture.

The Agent Runtime calls this service, which then routes
to the appropriate tool container's /invoke endpoint.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

class ToolConfig(BaseModel):
    """Configuration for a single tool."""
    tool_id: str
    name: str
    service_url: str  # e.g., http://tool-calculator:8080
    description: Optional[str] = None
    timeout: int = 30


class RouterConfig(BaseModel):
    """Router service configuration."""
    tools: Dict[str, ToolConfig] = {}
    default_timeout: int = 30
    max_retries: int = 3


# =============================================================================
# Request/Response Models
# =============================================================================

class RouteRequest(BaseModel):
    """Request to route a tool invocation."""
    tool_id: str
    args: Dict[str, Any]
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class RouteResponse(BaseModel):
    """Response from a tool invocation."""
    ok: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    tool_id: str
    duration_ms: Optional[int] = None


class ToolInfo(BaseModel):
    """Information about a registered tool."""
    tool_id: str
    name: str
    service_url: str
    description: Optional[str] = None
    healthy: bool = False


# =============================================================================
# Router State
# =============================================================================

class RouterState:
    """Holds the router's runtime state."""
    
    def __init__(self):
        self.config: RouterConfig = RouterConfig()
        self.http_client: Optional[httpx.AsyncClient] = None
    
    def load_manifest(self, manifest_path: str) -> None:
        """Load tool configurations from manifest file."""
        if not os.path.exists(manifest_path):
            logger.warning(f"Manifest not found: {manifest_path}")
            return
        
        with open(manifest_path) as f:
            data = yaml.safe_load(f)
        
        tools = data.get("tools", [])
        for tool_def in tools:
            tool_id = tool_def.get("tool_id")
            if not tool_id:
                continue
            
            # Build service URL from manifest
            # In Docker Compose, service name is tool-{tool_id}
            service_name = tool_def.get("service_name", f"tool-{tool_id}")
            port = tool_def.get("port", 8080)
            service_url = f"http://{service_name}:{port}"
            
            self.config.tools[tool_id] = ToolConfig(
                tool_id=tool_id,
                name=tool_def.get("name", tool_id),
                service_url=service_url,
                description=tool_def.get("description"),
                timeout=tool_def.get("timeout", self.config.default_timeout),
            )
            logger.info(f"Registered tool: {tool_id} -> {service_url}")
    
    async def init_client(self) -> None:
        """Initialize the HTTP client."""
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.default_timeout),
        )
    
    async def close_client(self) -> None:
        """Close the HTTP client."""
        if self.http_client:
            await self.http_client.aclose()


state = RouterState()


# =============================================================================
# Application Lifecycle
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    manifest_path = os.getenv("TOOLS_MANIFEST_PATH", "/app/tools/manifest.yaml")
    logger.info(f"Loading tool manifest from: {manifest_path}")
    state.load_manifest(manifest_path)
    
    await state.init_client()
    logger.info(f"Tool Router started with {len(state.config.tools)} tools")
    
    yield
    
    # Shutdown
    await state.close_client()
    logger.info("Tool Router stopped")


# =============================================================================
# FastAPI Application
# =============================================================================

app = FastAPI(
    title="Tool Router Service",
    description="Routes tool invocations to containerized tool services",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "tool-router",
        "tools_registered": len(state.config.tools),
    }


@app.get("/tools", response_model=list[ToolInfo])
async def list_tools():
    """List all registered tools with health status."""
    tools = []
    
    for tool_id, config in state.config.tools.items():
        # Quick health check
        healthy = False
        try:
            resp = await state.http_client.get(
                f"{config.service_url}/health",
                timeout=2.0,
            )
            healthy = resp.status_code == 200
        except Exception:
            pass
        
        tools.append(ToolInfo(
            tool_id=tool_id,
            name=config.name,
            service_url=config.service_url,
            description=config.description,
            healthy=healthy,
        ))
    
    return tools


@app.get("/tools/{tool_id}", response_model=ToolInfo)
async def get_tool(tool_id: str):
    """Get information about a specific tool."""
    if tool_id not in state.config.tools:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_id}")
    
    config = state.config.tools[tool_id]
    
    # Health check
    healthy = False
    try:
        resp = await state.http_client.get(
            f"{config.service_url}/health",
            timeout=2.0,
        )
        healthy = resp.status_code == 200
    except Exception:
        pass
    
    return ToolInfo(
        tool_id=tool_id,
        name=config.name,
        service_url=config.service_url,
        description=config.description,
        healthy=healthy,
    )


@app.post("/route", response_model=RouteResponse)
async def route_tool_call(request: RouteRequest):
    """Route a tool invocation to the appropriate tool container.
    
    This is the main endpoint called by the Agent Runtime.
    """
    import time
    start_time = time.time()
    
    tool_id = request.tool_id
    
    # Find tool configuration
    if tool_id not in state.config.tools:
        return RouteResponse(
            ok=False,
            error=f"Tool not registered: {tool_id}",
            tool_id=tool_id,
        )
    
    config = state.config.tools[tool_id]
    
    # Build request payload for the tool
    payload = {
        "args": request.args,
        "context": request.context or {},
    }
    
    if request.session_id:
        payload["context"]["session_id"] = request.session_id
    
    # Call the tool service
    try:
        logger.info(f"Routing to tool {tool_id} at {config.service_url}/invoke")
        
        response = await state.http_client.post(
            f"{config.service_url}/invoke",
            json=payload,
            timeout=config.timeout,
        )
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        if response.status_code != 200:
            return RouteResponse(
                ok=False,
                error=f"Tool returned status {response.status_code}: {response.text}",
                tool_id=tool_id,
                duration_ms=duration_ms,
            )
        
        result = response.json()
        
        # Handle different response formats
        if "error" in result and result["error"]:
            return RouteResponse(
                ok=False,
                error=result["error"],
                tool_id=tool_id,
                duration_ms=duration_ms,
            )
        
        return RouteResponse(
            ok=True,
            result=result.get("result", result),
            tool_id=tool_id,
            duration_ms=duration_ms,
        )
        
    except httpx.TimeoutException:
        duration_ms = int((time.time() - start_time) * 1000)
        return RouteResponse(
            ok=False,
            error=f"Tool {tool_id} timed out after {config.timeout}s",
            tool_id=tool_id,
            duration_ms=duration_ms,
        )
    except httpx.ConnectError as e:
        duration_ms = int((time.time() - start_time) * 1000)
        return RouteResponse(
            ok=False,
            error=f"Failed to connect to tool {tool_id}: {e}",
            tool_id=tool_id,
            duration_ms=duration_ms,
        )
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.exception(f"Error routing to tool {tool_id}")
        return RouteResponse(
            ok=False,
            error=f"Unexpected error: {str(e)}",
            tool_id=tool_id,
            duration_ms=duration_ms,
        )


# =============================================================================
# Direct invoke endpoint (for backwards compatibility)
# =============================================================================

@app.post("/tools/{tool_id}/invoke", response_model=RouteResponse)
async def invoke_tool_direct(tool_id: str, request: Dict[str, Any]):
    """Direct tool invocation by tool_id."""
    route_request = RouteRequest(
        tool_id=tool_id,
        args=request.get("args", {}),
        session_id=request.get("session_id"),
        context=request.get("context"),
    )
    return await route_tool_call(route_request)

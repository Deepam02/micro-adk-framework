"""Main FastAPI application for the Agent Runtime.

This module provides the HTTP API for running Google ADK agents with
containerized tools.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from micro_adk.core.config import FrameworkConfig, load_config
from micro_adk.core.postgres_session_service import PostgresSessionService
from micro_adk.core.tool_registry import ToolRegistry
from micro_adk.runtime.api.schemas import (
    AgentInfo,
    AgentRunRequest,
    AgentRunResponse,
    CreateSessionRequest,
    EventResponse,
    HealthResponse,
    ListAgentsResponse,
    ListSessionsResponse,
    SessionResponse,
    ToolInvocationResponse,
)
from micro_adk.runtime.services.agent_loader import AgentLoader
from micro_adk.runtime.services.runner_factory import RunnerFactory

logger = logging.getLogger(__name__)


class AppState:
    """Application state container."""
    
    def __init__(self):
        self.config: Optional[FrameworkConfig] = None
        self.session_service: Optional[PostgresSessionService] = None
        self.tool_registry: Optional[ToolRegistry] = None
        self.agent_loader: Optional[AgentLoader] = None
        self.runner_factory: Optional[RunnerFactory] = None


# Global app state
_state = AppState()


def get_state() -> AppState:
    """Get the application state."""
    return _state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    state = get_state()
    
    # Load configuration
    config_path = app.extra.get("config_path")
    state.config = load_config(config_path)
    
    logger.info("Starting Agent Runtime API")
    logger.info(f"Agents directory: {state.config.agents_dir}")
    logger.info(f"Tools manifest: {state.config.tools_manifest_path}")
    
    # Initialize services
    state.session_service = PostgresSessionService(
        db_url=state.config.database.url,
        pool_size=state.config.database.pool_size,
        max_overflow=state.config.database.max_overflow,
    )
    await state.session_service.initialize()
    
    # Initialize tool registry
    # If router_service_url is configured, tools will route through the Tool Router
    # Otherwise, they call tool containers directly
    router_url = state.config.router.router_service_url
    service_resolver = state.config.router.resolve_service_url if not router_url else None
    
    state.tool_registry = ToolRegistry(
        service_resolver=service_resolver,
        router_url=router_url,
    )
    
    if router_url:
        logger.info(f"Tool routing through: {router_url}")
    else:
        logger.info("Direct tool invocation (no router service)")
    
    try:
        state.tool_registry.load_manifest(state.config.tools_manifest_path)
    except FileNotFoundError:
        logger.warning(f"Tool manifest not found: {state.config.tools_manifest_path}")
    
    # Initialize agent loader with auto_reload in dev mode
    auto_reload = state.config.server.reload
    state.agent_loader = AgentLoader(
        agents_dir=state.config.agents_dir,
        tool_registry=state.tool_registry,
        auto_reload=auto_reload,
    )
    if auto_reload:
        logger.info("Agent hot-reload enabled (auto_reload=True)")
    
    # Initialize runner factory
    state.runner_factory = RunnerFactory(
        session_service=state.session_service,
        tool_registry=state.tool_registry,
        litellm_config=state.config.litellm,
    )
    
    yield
    
    # Cleanup
    logger.info("Shutting down Agent Runtime API")
    
    if state.tool_registry:
        await state.tool_registry.close()
    
    if state.session_service:
        await state.session_service.close()


def create_app(
    config_path: Optional[str] = None,
    config: Optional[FrameworkConfig] = None,
) -> FastAPI:
    """Create the FastAPI application.
    
    Args:
        config_path: Optional path to configuration file.
        config: Optional pre-loaded configuration.
        
    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="Micro ADK Agent Runtime",
        description="HTTP API for running Google ADK agents with containerized tools",
        version="0.1.0",
        lifespan=lifespan,
        config_path=config_path,
    )
    
    # Store config in app extra
    if config_path:
        app.extra["config_path"] = config_path
    
    # Add CORS middleware
    if config:
        origins = config.server.cors_origins
    else:
        origins = ["*"]
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Register routes
    register_routes(app)
    
    return app


def register_routes(app: FastAPI) -> None:
    """Register all API routes."""
    
    # =========================================================================
    # Health Check
    # =========================================================================
    
    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health_check() -> HealthResponse:
        """Check the health of the service."""
        state = get_state()
        
        db_healthy = False
        if state.session_service:
            try:
                # Try a simple query
                await state.session_service.list_sessions(app_name="__health__")
                db_healthy = True
            except Exception:
                pass
        
        return HealthResponse(
            status="healthy" if db_healthy else "degraded",
            database=db_healthy,
            version="0.1.0",
        )
    
    # =========================================================================
    # Agents
    # =========================================================================
    
    @app.get("/agents", response_model=ListAgentsResponse, tags=["Agents"])
    async def list_agents() -> ListAgentsResponse:
        """List all available agents."""
        state = get_state()
        
        if not state.agent_loader:
            return ListAgentsResponse(agents=[])
        
        agents = state.agent_loader.list_agents()
        return ListAgentsResponse(agents=agents)
    
    @app.post("/agents/reload", tags=["Agents"])
    async def reload_agents() -> dict:
        """Reload all agent configurations from disk (hot reload)."""
        state = get_state()
        
        if not state.agent_loader:
            raise HTTPException(status_code=503, detail="Agent loader not initialized")
        
        # Reload agents
        reloaded = state.agent_loader.reload_agents()
        
        # Clear runner cache to force recreation
        if state.runner_factory:
            state.runner_factory._runners.clear()
        
        return {
            "status": "ok",
            "reloaded_agents": reloaded,
            "message": f"Reloaded {len(reloaded)} agents"
        }
    
    @app.post("/agents/{agent_id}/reload", tags=["Agents"])
    async def reload_agent(agent_id: str) -> dict:
        """Reload a specific agent configuration (hot reload)."""
        state = get_state()
        
        if not state.agent_loader:
            raise HTTPException(status_code=503, detail="Agent loader not initialized")
        
        success = state.agent_loader.reload_agent(agent_id)
        
        if not success:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        
        # Clear runner cache for this agent
        if state.runner_factory and agent_id in state.runner_factory._runners:
            del state.runner_factory._runners[agent_id]
        
        return {
            "status": "ok",
            "agent_id": agent_id,
            "message": f"Reloaded agent: {agent_id}"
        }
    
    @app.get("/agents/{agent_id}", response_model=AgentInfo, tags=["Agents"])
    async def get_agent(agent_id: str) -> AgentInfo:
        """Get information about a specific agent."""
        state = get_state()
        
        if not state.agent_loader:
            raise HTTPException(status_code=503, detail="Agent loader not initialized")
        
        agent_info = state.agent_loader.get_agent_info(agent_id)
        if not agent_info:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        
        return agent_info
    
    @app.post("/agents/{agent_id}/run", response_model=AgentRunResponse, tags=["Agents"])
    async def run_agent(
        agent_id: str,
        request: AgentRunRequest,
        stream: bool = Query(default=False, description="Stream events via SSE"),
    ) -> AgentRunResponse | StreamingResponse:
        """Run an agent with the given input.
        
        This endpoint executes an agent and returns the response. If streaming
        is enabled, it returns Server-Sent Events (SSE) with each event as it
        occurs.
        """
        state = get_state()
        
        if not state.runner_factory or not state.agent_loader:
            raise HTTPException(status_code=503, detail="Service not initialized")
        
        # Get or create runner
        try:
            runner = await state.runner_factory.get_runner(
                agent_id=agent_id,
                agent_loader=state.agent_loader,
            )
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        
        if stream:
            # Return streaming response
            return StreamingResponse(
                _stream_agent_run(runner, request),
                media_type="text/event-stream",
            )
        
        # Non-streaming: collect all events
        events = []
        final_response = None
        
        try:
            from google.genai import types
            
            new_message = types.Content(
                role="user",
                parts=[types.Part(text=request.input)],
            )
            
            async for event in runner.run_async(
                user_id=request.user_id,
                session_id=request.session_id,
                new_message=new_message,
            ):
                events.append(EventResponse.from_event(event))
                
                # Check for final response
                if event.is_final_response() and event.content:
                    final_response = _extract_text_from_content(event.content)
        
        except Exception as e:
            logger.exception(f"Error running agent {agent_id}")
            raise HTTPException(status_code=500, detail=str(e))
        
        return AgentRunResponse(
            session_id=request.session_id,
            response=final_response or "",
            events=events,
        )
    
    # =========================================================================
    # Sessions
    # =========================================================================
    
    @app.post("/sessions", response_model=SessionResponse, tags=["Sessions"])
    async def create_session(request: CreateSessionRequest) -> SessionResponse:
        """Create a new session."""
        state = get_state()
        
        if not state.session_service:
            raise HTTPException(status_code=503, detail="Session service not initialized")
        
        try:
            session = await state.session_service.create_session(
                app_name=request.agent_id,
                user_id=request.user_id,
                state=request.metadata or {},
                session_id=request.session_id,
            )
            
            return SessionResponse(
                session_id=session.id,
                agent_id=session.app_name,
                user_id=session.user_id,
                created_at=session.last_update_time,
                metadata=session.state,
            )
        
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))
    
    @app.get("/sessions/{session_id}", response_model=SessionResponse, tags=["Sessions"])
    async def get_session(
        session_id: str,
        agent_id: str = Query(..., description="Agent ID"),
        user_id: str = Query(..., description="User ID"),
    ) -> SessionResponse:
        """Get a session by ID."""
        state = get_state()
        
        if not state.session_service:
            raise HTTPException(status_code=503, detail="Session service not initialized")
        
        session = await state.session_service.get_session(
            app_name=agent_id,
            user_id=user_id,
            session_id=session_id,
        )
        
        if not session:
            raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
        
        return SessionResponse(
            session_id=session.id,
            agent_id=session.app_name,
            user_id=session.user_id,
            created_at=session.last_update_time,
            metadata=session.state,
            events=[EventResponse.from_event(e) for e in session.events],
        )
    
    @app.get("/sessions", response_model=ListSessionsResponse, tags=["Sessions"])
    async def list_sessions(
        agent_id: str = Query(..., description="Agent ID"),
        user_id: Optional[str] = Query(default=None, description="User ID filter"),
    ) -> ListSessionsResponse:
        """List sessions for an agent."""
        state = get_state()
        
        if not state.session_service:
            raise HTTPException(status_code=503, detail="Session service not initialized")
        
        result = await state.session_service.list_sessions(
            app_name=agent_id,
            user_id=user_id,
        )
        
        return ListSessionsResponse(
            sessions=[
                SessionResponse(
                    session_id=s.id,
                    agent_id=s.app_name,
                    user_id=s.user_id,
                    created_at=s.last_update_time,
                    metadata=s.state,
                )
                for s in result.sessions
            ]
        )
    
    @app.delete("/sessions/{session_id}", tags=["Sessions"])
    async def delete_session(
        session_id: str,
        agent_id: str = Query(..., description="Agent ID"),
        user_id: str = Query(..., description="User ID"),
    ) -> dict:
        """Delete a session."""
        state = get_state()
        
        if not state.session_service:
            raise HTTPException(status_code=503, detail="Session service not initialized")
        
        await state.session_service.delete_session(
            app_name=agent_id,
            user_id=user_id,
            session_id=session_id,
        )
        
        return {"deleted": True, "session_id": session_id}
    
    # =========================================================================
    # Tool Invocations
    # =========================================================================
    
    @app.get(
        "/sessions/{session_id}/tool-invocations",
        response_model=list[ToolInvocationResponse],
        tags=["Tool Invocations"],
    )
    async def get_tool_invocations(
        session_id: str,
        agent_id: str = Query(..., description="Agent ID"),
        user_id: str = Query(..., description="User ID"),
        limit: int = Query(default=100, le=1000),
    ) -> list[ToolInvocationResponse]:
        """Get tool invocations for a session."""
        state = get_state()
        
        if not state.session_service:
            raise HTTPException(status_code=503, detail="Session service not initialized")
        
        invocations = await state.session_service.get_tool_invocations(
            app_name=agent_id,
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )
        
        return [ToolInvocationResponse(**inv) for inv in invocations]
    
    # =========================================================================
    # Tools
    # =========================================================================
    
    @app.get("/tools", tags=["Tools"])
    async def list_tools() -> list[dict]:
        """List all registered tools."""
        state = get_state()
        
        if not state.tool_registry:
            return []
        
        return [
            {
                "tool_id": entry.tool_id,
                "name": entry.name,
                "description": entry.description,
                "image": entry.image,
                "port": entry.port,
            }
            for entry in state.tool_registry.list_tool_entries()
        ]


async def _stream_agent_run(
    runner: Any,
    request: AgentRunRequest,
) -> AsyncGenerator[str, None]:
    """Stream agent run events as SSE."""
    import json
    from google.genai import types
    
    new_message = types.Content(
        role="user",
        parts=[types.Part(text=request.input)],
    )
    
    try:
        async for event in runner.run_async(
            user_id=request.user_id,
            session_id=request.session_id,
            new_message=new_message,
        ):
            event_data = EventResponse.from_event(event).model_dump()
            yield f"data: {json.dumps(event_data)}\n\n"
        
        yield "data: [DONE]\n\n"
    
    except Exception as e:
        logger.exception("Error in streaming agent run")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"


def _extract_text_from_content(content: Any) -> str:
    """Extract text from a Content object."""
    if not content or not hasattr(content, "parts"):
        return ""
    
    texts = []
    for part in content.parts or []:
        if hasattr(part, "text") and part.text:
            texts.append(part.text)
    
    return "\n".join(texts)


def get_app() -> FastAPI:
    """Get the default application instance."""
    return create_app()

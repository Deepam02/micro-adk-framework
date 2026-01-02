"""API request/response schemas."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response."""
    
    status: str = Field(..., description="Overall health status")
    database: bool = Field(..., description="Database connection healthy")
    version: str = Field(..., description="API version")


class AgentInfo(BaseModel):
    """Information about an agent."""
    
    agent_id: str = Field(..., description="Agent identifier")
    name: str = Field(..., description="Agent name")
    description: Optional[str] = Field(default=None, description="Agent description")
    tools: List[str] = Field(default_factory=list, description="Tool IDs used by the agent")
    model: str = Field(default="", description="LLM model used")


class ListAgentsResponse(BaseModel):
    """Response for listing agents."""
    
    agents: List[AgentInfo] = Field(default_factory=list)


class CreateSessionRequest(BaseModel):
    """Request to create a new session."""
    
    agent_id: str = Field(..., description="Agent to create session for")
    user_id: str = Field(..., description="User identifier")
    session_id: Optional[str] = Field(default=None, description="Optional custom session ID")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Initial session metadata")


class SessionResponse(BaseModel):
    """Session information response."""
    
    session_id: str = Field(..., description="Session identifier")
    agent_id: str = Field(..., description="Agent identifier")
    user_id: str = Field(..., description="User identifier")
    created_at: float = Field(..., description="Creation timestamp")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Session metadata")
    events: List["EventResponse"] = Field(default_factory=list, description="Session events")


class ListSessionsResponse(BaseModel):
    """Response for listing sessions."""
    
    sessions: List[SessionResponse] = Field(default_factory=list)


class AgentRunRequest(BaseModel):
    """Request to run an agent."""
    
    session_id: str = Field(..., description="Session ID to run in")
    user_id: str = Field(..., description="User identifier")
    input: str = Field(..., description="User input message")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Additional metadata")


class EventResponse(BaseModel):
    """An event from agent execution."""
    
    id: str = Field(..., description="Event identifier")
    author: str = Field(..., description="Event author (user or agent name)")
    timestamp: float = Field(..., description="Event timestamp")
    content_type: str = Field(default="text", description="Content type")
    content: Optional[str] = Field(default=None, description="Text content")
    function_calls: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Function calls in this event"
    )
    function_responses: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Function responses in this event"
    )
    is_final: bool = Field(default=False, description="Whether this is a final response")
    
    @classmethod
    def from_event(cls, event: Any) -> "EventResponse":
        """Create from an ADK Event object."""
        # Extract text content
        content = None
        if event.content and event.content.parts:
            texts = []
            for part in event.content.parts:
                if hasattr(part, "text") and part.text:
                    texts.append(part.text)
            if texts:
                content = "\n".join(texts)
        
        # Extract function calls
        function_calls = []
        for fc in event.get_function_calls():
            function_calls.append({
                "id": fc.id if hasattr(fc, "id") else None,
                "name": fc.name,
                "args": dict(fc.args) if fc.args else {},
            })
        
        # Extract function responses
        function_responses = []
        for fr in event.get_function_responses():
            function_responses.append({
                "id": fr.id if hasattr(fr, "id") else None,
                "name": fr.name,
                "response": dict(fr.response) if fr.response else {},
            })
        
        return cls(
            id=event.id,
            author=event.author,
            timestamp=event.timestamp,
            content=content,
            function_calls=function_calls,
            function_responses=function_responses,
            is_final=event.is_final_response(),
        )


class AgentRunResponse(BaseModel):
    """Response from running an agent."""
    
    session_id: str = Field(..., description="Session ID")
    response: str = Field(..., description="Final agent response text")
    events: List[EventResponse] = Field(default_factory=list, description="All events")


class ToolInvocationResponse(BaseModel):
    """Tool invocation record."""
    
    id: str = Field(..., description="Invocation ID")
    tool_id: str = Field(..., description="Tool identifier")
    tool_name: str = Field(..., description="Tool name")
    invocation_id: str = Field(..., description="Agent invocation ID")
    args: Optional[Dict[str, Any]] = Field(default=None, description="Tool arguments")
    result: Optional[Dict[str, Any]] = Field(default=None, description="Tool result")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    status: str = Field(..., description="Status: pending, success, error")
    duration_ms: Optional[int] = Field(default=None, description="Duration in milliseconds")
    created_at: Optional[str] = Field(default=None, description="Start timestamp")
    completed_at: Optional[str] = Field(default=None, description="Completion timestamp")


# Update forward references
SessionResponse.model_rebuild()

# Challenges & Customizations: Using Google ADK

This document outlines the challenges we faced (or would have faced) using Google ADK directly, and how we solved them through inheritance and customization.

## Summary

| Challenge | ADK Default | Our Solution |
|-----------|-------------|--------------|
| Session Persistence | In-memory only | Extended `BaseSessionService` → `PostgresSessionService` |
| Tool Execution | Local function calls | Extended `BaseTool` → `ContainerTool` (HTTP to containers) |
| Tool Logging | No built-in logging | Created `ToolInvocationLoggerPlugin` using `BasePlugin` |
| Multi-provider LLM | Google AI only | LiteLLM integration via model string pattern |
| Configuration | Hardcoded in Python | YAML-based config with env var overrides |
| HTTP API | No HTTP layer | FastAPI wrapper around ADK Runner |

---

## Challenge 1: Session Persistence

### Problem (if using ADK directly)
ADK's default `InMemorySessionService` loses all data on restart:
```python
# ADK default - sessions lost on restart!
from google.adk.sessions import InMemorySessionService
session_service = InMemorySessionService()
```

### Our Solution
We inherited from `BaseSessionService` and implemented PostgreSQL persistence:

```python
# Our customization
class PostgresSessionService(BaseSessionService):
    """Persists sessions to PostgreSQL."""
    
    async def create_session(self, ...) -> Session:
        # Create ADK Session object
        session = Session(id=..., app_name=..., user_id=...)
        # Persist to PostgreSQL
        await self._save_to_db(session)
        return session
    
    async def append_event(self, session: Session, event: Event):
        # ADK calls this for every message/tool call
        # We intercept and persist to PostgreSQL
        await self._save_event_to_db(session, event)
```

**Files:** `src/micro_adk/core/postgres_session_service.py`

---

## Challenge 2: Containerized Tools

### Problem (if using ADK directly)
ADK tools are Python functions that run in-process:
```python
# ADK default - tool runs in same process
@tool
def calculator(a: float, b: float, operation: str) -> float:
    # This runs in the agent's process
    return a + b
```

This doesn't scale - tools can't be independently deployed, scaled, or written in other languages.

### Our Solution
We extended `BaseTool` to call containerized microservices via HTTP:

```python
# Our customization
class ContainerTool(BaseTool):
    """Calls containerized tools via HTTP."""
    
    async def run_async(self, *, args, tool_context) -> Any:
        # Resolve container URL (Docker/Kubernetes)
        url = self._resolve_service_url()
        
        # Call container's /invoke endpoint
        response = await self._http_client.post(
            f"{url}/invoke",
            json={"args": args, "session_id": ...}
        )
        
        return response.json()["result"]
    
    def _get_declaration(self) -> FunctionDeclaration:
        # Generate JSON Schema from manifest for LLM
        return FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=self.config.parameters,  # From manifest.yaml
        )
```

**Files:** `src/micro_adk/core/container_tool.py`, `src/micro_adk/core/tool_registry.py`

---

## Challenge 3: Tool Invocation Logging

### Problem (if using ADK directly)
ADK doesn't log tool calls to a database - no observability:
```python
# ADK default - tool calls just happen, no logging
runner = Runner(agent=agent, session_service=session_service)
await runner.run_async(...)  # Tool calls not logged anywhere
```

### Our Solution
We used ADK's `BasePlugin` system for non-invasive logging:

```python
# Our customization
class ToolInvocationLoggerPlugin(BasePlugin):
    """Logs all tool calls to PostgreSQL."""
    
    async def before_tool_callback(self, *, tool, tool_args, tool_context):
        # Log start of invocation
        self.record_id = await self.db.log_tool_invocation_start(
            tool_id=tool.tool_id,
            args=tool_args,
            session_id=tool_context.session.id,
        )
        self.start_time = time.time()
        return None  # Continue with tool execution
    
    async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
        # Log completion with result and duration
        await self.db.log_tool_invocation_end(
            record_id=self.record_id,
            result=result,
            duration_ms=(time.time() - self.start_time) * 1000,
        )
        return None  # Use original result
```

**Files:** `src/micro_adk/core/tool_invocation_logger.py`

---

## Challenge 4: Multi-Provider LLM Support

### Problem (if using ADK directly)
ADK is designed for Google's Gemini API:
```python
# ADK default - tightly coupled to Google AI
from google.adk.agents import LlmAgent
agent = LlmAgent(model="gemini-2.0-flash", ...)  # Only Gemini
```

### Our Solution
We use LiteLLM's model string pattern (`provider/model`):

```python
# Our configuration
# config.yaml
litellm:
  default_model: gemini/gemini-2.5-flash  # Google Gemini
  # Or: openai/gpt-4, anthropic/claude-3, etc.

# Agent uses this via LiteLLM routing
agent = LlmAgent(
    model="gemini/gemini-2.5-flash",  # LiteLLM understands this
    ...
)
```

LiteLLM automatically routes to the correct provider based on the prefix.

**Files:** `src/micro_adk/core/config.py`, `config/config.yaml`

---

## Challenge 5: Dynamic Tool Schema

### Problem (if using ADK directly)
ADK expects Python function signatures for tool schemas:
```python
# ADK default - schema from Python function
@tool
def calculator(
    operation: Literal["add", "subtract"],  # Must be Python code
    a: float,
    b: float,
) -> float:
    ...
```

We need tools defined in YAML manifest for container deployment.

### Our Solution
We convert YAML schema to JSON Schema with a Pydantic validator:

```python
# tools/manifest.yaml
- tool_id: calculator
  schema:  # Simple YAML format
    operation:
      type: string
      enum: ["add", "subtract"]
    a:
      type: number

# Our conversion in ToolManifestEntry
class ToolManifestEntry(BaseModel):
    schema_: Dict[str, Any] = Field(alias="schema")
    parameters: Dict[str, Any] = None
    
    @model_validator(mode="after")
    def convert_schema_to_parameters(self):
        # Convert to JSON Schema format
        self.parameters = {
            "type": "object",
            "properties": self.schema_,
            "required": [k for k in self.schema_ if "default" not in self.schema_[k]]
        }
        return self
```

**Files:** `src/micro_adk/core/tool_registry.py`, `tools/manifest.yaml`

---

## Challenge 6: HTTP API Layer

### Problem (if using ADK directly)
ADK is a library, not a service - no HTTP endpoints:
```python
# ADK default - Python library only
runner = Runner(agent=agent, ...)
result = await runner.run_async(...)  # Must call from Python
```

### Our Solution
We wrapped ADK Runner in FastAPI endpoints:

```python
# Our HTTP layer
@app.post("/agents/{agent_id}/run")
async def run_agent(agent_id: str, request: AgentRunRequest):
    # Get or create ADK Runner
    runner = await runner_factory.get_runner(agent_id, agent_loader)
    
    # Run agent through ADK
    async for event in runner.run_async(
        user_id=request.user_id,
        session_id=request.session_id,
        new_message=Content(parts=[Part(text=request.input)]),
    ):
        events.append(event)
    
    return AgentRunResponse(
        session_id=request.session_id,
        response=extract_final_response(events),
        events=events,
    )
```

**Files:** `src/micro_adk/runtime/api/main.py`

---

## What ADK Gave Us for Free

Despite the customizations, ADK provided crucial functionality:

1. **Agent Execution Loop**: The run_async() method handles the LLM→Tool→LLM cycle
2. **Function Calling Protocol**: Proper formatting for LLM function calls
3. **Streaming Support**: Event-based architecture for real-time responses
4. **Tool Schema Generation**: Converts our FunctionDeclaration to LLM format
5. **Conversation State**: Manages message history within sessions
6. **Plugin Architecture**: Clean hooks for logging without modifying core code

---

## Lessons Learned

1. **Inherit, don't fork**: ADK's base classes (`BaseSessionService`, `BaseTool`, `BasePlugin`) are designed for extension
2. **Plugin system is powerful**: Non-invasive logging without touching ADK internals
3. **Model abstraction matters**: LiteLLM's provider/model pattern works well with ADK
4. **Schema conversion is tricky**: YAML to JSON Schema to LLM format requires careful validation
5. **Service discovery is essential**: Containerized tools need proper URL resolution (Docker Compose vs Kubernetes)

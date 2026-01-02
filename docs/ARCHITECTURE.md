# Micro ADK Framework Architecture

## How We Use Google ADK

This framework leverages **Google Agent Development Kit (ADK)** as its core agent runtime. Here's how we integrate with ADK:

### ADK Components Used

| ADK Component | Our Usage |
|---------------|-----------|
| `LlmAgent` | Base class for all agents - provides LLM integration, tool calling, and conversation management |
| `InMemorySessionService` → Extended to `PostgresSessionService` | We extend ADK's session service to persist to PostgreSQL |
| `Runner` | ADK's agent execution engine - handles the agent loop, tool calls, and streaming |
| `BaseTool` | Extended to create `ContainerTool` - our custom tool that calls containerized microservices |
| `BasePlugin` | Used for `ToolInvocationLoggerPlugin` to log tool calls |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HTTP Request                                       │
│                     POST /agents/{agent_id}/run                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Agent Runtime (FastAPI)                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │  Agent Loader   │  │  Runner Factory │  │  PostgresSessionService     │  │
│  │  (YAML→Agent)   │  │  (ADK Runner)   │  │  (ADK Session Extension)    │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
        ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
        │   LiteLLM     │  │  ADK Runner   │  │  PostgreSQL   │
        │   (Models)    │  │  (Execution)  │  │  (Sessions)   │
        │               │  │               │  │               │
        │ gemini-2.5    │  │ ┌───────────┐ │  │ ├─ sessions   │
        │ gpt-4         │  │ │ LlmAgent  │ │  │ ├─ events     │
        │ claude-3      │  │ └───────────┘ │  │ └─ tool_invoc │
        └───────────────┘  └───────────────┘  └───────────────┘
                                    │
                                    │ Tool Calls
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Tool Registry & Router                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │  Tool Registry  │  │  ContainerTool  │  │  Service Resolver           │  │
│  │  (Manifest→Tool)│  │  (ADK BaseTool) │  │  (URL Pattern/Mapping)      │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP /invoke
                                    ▼
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│   tool-calculator    │  │    tool-weather      │  │    tool-custom       │
│   (Container)        │  │    (Container)       │  │    (Container)       │
│                      │  │                      │  │                      │
│   POST /invoke       │  │    POST /invoke      │  │    POST /invoke      │
│   GET /health        │  │    GET /health       │  │    GET /health       │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

## Key Design Decisions

### 1. ADK Agent vs Custom Agent Logic

**We use ADK's `LlmAgent` directly** - no custom agent logic:

```python
# agents/assistant/agent.py
from google.adk.agents import LlmAgent

# This is all you need! ADK handles:
# - LLM communication
# - Tool calling protocol
# - Conversation management
# - Function calling schema generation

root_agent = LlmAgent(
    name="assistant",
    model="gemini/gemini-2.5-flash",  # Via LiteLLM
    instruction="You are a helpful assistant...",
    tools=[calculator, weather],  # ContainerTools
)
```

**Why ADK?**
- Battle-tested agent loop
- Built-in streaming support
- Proper function calling protocol
- Session management abstractions
- Plugin system for extensibility

### 2. Custom Tool Implementation

We extend ADK's `BaseTool` to create `ContainerTool`:

```python
class ContainerTool(BaseTool):
    """Calls containerized microservices via HTTP."""
    
    async def run_async(self, *, args, tool_context):
        # 1. Resolve service URL (Docker/K8s)
        url = self._get_service_url()
        
        # 2. Call container's /invoke endpoint
        response = await self._http_client.post(
            f"{url}/invoke",
            json={"args": args, "session_id": ...}
        )
        
        # 3. Return result to ADK
        return response.json()["result"]
```

### 3. Session Management with PostgreSQL

ADK provides `InMemorySessionService`. We extend it to persist:

```python
class PostgresSessionService(BaseSessionService):
    """Persists ADK sessions to PostgreSQL."""
    
    async def create_session(self, ...):
        # Create in ADK format, persist to Postgres
        
    async def append_event(self, session, event):
        # ADK calls this for each message/tool call
        # We persist to 'events' table
```

### 4. LiteLLM Integration

All LLM calls go through LiteLLM for model abstraction:

```python
# config.yaml
litellm:
  default_model: gemini/gemini-2.5-flash  # Google Gemini
  # Or: openai/gpt-4, anthropic/claude-3, etc.
```

ADK's LlmAgent uses the model string, and LiteLLM routes to the correct provider.

## Session & Context Management

### How Sessions Work

```
Session (PostgreSQL)
├── id: UUID
├── app_name: "assistant" (agent_id)
├── user_id: "user-123"
├── state: {} (ADK session state)
└── Events (conversation history)
    ├── Event 1: user message "What is 25 * 17?"
    ├── Event 2: assistant + function_call(calculator)
    ├── Event 3: function_response(result: 425)
    └── Event 4: assistant "25 times 17 is 425"
```

### Context Preservation

**Yes, chat history IS preserved!** Here's how:

1. **Create Session**: Returns `session_id`
2. **Send Message**: Events stored in PostgreSQL
3. **Next Message**: ADK loads all previous events as context
4. **LLM sees full history**: Enables multi-turn conversations

```bash
# First message
curl -X POST /agents/assistant/run \
  -d '{"session_id": "abc-123", "input": "My name is Alice"}'
# Response: "Nice to meet you, Alice!"

# Second message (same session_id)
curl -X POST /agents/assistant/run \
  -d '{"session_id": "abc-123", "input": "What is my name?"}'
# Response: "Your name is Alice!" (remembers context!)
```

## Plug and Play: Adding New Components

### Adding a New Agent

See [docs/ADD_AGENT.md](./ADD_AGENT.md)

### Adding a New Tool

See [docs/ADD_TOOL.md](./ADD_TOOL.md)

## What ADK Handles vs What We Handle

| Responsibility | ADK | Our Framework |
|----------------|-----|---------------|
| Agent execution loop | ✅ | |
| LLM communication | ✅ | |
| Function calling protocol | ✅ | |
| Tool schema generation | ✅ | |
| Streaming responses | ✅ | |
| Session abstraction | ✅ | |
| Session persistence | | ✅ (PostgreSQL) |
| Tool containerization | | ✅ (ContainerTool) |
| Service discovery | | ✅ (Docker/K8s) |
| Tool orchestration | | ✅ (Kubernetes) |
| HTTP API layer | | ✅ (FastAPI) |
| Auto-scaling | | ✅ (HPA) |

## Improvements & Future Work

### Current Limitations

1. **Tool invocations table empty**: The plugin logs to events, but we should also populate `tool_invocations` table for easier querying
2. **No streaming in HTTP API**: ADK supports streaming but our REST endpoint returns complete response
3. **Single agent per request**: No multi-agent orchestration yet
4. **No tool result caching**: Same tool calls aren't cached

### Recommended Improvements

1. **Add SSE/WebSocket streaming**:
   ```python
   @app.post("/agents/{agent_id}/stream")
   async def stream_agent(request):
       async for event in runner.run_async(...):
           yield f"data: {event.json()}\n\n"
   ```

2. **Populate tool_invocations table**:
   ```python
   # In ToolInvocationLoggerPlugin
   async def after_tool_callback(self, ...):
       await self.db.execute(
           "INSERT INTO tool_invocations ..."
       )
   ```

3. **Add tool result caching**:
   ```python
   @cached(ttl=300)
   async def invoke_tool(tool_id, args):
       ...
   ```

4. **Multi-agent support**:
   ```python
   # Use ADK's sub_agents feature
   root_agent = LlmAgent(
       name="orchestrator",
       sub_agents=[research_agent, code_agent],
   )
   ```

5. **Observability**:
   - OpenTelemetry tracing
   - Prometheus metrics
   - Structured logging with correlation IDs

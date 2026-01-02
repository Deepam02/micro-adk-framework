# Micro ADK Framework

A micro-framework that runs independent Google ADK agents as HTTP APIs, with tools deployed as containerized microservices featuring automatic autoscaling.

## ✅ Development Status

| Feature | Status | Notes |
|---------|--------|-------|
| Agent Runtime (FastAPI) | ✅ Done | Full REST API |
| Session Management | ✅ Done | PostgreSQL persistence |
| Tool Manifest | ✅ Done | YAML schema → JSON Schema conversion |
| ContainerTool | ✅ Done | HTTP-based tool invocation |
| Tool Router | ✅ Done | Service resolution + retries |
| Calculator Tool | ✅ Done | Sample tool |
| Weather Tool | ✅ Done | Sample tool |
| Docker Compose | ✅ Done | One-command local dev |
| LiteLLM Integration | ✅ Done | Multi-model support |
| Events Logging | ✅ Done | Full conversation history |
| Kubernetes Orchestrator | ✅ Done | Deployment + HPA |
| Helm Chart | ✅ Done | Production deployment |
| Tool Invocations Table | ⚠️ Partial | Logged in events, not separate table |
| SSE Streaming | 🔜 Planned | ADK supports it |

## Documentation

- **[Architecture & ADK Usage](docs/ARCHITECTURE.md)** - How we use Google ADK
- **[Add a New Tool](docs/ADD_TOOL.md)** - Guide for adding containerized tools
- **[Add a New Agent](docs/ADD_AGENT.md)** - Guide for creating agents

## Features

- **Agent-as-API**: Each agent is accessible via REST endpoints
- **Tools as Containers**: Every tool runs in its own container behind a standard `/invoke` API
- **Internal Orchestration + Autoscaling**: Framework deploys tools and configures HPA automatically
- **One-command Deployment**: Local dev via Docker Compose; production via Helm/Kubernetes
- **Session Persistence**: All conversations and tool calls stored in PostgreSQL
- **LiteLLM Integration**: All LLM calls go through LiteLLM for model abstraction

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Agent Runtime                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  FastAPI    │  │   ADK       │  │  PostgresSessionService │  │
│  │  Server     │──│   Runner    │──│  (sessions + events +   │  │
│  │             │  │             │  │   tool_invocations)     │  │
│  └─────────────┘  └──────┬──────┘  └─────────────────────────┘  │
│                          │                                       │
│  ┌───────────────────────┼───────────────────────────────────┐  │
│  │              Tool Registry + Router                        │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐│  │
│  │  │ToolManifest │  │ContainerTool│  │  ToolRouter         ││  │
│  │  │  (YAML)     │──│  (ADK Tool) │──│  (HTTP Client)      ││  │
│  │  └─────────────┘  └─────────────┘  └─────────────────────┘│  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐
                    │   Tool Orchestrator  │
                    │   (Kubernetes HPA)   │
                    └──────────┬──────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        ▼                      ▼                      ▼
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Tool Pod    │      │  Tool Pod    │      │  Tool Pod    │
│  Calculator  │      │  Weather     │      │  Custom...   │
│  /invoke     │      │  /invoke     │      │  /invoke     │
└──────────────┘      └──────────────┘      └──────────────┘
```

## Quick Start

### Prerequisites

- Python 3.10+
- Docker & Docker Compose
- PostgreSQL (or use Docker Compose)
- Kubernetes cluster (optional, for production)

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd micro-adk-framework

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install the framework
pip install -e .
```

### Local Development with Docker Compose

```bash
# Start all services (Postgres, Runtime, Tools)
docker-compose up -d

# View logs
docker-compose logs -f runtime

# Run a test request
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "assistant", "user_id": "user1"}'

curl -X POST http://localhost:8000/agents/assistant/run \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<session_id>", "user_id": "user1", "input": "What is 25 * 4?"}'
```

### Initialize a New Project

```bash
# Create a new project structure
micro-adk init my-project
cd my-project

# Edit configuration
# - config/config.yaml: Database, LiteLLM, server settings
# - tools/manifest.yaml: Define your tools
# - agents/: Create agent configurations

# Run the server
micro-adk serve --config config/config.yaml
```

## Configuration

### Framework Configuration (`config/config.yaml`)

```yaml
database:
  url: postgresql+asyncpg://user:pass@host:5432/db
  pool_size: 5

litellm:
  api_base: null  # Optional LiteLLM proxy
  default_model: gemini/gemini-2.0-flash  # provider/model format
  timeout: 30

server:
  host: 0.0.0.0
  port: 8000

agents_dir: ./agents
tools_manifest_path: ./tools/manifest.yaml
```

### Tool Manifest (`tools/manifest.yaml`)

```yaml
tools:
  - tool_id: calculator
    name: calculator
    description: Performs arithmetic operations
    image: micro-adk/tool-calculator:latest
    port: 8080
    schema:
      operation:
        type: string
        enum: ["add", "subtract", "multiply", "divide"]
      a:
        type: number
      b:
        type: number
    autoscaling:
      enabled: true
      min_replicas: 1
      max_replicas: 10
      target_cpu_percent: 80
```

### Agent Configuration (`agents/<agent_id>/agent.yaml`)

```yaml
agent_id: my-agent
name: My Agent
description: An example agent

model: gpt-4
instruction: |
  You are a helpful assistant.

tools:
  - calculator
  - weather

sub_agents: []
```

## API Reference

### Health Check

```
GET /health
```

### Agents

```
GET  /agents                    # List all agents
GET  /agents/{agent_id}         # Get agent info
POST /agents/{agent_id}/run     # Run agent with input
```

### Sessions

```
POST   /sessions                                    # Create session
GET    /sessions/{session_id}?agent_id=&user_id=   # Get session
GET    /sessions?agent_id=                          # List sessions
DELETE /sessions/{session_id}?agent_id=&user_id=   # Delete session
```

### Tool Invocations

```
GET /sessions/{session_id}/tool-invocations?agent_id=&user_id=
```

### Run Agent Request

```json
{
  "session_id": "string",
  "user_id": "string",
  "input": "User message",
  "metadata": {}
}
```

### Run Agent Response

```json
{
  "session_id": "string",
  "response": "Agent response text",
  "events": [
    {
      "id": "event-id",
      "author": "assistant",
      "timestamp": 1234567890.0,
      "content": "...",
      "function_calls": [],
      "function_responses": [],
      "is_final": true
    }
  ]
}
```

## Creating Custom Tools

Tools are containerized services that expose a `/invoke` endpoint:

```python
# main.py
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional

app = FastAPI()

class InvokeRequest(BaseModel):
    args: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None

class InvokeResponse(BaseModel):
    result: Any = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.post("/invoke")
async def invoke(request: InvokeRequest) -> InvokeResponse:
    # Your tool logic here
    result = do_something(request.args)
    return InvokeResponse(result=result)
```

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn
COPY main.py .
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

## Kubernetes Deployment

### Using Helm

```bash
# Add required dependency
helm repo add bitnami https://charts.bitnami.com/bitnami

# Install with custom values
helm install micro-adk ./helm/micro-adk \
  --set apiKeys.openai="sk-..." \
  --set postgresql.auth.password="secure-password"

# Or with a values file
helm install micro-adk ./helm/micro-adk -f my-values.yaml
```

### Deploy Tools

```bash
# Deploy all tools from manifest
micro-adk deploy --config config/config.yaml --namespace default

# Undeploy all tools
micro-adk undeploy --config config/config.yaml --namespace default
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `MICRO_ADK_DATABASE_URL` | PostgreSQL connection URL |
| `MICRO_ADK_AGENTS_DIR` | Path to agents directory |
| `MICRO_ADK_TOOLS_MANIFEST` | Path to tool manifest |
| `GEMINI_API_KEY` | Google Gemini API key for LiteLLM |
| `OPENAI_API_KEY` | OpenAI API key for LiteLLM |
| `ANTHROPIC_API_KEY` | Anthropic API key for LiteLLM |
| `LITELLM_API_BASE` | Custom LiteLLM proxy URL |

## Project Structure

```
micro-adk-framework/
├── src/micro_adk/
│   ├── core/                 # Core components
│   │   ├── config.py         # Configuration management
│   │   ├── container_tool.py # ContainerTool (ADK BaseTool extension)
│   │   ├── postgres_session_service.py  # PostgreSQL sessions
│   │   ├── tool_invocation_logger.py    # Tool call logging
│   │   └── tool_registry.py  # Tool manifest management
│   ├── runtime/              # Agent runtime
│   │   ├── api/              # FastAPI application
│   │   └── services/         # Runtime services
│   ├── router/               # Tool routing
│   │   ├── tool_router.py    # HTTP client for tools
│   │   └── service_discovery.py  # K8s/Docker discovery
│   ├── orchestrator/         # Kubernetes orchestration
│   │   ├── kubernetes_orchestrator.py
│   │   ├── deployment_manager.py
│   │   └── autoscaler.py
│   └── cli.py                # Command-line interface
├── samples/tools/            # Sample tool implementations
├── config/                   # Default configuration
├── agents/                   # Agent definitions
├── tools/                    # Tool manifest
├── migrations/               # Database migrations
├── helm/                     # Helm chart
├── docker-compose.yaml       # Local development
└── Dockerfile                # Runtime container
```

## License

MIT

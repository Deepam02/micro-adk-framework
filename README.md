# Micro ADK Framework

A micro-framework for running Google ADK agents as HTTP APIs with containerized tools.

## Quick Start

### 1. Configure API Key

Create a `.env` file:

```bash
# For Google Gemini (default)
GEMINI_API_KEY=your-gemini-api-key

# OR for OpenAI
OPENAI_API_KEY=your-openai-api-key

# OR for Anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key
```

### 2. Start Services

```bash
docker-compose up -d
```

### 3. Test It

```bash
# Create a session
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "assistant", "user_id": "user1"}'

# Run the agent (replace SESSION_ID)
curl -X POST http://localhost:8000/agents/assistant/run \
  -H "Content-Type: application/json" \
  -d '{"session_id": "SESSION_ID", "user_id": "user1", "input": "What is 25 * 4?"}'
```

---

## Using Different LLM Providers

### Google Gemini (Default)
```bash
GEMINI_API_KEY=your-key
```
Model: `gemini/gemini-2.5-flash` (default, no changes needed)

### OpenAI
```bash
OPENAI_API_KEY=your-key
```
Edit `agents/assistant/agent.yaml`:
```yaml
model: openai/gpt-4o
```

### Anthropic
```bash
ANTHROPIC_API_KEY=your-key
```
Edit `agents/assistant/agent.yaml`:
```yaml
model: anthropic/claude-3-sonnet-20240229
```

After changing model: `docker-compose restart runtime`

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/sessions` | POST | Create session |
| `/sessions/{id}` | GET | Get session history |
| `/agents` | GET | List agents |
| `/agents/{id}/run` | POST | Run agent |

---

## Adding a New Tool

1. Create `samples/tools/my-tool/main.py`:

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class InvokeRequest(BaseModel):
    args: dict

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/invoke")
def invoke(request: InvokeRequest):
    result = do_something(request.args)
    return {"result": result}
```

2. Create `samples/tools/my-tool/Dockerfile`:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

3. Add to `tools/manifest.yaml`:

```yaml
- tool_id: my-tool
  name: my_tool
  description: What the tool does
  image: micro-adk/my-tool:latest
  port: 8080
  schema:
    param1:
      type: string
```

4. Add to `docker-compose.yaml`:

```yaml
tool-my-tool:
  build: ./samples/tools/my-tool
  expose:
    - "8080"
```

5. Add to `agents/assistant/agent.yaml` tools list.

6. Rebuild: `docker-compose up -d --build`

---

## Adding a New Agent

Create `agents/my-agent/agent.yaml`:

```yaml
agent_id: my-agent
name: My Agent
model: gemini/gemini-2.5-flash
instruction: |
  You are a helpful assistant.
tools:
  - calculator
  - weather
```

Restart: `docker-compose restart runtime`

---

## Available Tools

| Tool | Description |
|------|-------------|
| `calculator` | Arithmetic: add, subtract, multiply, divide |
| `weather` | Get real weather data (via WeatherAPI.com) |
| `text_utils` | Text ops: word_count, reverse, uppercase, lowercase |

---

## Project Structure

```
micro-adk-framework/
├── agents/                  # Agent configurations
│   └── assistant/           # Default assistant agent
├── samples/tools/           # Tool implementations
│   ├── calculator/          # Calculator tool
│   ├── weather/             # Weather tool (real API)
│   └── text_utils/          # Text utilities tool
├── tools/manifest.yaml      # Tool registry
├── config/config.yaml       # Framework config
├── examples/                # Example agent templates
├── src/micro_adk/           # Framework source code
├── docs/                    # Documentation
├── helm/                    # Kubernetes Helm chart
├── migrations/              # Database migrations
└── docker-compose.yaml      # Local dev setup
```

---

## Troubleshooting

```bash
# View logs
docker-compose logs runtime

# Check status
docker-compose ps

# Reset
docker-compose down -v && docker-compose up -d --build
```

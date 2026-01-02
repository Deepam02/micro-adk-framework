# Adding a New Tool

This guide explains how to add a new containerized tool to the Micro ADK Framework.

## Overview

Tools in this framework are **containerized microservices** that:
- Run in their own Docker container
- Expose a standard `/invoke` endpoint
- Are called by agents via HTTP

## Step 1: Create the Tool Service

### 1.1 Create Directory Structure

```bash
samples/tools/my_tool/
├── Dockerfile
├── main.py
└── requirements.txt
```

### 1.2 Implement the Tool Service

Create `main.py`:

```python
"""My Custom Tool - A tool that does something useful."""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional

app = FastAPI(title="My Tool")


class InvokeRequest(BaseModel):
    """Standard request format for tool invocation."""
    session_id: str
    tool_name: str
    args: Dict[str, Any]
    metadata: Dict[str, Any] = {}


class InvokeResponse(BaseModel):
    """Standard response format."""
    result: Optional[Any] = None
    error: Optional[str] = None


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post("/invoke")
async def invoke(request: InvokeRequest) -> InvokeResponse:
    """Main tool invocation endpoint."""
    try:
        # Extract your arguments
        arg1 = request.args.get("arg1")
        arg2 = request.args.get("arg2")
        
        # Do your tool logic here
        result = do_something(arg1, arg2)
        
        return InvokeResponse(result=result)
    except Exception as e:
        return InvokeResponse(error=str(e))


def do_something(arg1, arg2):
    """Your actual tool logic."""
    # Implement your tool's functionality
    return {"output": f"Processed {arg1} and {arg2}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

### 1.3 Create Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY main.py .

# Expose port
EXPOSE 8080

# Run the service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 1.4 Create requirements.txt

```
fastapi>=0.100.0
uvicorn>=0.22.0
pydantic>=2.0.0
```

## Step 2: Register in Tool Manifest

Edit `tools/manifest.yaml`:

```yaml
tools:
  # ... existing tools ...
  
  # Add your new tool
  - tool_id: my_tool
    name: my_tool_name  # Name the LLM will see
    description: |
      A clear description of what this tool does.
      The LLM uses this to decide when to call the tool.
      Be specific about inputs and outputs.
    image: micro-adk/tool-my-tool:latest
    port: 8080
    health_check_path: /health
    
    # Define the parameters schema
    # This is converted to JSON Schema for the LLM
    schema:
      arg1:
        type: string
        description: Description of first argument
      arg2:
        type: number
        description: Description of second argument
      optional_arg:
        type: string
        description: An optional argument
        default: "default_value"
    
    # Resource limits (for Kubernetes)
    resources:
      cpu_request: "50m"
      cpu_limit: "200m"
      memory_request: "64Mi"
      memory_limit: "128Mi"
    
    # Autoscaling configuration (for Kubernetes)
    autoscaling:
      enabled: true
      min_replicas: 1
      max_replicas: 5
      target_cpu_percent: 80
```

## Step 3: Add to Docker Compose (Development)

Edit `docker-compose.yaml`:

```yaml
services:
  # ... existing services ...
  
  tool-my-tool:
    build:
      context: ./samples/tools/my_tool
      dockerfile: Dockerfile
    ports:
      - "8083:8080"  # Use a unique port
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 10s
      timeout: 5s
      retries: 3
```

## Step 4: Enable Tool for an Agent

Edit your agent's YAML (e.g., `agents/assistant/agent.yaml`):

```yaml
name: assistant
model: gemini/gemini-2.5-flash
instruction: |
  You are a helpful assistant with access to various tools.
  
tools:
  - calculator
  - get_weather
  - my_tool  # Add your tool_id here
```

## Step 5: Test the Tool

### 5.1 Rebuild and Start

```bash
docker-compose up -d --build
```

### 5.2 Verify Tool is Registered

```bash
curl http://localhost:8000/tools | jq
```

Should show your tool in the list.

### 5.3 Test via Agent

```bash
# Create session
SESSION=$(curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "assistant", "user_id": "test"}' | jq -r '.session_id')

# Ask agent to use your tool
curl -X POST http://localhost:8000/agents/assistant/run \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION\",
    \"user_id\": \"test\",
    \"input\": \"Use my_tool with arg1='hello' and arg2=42\"
  }" | jq
```

## Schema Reference

### Parameter Types

```yaml
schema:
  # String
  name:
    type: string
    description: A text value
  
  # Number (integer or float)
  count:
    type: number
    description: A numeric value
  
  # Integer only
  age:
    type: integer
    description: An integer value
  
  # Boolean
  enabled:
    type: boolean
    description: True or false
  
  # Enum (restricted values)
  status:
    type: string
    enum: ["pending", "active", "completed"]
    description: Status value
  
  # With default (makes it optional)
  format:
    type: string
    default: "json"
    description: Output format
```

### Full Tool Manifest Entry Schema

```yaml
- tool_id: string          # Required: Unique identifier
  name: string             # Required: LLM-visible name
  description: string      # Required: LLM-visible description
  image: string            # Required: Docker image
  port: integer            # Default: 8080
  health_check_path: string # Default: /health
  timeout: float           # Default: 30.0 (seconds)
  max_retries: integer     # Default: 3
  
  schema:                  # Tool parameters
    param_name:
      type: string|number|integer|boolean
      description: string
      enum: [values]       # Optional
      default: value       # Optional (makes param optional)
  
  env:                     # Environment variables
    API_KEY: "${MY_API_KEY}"
  
  resources:
    cpu_request: "50m"
    cpu_limit: "200m"
    memory_request: "64Mi"
    memory_limit: "128Mi"
  
  autoscaling:
    enabled: true
    min_replicas: 1
    max_replicas: 5
    target_cpu_percent: 80
```

## Example: Web Scraper Tool

### main.py

```python
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, Optional
import httpx

app = FastAPI(title="Web Scraper Tool")


class InvokeRequest(BaseModel):
    session_id: str
    tool_name: str
    args: Dict[str, Any]
    metadata: Dict[str, Any] = {}


class InvokeResponse(BaseModel):
    result: Optional[Any] = None
    error: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/invoke")
async def invoke(request: InvokeRequest) -> InvokeResponse:
    try:
        url = request.args.get("url")
        if not url:
            return InvokeResponse(error="URL is required")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            
        return InvokeResponse(result={
            "status_code": response.status_code,
            "content_length": len(response.text),
            "content_preview": response.text[:500],
        })
    except Exception as e:
        return InvokeResponse(error=str(e))
```

### manifest.yaml entry

```yaml
- tool_id: web_scraper
  name: scrape_webpage
  description: |
    Fetches a webpage and returns its content.
    Use this to get information from websites.
  image: micro-adk/tool-web-scraper:latest
  port: 8080
  
  schema:
    url:
      type: string
      description: The URL of the webpage to scrape
```

## Troubleshooting

### Tool not being called by LLM

1. Check the `description` is clear and specific
2. Verify schema parameters match what LLM should provide
3. Check logs: `docker-compose logs runtime`

### Connection refused

1. Verify tool container is running: `docker-compose ps`
2. Check health endpoint: `curl http://localhost:808X/health`
3. Verify service URL pattern in `config.yaml`:
   ```yaml
   router:
     service_url_pattern: "http://tool-{tool_id}:8080"
   ```

### Schema not working

1. Ensure `schema:` is properly indented in manifest
2. Check types are valid: `string`, `number`, `integer`, `boolean`
3. Restart runtime after manifest changes

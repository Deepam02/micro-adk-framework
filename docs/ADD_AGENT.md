# Adding a New Agent

This guide explains how to add a new agent to the Micro ADK Framework.

## Overview

Agents in this framework are **Google ADK LlmAgents** that:
- Are defined via YAML configuration OR Python code
- Can use any containerized tools from the manifest
- Support any LLM via LiteLLM (Gemini, OpenAI, Anthropic, etc.)

## Method 1: YAML-Only Agent (Recommended)

The simplest way to add an agent - no Python code required.

### Step 1: Create Agent Directory

```bash
mkdir -p agents/my_agent
```

### Step 2: Create agent.yaml

Create `agents/my_agent/agent.yaml`:

```yaml
# Agent Configuration
name: my_agent
model: gemini/gemini-2.5-flash  # Or openai/gpt-4, anthropic/claude-3, etc.

# System instruction for the agent
instruction: |
  You are a specialized assistant for [your use case].
  
  Your capabilities:
  - Capability 1
  - Capability 2
  
  Guidelines:
  - Be helpful and concise
  - Use tools when appropriate
  - Always explain your reasoning

# Tools this agent can use (reference tool_ids from manifest.yaml)
tools:
  - calculator
  - get_weather
  # Add more tool_ids as needed

# Optional: Agent description (for documentation)
description: |
  This agent helps users with [specific task].
  It has access to calculator and weather tools.
```

### Step 3: Test the Agent

```bash
# Restart to load new agent
docker-compose restart runtime

# Verify agent is available
curl http://localhost:8000/agents | jq

# Create session and test
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my_agent", "user_id": "test"}'

curl -X POST http://localhost:8000/agents/my_agent/run \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<session_id>",
    "user_id": "test",
    "input": "Hello, what can you do?"
  }'
```

## Method 2: Python Agent (Advanced)

For complex agents with custom logic, callbacks, or sub-agents.

### Step 1: Create Agent Directory

```bash
mkdir -p agents/advanced_agent
```

### Step 2: Create __init__.py

Create `agents/advanced_agent/__init__.py`:

```python
"""Advanced Agent with custom logic."""

from google.adk.agents import LlmAgent

# The agent loader looks for 'root_agent' variable
root_agent = None  # Will be set by create_agent()


def create_agent(tools: list):
    """Create the agent with provided tools.
    
    Args:
        tools: List of ContainerTool instances from the manifest
        
    Returns:
        Configured LlmAgent
    """
    global root_agent
    
    # Filter tools you want
    calculator = next((t for t in tools if t.name == "calculator"), None)
    weather = next((t for t in tools if t.name == "get_weather"), None)
    
    agent_tools = [t for t in [calculator, weather] if t is not None]
    
    root_agent = LlmAgent(
        name="advanced_agent",
        model="gemini/gemini-2.5-flash",
        instruction="""You are an advanced assistant with special capabilities.
        
        You can:
        - Perform calculations
        - Check weather
        - Chain multiple tool calls together
        
        Always think step by step.""",
        tools=agent_tools,
    )
    
    return root_agent
```

### Step 3: Create agent.yaml (metadata)

Create `agents/advanced_agent/agent.yaml`:

```yaml
name: advanced_agent
model: gemini/gemini-2.5-flash
description: Advanced agent with Python customization
python_module: true  # Tells loader to use __init__.py

tools:
  - calculator
  - get_weather
```

## Agent Configuration Reference

### agent.yaml Schema

```yaml
# Required fields
name: string              # Unique agent identifier (used in API paths)
model: string             # LiteLLM model string (provider/model)
instruction: string       # System prompt for the agent

# Optional fields
description: string       # Human-readable description
tools: list[string]       # List of tool_ids from manifest.yaml
python_module: boolean    # If true, loads from __init__.py

# Advanced (for Python agents)
sub_agents: list[string]  # Names of sub-agents for multi-agent setups
generate_content_config:  # LLM generation parameters
  temperature: 0.7
  max_output_tokens: 2048
  top_p: 0.95
```

### Model Options

```yaml
# Google Gemini (via LiteLLM)
model: gemini/gemini-2.5-flash
model: gemini/gemini-2.0-pro

# OpenAI (requires OPENAI_API_KEY)
model: openai/gpt-4
model: openai/gpt-4-turbo
model: openai/gpt-3.5-turbo

# Anthropic (requires ANTHROPIC_API_KEY)
model: anthropic/claude-3-opus
model: anthropic/claude-3-sonnet

# Local models via Ollama
model: ollama/llama2
model: ollama/mistral
```

## Example Agents

### 1. Math Tutor Agent

`agents/math_tutor/agent.yaml`:

```yaml
name: math_tutor
model: gemini/gemini-2.5-flash

instruction: |
  You are a patient and encouraging math tutor.
  
  Your approach:
  1. First understand what the student is trying to solve
  2. Guide them through the problem step by step
  3. Use the calculator to verify answers
  4. Explain concepts in simple terms
  
  Never just give the answer - help them learn!

tools:
  - calculator

description: A math tutoring agent that helps students learn
```

### 2. Research Assistant Agent

`agents/researcher/agent.yaml`:

```yaml
name: researcher
model: gemini/gemini-2.5-flash

instruction: |
  You are a research assistant that helps gather information.
  
  When asked about a topic:
  1. Break down the query into sub-questions
  2. Use available tools to gather data
  3. Synthesize findings into a clear summary
  4. Cite sources and provide context
  
  Be thorough but concise.

tools:
  - web_scraper
  - get_weather

description: Research assistant for information gathering
```

### 3. Multi-Tool Agent (Python)

`agents/multi_tool/__init__.py`:

```python
"""Multi-tool agent that chains operations."""

from google.adk.agents import LlmAgent

root_agent = None


def create_agent(tools: list):
    global root_agent
    
    root_agent = LlmAgent(
        name="multi_tool",
        model="gemini/gemini-2.5-flash",
        instruction="""You are a capable assistant with multiple tools.
        
        You can chain tools together. For example:
        - Check weather, then calculate temperature conversions
        - Perform multi-step calculations
        
        Think about which tools to use and in what order.""",
        tools=tools,  # Use all available tools
    )
    
    return root_agent
```

## Testing Your Agent

### Using curl

```bash
# Create session
SESSION=$(curl -s -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my_agent", "user_id": "test"}' | jq -r '.session_id')

echo "Session: $SESSION"

# Send message
curl -X POST http://localhost:8000/agents/my_agent/run \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION\",
    \"user_id\": \"test\",
    \"input\": \"Hello! What can you help me with?\"
  }" | jq '.response'
```

### Using Python

```python
import requests

BASE_URL = "http://localhost:8000"

# Create session
session = requests.post(f"{BASE_URL}/sessions", json={
    "agent_id": "my_agent",
    "user_id": "test"
}).json()

session_id = session["session_id"]

# Chat with agent
response = requests.post(f"{BASE_URL}/agents/my_agent/run", json={
    "session_id": session_id,
    "user_id": "test",
    "input": "What's 25 times 17?"
}).json()

print(response["response"])
```

## Multi-Agent Setup (Advanced)

ADK supports sub-agents for complex workflows:

```python
# agents/orchestrator/__init__.py

from google.adk.agents import LlmAgent

def create_agent(tools: list):
    # Create specialized sub-agents
    math_agent = LlmAgent(
        name="math_specialist",
        model="gemini/gemini-2.5-flash",
        instruction="You are a math specialist...",
        tools=[t for t in tools if t.name == "calculator"],
    )
    
    weather_agent = LlmAgent(
        name="weather_specialist", 
        model="gemini/gemini-2.5-flash",
        instruction="You are a weather specialist...",
        tools=[t for t in tools if t.name == "get_weather"],
    )
    
    # Create orchestrator that delegates
    root_agent = LlmAgent(
        name="orchestrator",
        model="gemini/gemini-2.5-flash",
        instruction="""You coordinate between specialists.
        
        For math questions, delegate to math_specialist.
        For weather questions, delegate to weather_specialist.
        """,
        sub_agents=[math_agent, weather_agent],
    )
    
    return root_agent
```

## Troubleshooting

### Agent not loading

1. Check YAML syntax: `python -c "import yaml; yaml.safe_load(open('agent.yaml'))"`
2. Verify agent directory is under `agents/`
3. Check logs: `docker-compose logs runtime`

### Tools not available

1. Ensure tool_ids in agent.yaml match manifest.yaml
2. Restart runtime after manifest changes
3. Check tool is registered: `curl http://localhost:8000/tools`

### Model errors

1. Verify API key is set: `echo $GEMINI_API_KEY`
2. Check model string format: `provider/model`
3. Review LiteLLM docs for supported models

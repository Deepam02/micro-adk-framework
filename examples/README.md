# Example Agents

This folder contains example agent configurations you can use as templates.

## Available Examples

### 1. Math Tutor (`math_tutor/agent.yaml`)
A math-focused agent that helps solve equations and explains mathematical concepts.

### 2. Writing Assistant (`writing_assistant/agent.yaml`)
An agent specialized in helping with writing tasks - grammar, style, and text analysis.

### 3. Weather Bot (`weather_bot/agent.yaml`)
A simple agent focused on weather queries.

## Using Examples

To use an example agent:

1. Copy the agent folder to `agents/`:
   ```bash
   cp -r examples/math_tutor agents/
   ```

2. Restart the runtime:
   ```bash
   docker-compose restart runtime
   ```

3. Test it:
   ```bash
   curl -X POST http://localhost:8000/agents/math_tutor/run \
     -H "Content-Type: application/json" \
     -d '{"session_id": "your-session-id", "user_id": "user1", "input": "What is the square root of 144?"}'
   ```

## Creating Your Own Agent

Create `agents/my-agent/agent.yaml`:

```yaml
agent_id: my-agent
name: My Custom Agent
model: gemini/gemini-2.5-flash

instruction: |
  Your agent personality and behavior instructions here.

tools:
  - calculator
  - weather
  - text_utils
```

# Example Agents

Example agent configurations for different models and use cases.

---

## Quick Start: Using Examples

### Step 1: Copy agent to `agents/` folder

```bash
# Windows
copy examples\gpt_assistant agents\gpt_assistant

# Linux/Mac
cp -r examples/gpt_assistant agents/
```

### Step 2: Set API key in `.env`

```bash
# For GPT agents
OPENAI_API_KEY=your-openai-key

# For Claude agents
ANTHROPIC_API_KEY=your-anthropic-key

# For Gemini agents (default)
GEMINI_API_KEY=your-gemini-key
```

### Step 3: Restart runtime

```bash
docker-compose restart runtime
```

### Step 4: Test it

```bash
# Create session
curl -X POST http://localhost:8000/sessions \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "gpt_assistant", "user_id": "user1"}'

# Run agent (replace SESSION_ID)
curl -X POST http://localhost:8000/agents/gpt_assistant/run \
  -H "Content-Type: application/json" \
  -d '{"session_id": "SESSION_ID", "user_id": "user1", "input": "Hello!"}'
```

---

## Available Examples

| Agent | Model | Description |
|-------|-------|-------------|
| `gpt_assistant` | OpenAI GPT-4o | General assistant using OpenAI |
| `claude_assistant` | Claude 3.5 Sonnet | General assistant using Anthropic |
| `math_tutor` | Gemini | Math-focused tutor |
| `writing_assistant` | Gemini | Writing and text analysis |
| `weather_bot` | Gemini | Weather-focused bot |

---

## Model Reference

### OpenAI Models
```yaml
model: openai/gpt-4o
model: openai/gpt-4o-mini
model: openai/gpt-4-turbo
```

### Anthropic Models
```yaml
model: anthropic/claude-3-5-sonnet-20241022
model: anthropic/claude-3-opus-20240229
model: anthropic/claude-3-haiku-20240307
```

### Google Gemini Models
```yaml
model: gemini/gemini-2.5-flash
model: gemini/gemini-2.0-flash
model: gemini/gemini-1.5-pro
```

---

## Creating Your Own Agent

Create `agents/my-agent/agent.yaml`:

```yaml
agent_id: my-agent
name: My Agent
model: openai/gpt-4o  # or any model above

instruction: |
  Your agent's personality and behavior.

tools:
  - calculator
  - weather
  - text_utils
```

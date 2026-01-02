"""Command-line interface for the Micro ADK framework."""

import argparse
import asyncio
import logging
import sys

import uvicorn


def setup_logging(level: str = "INFO") -> None:
    """Configure logging."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def run_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    config_path: str = None,
    reload: bool = False,
    log_level: str = "info",
) -> None:
    """Run the agent runtime server."""
    from micro_adk.runtime.api.main import create_app
    
    app = create_app(config_path=config_path)
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
    )


def deploy_tools(config_path: str, namespace: str = "default") -> None:
    """Deploy all tools from the manifest."""
    from micro_adk.core.config import load_config
    from micro_adk.core.tool_registry import ToolRegistry
    from micro_adk.orchestrator import KubernetesOrchestrator, OrchestratorConfig
    
    async def _deploy():
        config = load_config(config_path)
        
        # Load tool registry
        registry = ToolRegistry()
        registry.load_manifest(config.tools_manifest_path)
        
        # Create orchestrator
        orch_config = OrchestratorConfig(
            namespace=namespace,
            **config.tool_orchestrator.model_dump(),
        )
        orchestrator = KubernetesOrchestrator(
            config=orch_config,
            tool_registry=registry,
        )
        
        await orchestrator.initialize()
        
        print(f"Deploying {len(registry.list_tool_entries())} tools...")
        
        results = await orchestrator.deploy_all_tools()
        
        for tool_id, status in results.items():
            if status.error:
                print(f"  ✗ {tool_id}: {status.error}")
            else:
                print(f"  ✓ {tool_id}: {status.available_replicas}/{status.desired_replicas} ready")
        
        await orchestrator.close()
    
    asyncio.run(_deploy())


def undeploy_tools(config_path: str, namespace: str = "default") -> None:
    """Remove all deployed tools."""
    from micro_adk.core.config import load_config
    from micro_adk.core.tool_registry import ToolRegistry
    from micro_adk.orchestrator import KubernetesOrchestrator, OrchestratorConfig
    
    async def _undeploy():
        config = load_config(config_path)
        
        # Load tool registry
        registry = ToolRegistry()
        registry.load_manifest(config.tools_manifest_path)
        
        # Create orchestrator
        orch_config = OrchestratorConfig(namespace=namespace)
        orchestrator = KubernetesOrchestrator(
            config=orch_config,
            tool_registry=registry,
        )
        
        await orchestrator.initialize()
        
        print("Removing all tool deployments...")
        await orchestrator.undeploy_all_tools()
        print("Done.")
        
        await orchestrator.close()
    
    asyncio.run(_undeploy())


def init_project(path: str) -> None:
    """Initialize a new micro-adk project."""
    from pathlib import Path
    
    project_path = Path(path)
    project_path.mkdir(parents=True, exist_ok=True)
    
    # Create directory structure
    dirs = [
        "agents",
        "tools",
        "config",
    ]
    
    for d in dirs:
        (project_path / d).mkdir(exist_ok=True)
    
    # Create sample config
    config_content = """# Micro ADK Framework Configuration

# Database configuration
database:
  url: postgresql+asyncpg://postgres:postgres@localhost:5432/micro_adk
  pool_size: 5
  max_overflow: 10

# LiteLLM configuration  
litellm:
  api_base: null  # Set to use a custom LiteLLM proxy
  default_model: gpt-4
  timeout: 30

# Server configuration
server:
  host: 0.0.0.0
  port: 8000
  cors_origins:
    - "*"

# Paths
agents_dir: ./agents
tools_manifest_path: ./tools/manifest.yaml
"""
    
    (project_path / "config" / "config.yaml").write_text(config_content)
    
    # Create sample tool manifest
    manifest_content = """# Tool Manifest
# Define containerized tools for your agents

tools:
  - tool_id: calculator
    name: calculator
    description: A simple calculator tool
    image: micro-adk/tool-calculator:latest
    port: 8080
    schema:
      operation:
        type: string
        description: "The operation: add, subtract, multiply, divide"
      a:
        type: number
        description: First operand
      b:
        type: number
        description: Second operand
    autoscaling:
      enabled: true
      min_replicas: 1
      max_replicas: 5
      target_cpu_percent: 80
"""
    
    (project_path / "tools" / "manifest.yaml").write_text(manifest_content)
    
    # Create sample agent
    agent_dir = project_path / "agents" / "assistant"
    agent_dir.mkdir(parents=True, exist_ok=True)
    
    agent_config = """# Agent Configuration
agent_id: assistant
name: Assistant Agent
description: A helpful assistant with calculator capabilities

model: gpt-4
instruction: |
  You are a helpful assistant. You can use the calculator tool to perform
  mathematical operations when needed.

tools:
  - calculator
"""
    
    (agent_dir / "agent.yaml").write_text(agent_config)
    
    print(f"Initialized new micro-adk project at: {project_path}")
    print()
    print("Project structure:")
    print(f"  {project_path}/")
    print("  ├── config/")
    print("  │   └── config.yaml")
    print("  ├── agents/")
    print("  │   └── assistant/")
    print("  │       └── agent.yaml")
    print("  └── tools/")
    print("      └── manifest.yaml")
    print()
    print("Next steps:")
    print("  1. Update config/config.yaml with your database settings")
    print("  2. Define your tools in tools/manifest.yaml")
    print("  3. Create agent configurations in agents/")
    print("  4. Run: micro-adk serve --config config/config.yaml")


def main() -> None:
    """Main CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Micro ADK Framework - Run Google ADK agents as HTTP APIs",
        prog="micro-adk",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Serve command
    serve_parser = subparsers.add_parser("serve", help="Run the agent runtime server")
    serve_parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    serve_parser.add_argument("--config", "-c", help="Path to configuration file")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    serve_parser.add_argument("--log-level", default="info", help="Log level")
    
    # Deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Deploy tools to Kubernetes")
    deploy_parser.add_argument("--config", "-c", required=True, help="Path to configuration file")
    deploy_parser.add_argument("--namespace", "-n", default="default", help="Kubernetes namespace")
    
    # Undeploy command
    undeploy_parser = subparsers.add_parser("undeploy", help="Remove tool deployments")
    undeploy_parser.add_argument("--config", "-c", required=True, help="Path to configuration file")
    undeploy_parser.add_argument("--namespace", "-n", default="default", help="Kubernetes namespace")
    
    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new project")
    init_parser.add_argument("path", nargs="?", default=".", help="Project path")
    
    args = parser.parse_args()
    
    if args.command == "serve":
        setup_logging(args.log_level.upper())
        run_server(
            host=args.host,
            port=args.port,
            config_path=args.config,
            reload=args.reload,
            log_level=args.log_level,
        )
    
    elif args.command == "deploy":
        setup_logging()
        deploy_tools(args.config, args.namespace)
    
    elif args.command == "undeploy":
        setup_logging()
        undeploy_tools(args.config, args.namespace)
    
    elif args.command == "init":
        init_project(args.path)
    
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

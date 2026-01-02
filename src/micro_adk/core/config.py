"""Framework configuration management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseConfig(BaseModel):
    """Database configuration."""
    
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(default=5432, description="Database port")
    database: str = Field(default="micro_adk", description="Database name")
    user: str = Field(default="postgres", description="Database user")
    password: str = Field(default="postgres", description="Database password")
    pool_size: int = Field(default=5, description="Connection pool size")
    max_overflow: int = Field(default=10, description="Max overflow connections")
    
    @property
    def url(self) -> str:
        """Get async database URL."""
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
    
    @property
    def sync_url(self) -> str:
        """Get sync database URL for migrations."""
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


class LiteLLMConfig(BaseModel):
    """LiteLLM configuration."""
    
    base_url: Optional[str] = Field(default=None, description="LiteLLM proxy base URL")
    api_key: Optional[str] = Field(default=None, description="API key for LiteLLM")
    default_model: str = Field(default="gemini/gemini-2.0-flash", description="Default model (format: provider/model)")
    timeout: int = Field(default=120, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retries for failed requests")


class ToolOrchestratorConfig(BaseModel):
    """Tool orchestrator configuration."""
    
    enabled: bool = Field(default=True, description="Enable Kubernetes orchestration")
    namespace: str = Field(default="micro-adk-tools", description="Kubernetes namespace for tools")
    kubeconfig_path: Optional[str] = Field(default=None, description="Path to kubeconfig file")
    in_cluster: bool = Field(default=False, description="Running inside Kubernetes cluster")
    lazy_deploy: bool = Field(default=True, description="Deploy tools on first invocation")
    health_check_interval: int = Field(default=30, description="Health check interval in seconds")
    default_replicas: int = Field(default=1, description="Default replica count")


class ToolRouterConfig(BaseModel):
    """Tool router configuration."""
    
    # External Tool Router service URL (when using separate router container)
    router_service_url: Optional[str] = Field(
        default=None,
        description="URL of the standalone Tool Router service. If set, tools route through this service.",
    )
    
    timeout: int = Field(default=30, description="Request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retries for failed requests")
    retry_delay: float = Field(default=1.0, description="Delay between retries in seconds")
    circuit_breaker_threshold: int = Field(default=5, description="Circuit breaker failure threshold")
    circuit_breaker_timeout: int = Field(default=60, description="Circuit breaker timeout in seconds")
    
    # Service resolution (used when NOT using router_service_url)
    # Pattern can include {tool_id} placeholder, e.g., "http://tool-{tool_id}:8080"
    service_url_pattern: Optional[str] = Field(
        default=None,
        description="URL pattern for resolving tool service URLs. Use {tool_id} as placeholder.",
    )
    # Explicit mappings take precedence over pattern
    service_urls: dict[str, str] = Field(
        default_factory=dict,
        description="Explicit tool_id -> service_url mappings",
    )
    
    def resolve_service_url(self, tool_id: str) -> Optional[str]:
        """Resolve a tool ID to a service URL."""
        # Check explicit mapping first
        if tool_id in self.service_urls:
            return self.service_urls[tool_id]
        
        # Use pattern if available
        if self.service_url_pattern:
            return self.service_url_pattern.format(tool_id=tool_id)
        
        return None


class ServerConfig(BaseModel):
    """API server configuration."""
    
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    workers: int = Field(default=1, description="Number of worker processes")
    reload: bool = Field(default=False, description="Enable auto-reload for development")
    cors_origins: list[str] = Field(default=["*"], description="CORS allowed origins")


class FrameworkConfig(BaseSettings):
    """Main framework configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="MICRO_ADK_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )
    
    # Sub-configurations
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    litellm: LiteLLMConfig = Field(default_factory=LiteLLMConfig)
    orchestrator: ToolOrchestratorConfig = Field(default_factory=ToolOrchestratorConfig)
    router: ToolRouterConfig = Field(default_factory=ToolRouterConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    
    # Paths
    agents_dir: str = Field(default="./agents", description="Directory containing agent definitions")
    tools_manifest_path: str = Field(default="./config/tool_manifest.yaml", description="Path to tool manifest")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(default="json", description="Log format: json or text")
    
    @classmethod
    def from_yaml(cls, path: str | Path) -> "FrameworkConfig":
        """Load configuration from a YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return cls(**data)
    
    @classmethod
    def from_env(cls) -> "FrameworkConfig":
        """Load configuration from environment variables."""
        return cls()
    
    def to_yaml(self, path: str | Path) -> None:
        """Save configuration to a YAML file."""
        with open(path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)


def load_config(
    config_path: Optional[str] = None,
    use_env: bool = True,
) -> FrameworkConfig:
    """Load framework configuration.
    
    Priority order:
    1. Explicitly passed config_path
    2. MICRO_ADK_CONFIG_PATH environment variable
    3. Default paths: ./config/config.yaml, ./config.yaml
    4. Environment variables only (pydantic-settings)
    
    Args:
        config_path: Optional path to YAML configuration file.
        use_env: Whether to load from environment variables.
        
    Returns:
        FrameworkConfig instance.
    """
    import os
    
    # Check explicit path
    if config_path and Path(config_path).exists():
        return FrameworkConfig.from_yaml(config_path)
    
    # Check environment variable
    env_config_path = os.environ.get("MICRO_ADK_CONFIG_PATH")
    if env_config_path and Path(env_config_path).exists():
        return FrameworkConfig.from_yaml(env_config_path)
    
    # Check default paths
    default_paths = [
        "./config/config.yaml",
        "./config.yaml",
        "/app/config/config.yaml",  # Docker container path
    ]
    
    for default_path in default_paths:
        if Path(default_path).exists():
            return FrameworkConfig.from_yaml(default_path)
    
    # Fall back to environment variables
    if use_env:
        return FrameworkConfig.from_env()
    
    return FrameworkConfig()

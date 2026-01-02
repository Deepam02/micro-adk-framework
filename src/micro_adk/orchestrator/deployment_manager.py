"""Deployment manager for Kubernetes.

This module provides low-level deployment operations for managing
containerized tool services in Kubernetes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DeploymentSpec:
    """Specification for a Kubernetes deployment."""
    
    name: str
    image: str
    replicas: int = 1
    container_port: int = 80
    labels: Dict[str, str] = field(default_factory=dict)
    env_vars: Dict[str, str] = field(default_factory=dict)
    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    memory_request: str = "128Mi"
    memory_limit: str = "512Mi"
    image_pull_policy: str = "IfNotPresent"
    health_check_path: str = "/health"
    service_account: Optional[str] = None


@dataclass
class DeploymentStatus:
    """Status of a Kubernetes deployment."""
    
    name: str
    namespace: str
    ready: bool = False
    available_replicas: int = 0
    desired_replicas: int = 0
    updated_replicas: int = 0
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None


class DeploymentManager:
    """Manages Kubernetes deployments for tools.
    
    This class handles the low-level Kubernetes API operations for:
    - Creating deployments
    - Creating services
    - Scaling deployments
    - Checking deployment status
    - Deleting resources
    """
    
    def __init__(
        self,
        namespace: str = "default",
        kubeconfig_path: Optional[str] = None,
        in_cluster: bool = False,
    ):
        """Initialize the deployment manager.
        
        Args:
            namespace: Kubernetes namespace.
            kubeconfig_path: Path to kubeconfig file.
            in_cluster: Whether running inside a cluster.
        """
        self.namespace = namespace
        self.kubeconfig_path = kubeconfig_path
        self.in_cluster = in_cluster
        
        self._apps_api = None
        self._core_api = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the Kubernetes client."""
        try:
            from kubernetes import client, config
            from kubernetes.client import AppsV1Api, CoreV1Api
            
            if self.in_cluster:
                config.load_incluster_config()
            elif self.kubeconfig_path:
                config.load_kube_config(config_file=self.kubeconfig_path)
            else:
                config.load_kube_config()
            
            self._apps_api = AppsV1Api()
            self._core_api = CoreV1Api()
            self._initialized = True
            
            logger.info("Kubernetes client initialized")
        
        except ImportError:
            logger.warning("kubernetes package not installed, using mock mode")
            self._initialized = False
        except Exception as e:
            logger.warning(f"Failed to initialize Kubernetes client: {e}")
            self._initialized = False
    
    async def deploy(self, spec: DeploymentSpec) -> DeploymentStatus:
        """Create or update a deployment.
        
        Args:
            spec: Deployment specification.
            
        Returns:
            Deployment status.
        """
        if not self._initialized:
            logger.warning(f"Mock deploying: {spec.name}")
            return DeploymentStatus(
                name=spec.name,
                namespace=self.namespace,
                ready=True,
                available_replicas=spec.replicas,
                desired_replicas=spec.replicas,
            )
        
        from kubernetes import client
        
        # Build container spec
        container = client.V1Container(
            name=spec.name,
            image=spec.image,
            image_pull_policy=spec.image_pull_policy,
            ports=[client.V1ContainerPort(container_port=spec.container_port)],
            env=[
                client.V1EnvVar(name=k, value=v)
                for k, v in spec.env_vars.items()
            ] if spec.env_vars else None,
            resources=client.V1ResourceRequirements(
                requests={
                    "cpu": spec.cpu_request,
                    "memory": spec.memory_request,
                },
                limits={
                    "cpu": spec.cpu_limit,
                    "memory": spec.memory_limit,
                },
            ),
            liveness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(
                    path=spec.health_check_path,
                    port=spec.container_port,
                ),
                initial_delay_seconds=10,
                period_seconds=10,
            ),
            readiness_probe=client.V1Probe(
                http_get=client.V1HTTPGetAction(
                    path=spec.health_check_path,
                    port=spec.container_port,
                ),
                initial_delay_seconds=5,
                period_seconds=5,
            ),
        )
        
        # Build pod template
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=spec.labels),
            spec=client.V1PodSpec(
                containers=[container],
                service_account_name=spec.service_account,
            ),
        )
        
        # Build deployment spec
        deployment_spec = client.V1DeploymentSpec(
            replicas=spec.replicas,
            selector=client.V1LabelSelector(match_labels={"app": spec.labels.get("app", spec.name)}),
            template=template,
        )
        
        # Build deployment
        deployment = client.V1Deployment(
            api_version="apps/v1",
            kind="Deployment",
            metadata=client.V1ObjectMeta(name=spec.name, labels=spec.labels),
            spec=deployment_spec,
        )
        
        try:
            # Try to create, if exists then patch
            try:
                self._apps_api.create_namespaced_deployment(
                    namespace=self.namespace,
                    body=deployment,
                )
                logger.info(f"Created deployment: {spec.name}")
            except client.ApiException as e:
                if e.status == 409:  # Already exists
                    self._apps_api.patch_namespaced_deployment(
                        name=spec.name,
                        namespace=self.namespace,
                        body=deployment,
                    )
                    logger.info(f"Updated deployment: {spec.name}")
                else:
                    raise
            
            # Create service
            await self._create_service(spec)
            
            return await self.get_status(spec.name)
        
        except Exception as e:
            logger.error(f"Failed to deploy {spec.name}: {e}")
            return DeploymentStatus(
                name=spec.name,
                namespace=self.namespace,
                ready=False,
                error=str(e),
            )
    
    async def _create_service(self, spec: DeploymentSpec) -> None:
        """Create a service for the deployment."""
        if not self._initialized:
            return
        
        from kubernetes import client
        
        service = client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(
                name=spec.name,
                labels=spec.labels,
            ),
            spec=client.V1ServiceSpec(
                selector={"app": spec.labels.get("app", spec.name)},
                ports=[
                    client.V1ServicePort(
                        port=80,
                        target_port=spec.container_port,
                    )
                ],
                type="ClusterIP",
            ),
        )
        
        try:
            try:
                self._core_api.create_namespaced_service(
                    namespace=self.namespace,
                    body=service,
                )
                logger.info(f"Created service: {spec.name}")
            except client.ApiException as e:
                if e.status == 409:  # Already exists
                    pass  # Service already exists
                else:
                    raise
        except Exception as e:
            logger.error(f"Failed to create service {spec.name}: {e}")
    
    async def get_status(self, name: str) -> Optional[DeploymentStatus]:
        """Get the status of a deployment.
        
        Args:
            name: Deployment name.
            
        Returns:
            Deployment status or None.
        """
        if not self._initialized:
            return DeploymentStatus(
                name=name,
                namespace=self.namespace,
                ready=True,
                available_replicas=1,
                desired_replicas=1,
            )
        
        from kubernetes import client
        
        try:
            deployment = self._apps_api.read_namespaced_deployment_status(
                name=name,
                namespace=self.namespace,
            )
            
            status = deployment.status
            
            return DeploymentStatus(
                name=name,
                namespace=self.namespace,
                ready=(status.available_replicas or 0) >= (status.replicas or 0),
                available_replicas=status.available_replicas or 0,
                desired_replicas=status.replicas or 0,
                updated_replicas=status.updated_replicas or 0,
                conditions=[
                    {
                        "type": c.type,
                        "status": c.status,
                        "reason": c.reason,
                        "message": c.message,
                    }
                    for c in (status.conditions or [])
                ],
            )
        
        except client.ApiException as e:
            if e.status == 404:
                return None
            raise
    
    async def scale(self, name: str, replicas: int) -> bool:
        """Scale a deployment.
        
        Args:
            name: Deployment name.
            replicas: Desired replica count.
            
        Returns:
            True if successful.
        """
        if not self._initialized:
            logger.info(f"Mock scaling {name} to {replicas}")
            return True
        
        try:
            self._apps_api.patch_namespaced_deployment_scale(
                name=name,
                namespace=self.namespace,
                body={"spec": {"replicas": replicas}},
            )
            logger.info(f"Scaled {name} to {replicas}")
            return True
        except Exception as e:
            logger.error(f"Failed to scale {name}: {e}")
            return False
    
    async def delete(self, name: str) -> bool:
        """Delete a deployment and its service.
        
        Args:
            name: Deployment name.
            
        Returns:
            True if successful.
        """
        if not self._initialized:
            logger.info(f"Mock deleting: {name}")
            return True
        
        from kubernetes import client
        
        try:
            # Delete deployment
            self._apps_api.delete_namespaced_deployment(
                name=name,
                namespace=self.namespace,
            )
            
            # Delete service
            try:
                self._core_api.delete_namespaced_service(
                    name=name,
                    namespace=self.namespace,
                )
            except client.ApiException as e:
                if e.status != 404:
                    raise
            
            logger.info(f"Deleted deployment and service: {name}")
            return True
        
        except client.ApiException as e:
            if e.status == 404:
                return True  # Already deleted
            logger.error(f"Failed to delete {name}: {e}")
            return False
    
    async def list_deployments(self) -> List[DeploymentStatus]:
        """List all deployments in the namespace.
        
        Returns:
            List of deployment statuses.
        """
        if not self._initialized:
            return []
        
        try:
            deployments = self._apps_api.list_namespaced_deployment(
                namespace=self.namespace,
                label_selector="managed-by=micro-adk",
            )
            
            return [
                DeploymentStatus(
                    name=d.metadata.name,
                    namespace=self.namespace,
                    ready=(d.status.available_replicas or 0) >= (d.status.replicas or 0),
                    available_replicas=d.status.available_replicas or 0,
                    desired_replicas=d.status.replicas or 0,
                )
                for d in deployments.items
            ]
        except Exception as e:
            logger.error(f"Failed to list deployments: {e}")
            return []
    
    async def close(self) -> None:
        """Clean up resources."""
        pass  # Kubernetes client doesn't need explicit cleanup

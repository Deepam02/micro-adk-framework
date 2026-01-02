"""Autoscaler manager for Kubernetes HPA.

This module provides management of Horizontal Pod Autoscalers (HPA)
for automatic scaling of tool deployments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class HPASpec:
    """Specification for a Horizontal Pod Autoscaler."""
    
    name: str
    deployment_name: str
    min_replicas: int = 1
    max_replicas: int = 10
    target_cpu_percent: int = 80
    target_memory_percent: Optional[int] = None
    scale_down_stabilization: int = 300  # seconds
    scale_up_stabilization: int = 0  # seconds
    
    # Custom metrics (for future use)
    custom_metrics: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ScalingMetrics:
    """Current scaling metrics for an HPA."""
    
    name: str
    current_replicas: int
    desired_replicas: int
    current_cpu_percent: Optional[int] = None
    current_memory_percent: Optional[int] = None
    conditions: List[Dict[str, Any]] = field(default_factory=list)


class AutoscalerManager:
    """Manages Kubernetes Horizontal Pod Autoscalers.
    
    This class handles:
    - Creating and updating HPAs
    - Reading current scaling metrics
    - Deleting HPAs
    """
    
    def __init__(
        self,
        namespace: str = "default",
        kubeconfig_path: Optional[str] = None,
        in_cluster: bool = False,
    ):
        """Initialize the autoscaler manager.
        
        Args:
            namespace: Kubernetes namespace.
            kubeconfig_path: Path to kubeconfig file.
            in_cluster: Whether running inside a cluster.
        """
        self.namespace = namespace
        self.kubeconfig_path = kubeconfig_path
        self.in_cluster = in_cluster
        
        self._autoscaling_api = None
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize the Kubernetes client."""
        try:
            from kubernetes import client, config
            from kubernetes.client import AutoscalingV2Api
            
            if self.in_cluster:
                config.load_incluster_config()
            elif self.kubeconfig_path:
                config.load_kube_config(config_file=self.kubeconfig_path)
            else:
                config.load_kube_config()
            
            self._autoscaling_api = AutoscalingV2Api()
            self._initialized = True
            
            logger.info("Autoscaling API initialized")
        
        except ImportError:
            logger.warning("kubernetes package not installed, using mock mode")
            self._initialized = False
        except Exception as e:
            logger.warning(f"Failed to initialize autoscaling API: {e}")
            self._initialized = False
    
    async def create_or_update_hpa(self, spec: HPASpec) -> bool:
        """Create or update an HPA.
        
        Args:
            spec: HPA specification.
            
        Returns:
            True if successful.
        """
        if not self._initialized:
            logger.info(f"Mock creating HPA: {spec.name}")
            return True
        
        from kubernetes import client
        
        # Build metrics
        metrics = [
            client.V2MetricSpec(
                type="Resource",
                resource=client.V2ResourceMetricSource(
                    name="cpu",
                    target=client.V2MetricTarget(
                        type="Utilization",
                        average_utilization=spec.target_cpu_percent,
                    ),
                ),
            )
        ]
        
        if spec.target_memory_percent:
            metrics.append(
                client.V2MetricSpec(
                    type="Resource",
                    resource=client.V2ResourceMetricSource(
                        name="memory",
                        target=client.V2MetricTarget(
                            type="Utilization",
                            average_utilization=spec.target_memory_percent,
                        ),
                    ),
                )
            )
        
        # Build HPA
        hpa = client.V2HorizontalPodAutoscaler(
            api_version="autoscaling/v2",
            kind="HorizontalPodAutoscaler",
            metadata=client.V1ObjectMeta(
                name=spec.name,
                labels={
                    "managed-by": "micro-adk",
                },
            ),
            spec=client.V2HorizontalPodAutoscalerSpec(
                scale_target_ref=client.V2CrossVersionObjectReference(
                    api_version="apps/v1",
                    kind="Deployment",
                    name=spec.deployment_name,
                ),
                min_replicas=spec.min_replicas,
                max_replicas=spec.max_replicas,
                metrics=metrics,
                behavior=client.V2HorizontalPodAutoscalerBehavior(
                    scale_down=client.V2HPAScalingRules(
                        stabilization_window_seconds=spec.scale_down_stabilization,
                    ),
                    scale_up=client.V2HPAScalingRules(
                        stabilization_window_seconds=spec.scale_up_stabilization,
                    ),
                ),
            ),
        )
        
        try:
            try:
                self._autoscaling_api.create_namespaced_horizontal_pod_autoscaler(
                    namespace=self.namespace,
                    body=hpa,
                )
                logger.info(f"Created HPA: {spec.name}")
            except client.ApiException as e:
                if e.status == 409:  # Already exists
                    self._autoscaling_api.patch_namespaced_horizontal_pod_autoscaler(
                        name=spec.name,
                        namespace=self.namespace,
                        body=hpa,
                    )
                    logger.info(f"Updated HPA: {spec.name}")
                else:
                    raise
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to create/update HPA {spec.name}: {e}")
            return False
    
    async def get_metrics(self, name: str) -> Optional[ScalingMetrics]:
        """Get current scaling metrics for an HPA.
        
        Args:
            name: HPA name.
            
        Returns:
            Scaling metrics or None.
        """
        if not self._initialized:
            return ScalingMetrics(
                name=name,
                current_replicas=1,
                desired_replicas=1,
                current_cpu_percent=50,
            )
        
        from kubernetes import client
        
        try:
            hpa = self._autoscaling_api.read_namespaced_horizontal_pod_autoscaler_status(
                name=name,
                namespace=self.namespace,
            )
            
            status = hpa.status
            
            # Extract current CPU usage
            current_cpu = None
            current_memory = None
            
            for metric in status.current_metrics or []:
                if metric.type == "Resource" and metric.resource:
                    if metric.resource.name == "cpu" and metric.resource.current:
                        current_cpu = metric.resource.current.average_utilization
                    elif metric.resource.name == "memory" and metric.resource.current:
                        current_memory = metric.resource.current.average_utilization
            
            return ScalingMetrics(
                name=name,
                current_replicas=status.current_replicas or 0,
                desired_replicas=status.desired_replicas or 0,
                current_cpu_percent=current_cpu,
                current_memory_percent=current_memory,
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
    
    async def delete_hpa(self, name: str) -> bool:
        """Delete an HPA.
        
        Args:
            name: HPA name.
            
        Returns:
            True if successful.
        """
        if not self._initialized:
            logger.info(f"Mock deleting HPA: {name}")
            return True
        
        from kubernetes import client
        
        try:
            self._autoscaling_api.delete_namespaced_horizontal_pod_autoscaler(
                name=name,
                namespace=self.namespace,
            )
            logger.info(f"Deleted HPA: {name}")
            return True
        
        except client.ApiException as e:
            if e.status == 404:
                return True  # Already deleted
            logger.error(f"Failed to delete HPA {name}: {e}")
            return False
    
    async def list_hpas(self) -> List[ScalingMetrics]:
        """List all HPAs in the namespace.
        
        Returns:
            List of scaling metrics.
        """
        if not self._initialized:
            return []
        
        try:
            hpas = self._autoscaling_api.list_namespaced_horizontal_pod_autoscaler(
                namespace=self.namespace,
                label_selector="managed-by=micro-adk",
            )
            
            return [
                ScalingMetrics(
                    name=h.metadata.name,
                    current_replicas=h.status.current_replicas or 0,
                    desired_replicas=h.status.desired_replicas or 0,
                )
                for h in hpas.items
            ]
        except Exception as e:
            logger.error(f"Failed to list HPAs: {e}")
            return []
    
    async def close(self) -> None:
        """Clean up resources."""
        pass  # Kubernetes client doesn't need explicit cleanup

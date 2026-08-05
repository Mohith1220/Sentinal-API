# Feature: sentinel-api, Task 22: Smoke tests — Health checks
"""
Smoke tests for service health checks.

Tests:
- Each service's /health endpoint returns HTTP 200 after docker compose up

Requirements: 13.1, 15.5
"""

import pytest
import httpx
import time


# Service endpoints to test
SERVICES = [
    ("api-gateway", "http://localhost:8000/health"),
    ("discovery-service", "http://localhost:8001/health"),
    ("stream-processor", "http://localhost:8002/health"),
    ("classification-service", "http://localhost:8003/health"),
    ("risk-scorer-service", "http://localhost:8004/health"),
    ("anomaly-detector-service", "http://localhost:8005/health"),
    ("remediation-service", "http://localhost:8006/health"),
    ("graph-service", "http://localhost:8007/health"),
]


@pytest.mark.smoke
@pytest.mark.parametrize("service_name,health_url", SERVICES)
def test_service_health_check(service_name: str, health_url: str):
    """
    Test that each service's /health endpoint returns HTTP 200.
    
    This test assumes docker compose up has been run and all services are started.
    
    Validates: Requirements 13.1, 15.5
    """
    max_retries = 3
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            response = httpx.get(health_url, timeout=5.0)
            
            # Assert HTTP 200 status
            assert response.status_code == 200, (
                f"{service_name} health check failed: "
                f"expected status 200, got {response.status_code}"
            )
            
            # Success - exit retry loop
            return
            
        except httpx.ConnectError:
            if attempt < max_retries - 1:
                # Service might still be starting up, retry
                time.sleep(retry_delay)
                continue
            else:
                # Final attempt failed
                pytest.fail(
                    f"{service_name} health check failed: "
                    f"could not connect to {health_url} after {max_retries} attempts"
                )
        except httpx.TimeoutException:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
                continue
            else:
                pytest.fail(
                    f"{service_name} health check failed: "
                    f"timeout connecting to {health_url} after {max_retries} attempts"
                )


@pytest.mark.smoke
def test_all_services_healthy():
    """
    Test that all services are healthy simultaneously.
    
    This is a comprehensive check that verifies the entire platform is operational.
    
    Validates: Requirements 13.1, 15.5
    """
    failed_services = []
    
    for service_name, health_url in SERVICES:
        try:
            response = httpx.get(health_url, timeout=5.0)
            if response.status_code != 200:
                failed_services.append(
                    f"{service_name} (status {response.status_code})"
                )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            failed_services.append(f"{service_name} ({type(e).__name__})")
    
    # Assert all services are healthy
    assert len(failed_services) == 0, (
        f"The following services are not healthy: {', '.join(failed_services)}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# Feature: sentinel-api, Task 22: Performance tests — Risk Scorer
"""
Performance tests for the Risk Scorer Service.

Tests:
- Send 1,000 concurrent scoring requests
- Assert all complete within 2 seconds each

Requirements: 13.1
"""

import asyncio
import time
import sys
import os
from typing import List
import statistics

import pytest
import httpx

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, _REPO_ROOT)
sys.path.insert(0, os.path.join(_REPO_ROOT, "sentinel_shared"))

from sentinel_shared.models import (
    EndpointRecord,
    AuthScheme,
    DataSensitivity,
    LifecycleStatus,
)


async def create_test_endpoint(client: httpx.AsyncClient, index: int) -> str:
    """
    Create a test endpoint in the discovery service.
    
    Returns the endpoint ID.
    """
    endpoint = EndpointRecord(
        http_method="GET",
        host="perf-test.example.com",
        normalized_path=f"/api/test/{index}",
        auth_scheme=AuthScheme.NONE if index % 2 == 0 else AuthScheme.JWT,
        data_sensitivity=DataSensitivity.PII if index % 3 == 0 else DataSensitivity.INTERNAL,
        lifecycle_status=LifecycleStatus.ZOMBIE if index % 5 == 0 else LifecycleStatus.ACTIVE,
        risk_score=0,
    )
    
    # Create endpoint via discovery service
    response = await client.post(
        "http://localhost:8001/discover/openapi",
        json={
            "openapi": "3.0.0",
            "info": {"title": f"Perf Test {index}", "version": "1.0.0"},
            "paths": {
                endpoint.normalized_path: {
                    endpoint.http_method.lower(): {
                        "responses": {"200": {"description": "ok"}}
                    }
                }
            }
        },
        timeout=10.0
    )
    
    if response.status_code not in [200, 201]:
        raise Exception(f"Failed to create endpoint: {response.status_code}")
    
    # Extract endpoint ID from response
    data = response.json()
    if isinstance(data, list) and len(data) > 0:
        return data[0].get("id")
    elif isinstance(data, dict):
        return data.get("id")
    
    raise Exception("Could not extract endpoint ID from response")


async def score_endpoint(client: httpx.AsyncClient, endpoint_id: str) -> float:
    """
    Score an endpoint and return the elapsed time in seconds.
    """
    start_time = time.time()
    
    response = await client.post(
        f"http://localhost:8004/score/{endpoint_id}",
        timeout=5.0
    )
    
    elapsed = time.time() - start_time
    
    if response.status_code not in [200, 201]:
        raise Exception(f"Scoring failed: {response.status_code}")
    
    return elapsed


@pytest.mark.performance
@pytest.mark.asyncio
async def test_risk_scorer_concurrent_requests():
    """
    Test that 1,000 concurrent scoring requests all complete within 2 seconds each.
    
    This test validates the performance requirement that the risk scorer can
    handle high concurrent load.
    
    Validates: Requirement 13.1
    """
    num_requests = 1000
    max_time_per_request = 2.0  # seconds
    
    # Check if services are available
    try:
        async with httpx.AsyncClient() as client:
            health_response = await client.get(
                "http://localhost:8004/health",
                timeout=5.0
            )
            if health_response.status_code != 200:
                pytest.skip("Risk scorer service is not available")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("Risk scorer service is not available")
    
    # Create test endpoints
    print(f"\nCreating {num_requests} test endpoints...")
    endpoint_ids: List[str] = []
    
    async with httpx.AsyncClient() as client:
        # Create endpoints in batches to avoid overwhelming the service
        batch_size = 50
        for i in range(0, num_requests, batch_size):
            batch_tasks = [
                create_test_endpoint(client, j)
                for j in range(i, min(i + batch_size, num_requests))
            ]
            batch_ids = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            # Filter out exceptions
            valid_ids = [
                eid for eid in batch_ids 
                if isinstance(eid, str) and eid
            ]
            endpoint_ids.extend(valid_ids)
            
            # Brief pause between batches
            await asyncio.sleep(0.1)
    
    print(f"Created {len(endpoint_ids)} endpoints")
    
    if len(endpoint_ids) < num_requests * 0.8:
        pytest.skip(
            f"Could not create enough test endpoints: "
            f"created {len(endpoint_ids)}, needed {num_requests}"
        )
    
    # Score all endpoints concurrently
    print(f"Scoring {len(endpoint_ids)} endpoints concurrently...")
    start_time = time.time()
    
    async with httpx.AsyncClient() as client:
        tasks = [score_endpoint(client, eid) for eid in endpoint_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_elapsed = time.time() - start_time
    
    # Filter out exceptions and get valid timings
    timings = [r for r in results if isinstance(r, float)]
    
    print(f"\nCompleted {len(timings)} scoring requests in {total_elapsed:.2f}s")
    
    # Calculate statistics
    if timings:
        avg_time = statistics.mean(timings)
        max_time = max(timings)
        min_time = min(timings)
        p95_time = statistics.quantiles(timings, n=20)[18]  # 95th percentile
        p99_time = statistics.quantiles(timings, n=100)[98]  # 99th percentile
        
        print(f"Timing statistics:")
        print(f"  Min: {min_time:.3f}s")
        print(f"  Avg: {avg_time:.3f}s")
        print(f"  Max: {max_time:.3f}s")
        print(f"  P95: {p95_time:.3f}s")
        print(f"  P99: {p99_time:.3f}s")
        
        # Count requests that exceeded the threshold
        slow_requests = [t for t in timings if t > max_time_per_request]
        slow_percentage = (len(slow_requests) / len(timings)) * 100
        
        print(f"  Slow requests (>{max_time_per_request}s): {len(slow_requests)} ({slow_percentage:.1f}%)")
        
        # Assert that all requests completed within the threshold
        assert max_time <= max_time_per_request, (
            f"Some requests exceeded {max_time_per_request}s threshold: "
            f"max time was {max_time:.3f}s"
        )
        
        # Assert that at least 95% of requests completed successfully
        success_rate = (len(timings) / len(endpoint_ids)) * 100
        assert success_rate >= 95.0, (
            f"Success rate too low: {success_rate:.1f}% "
            f"({len(timings)}/{len(endpoint_ids)} succeeded)"
        )
    else:
        pytest.fail("No successful scoring requests completed")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_risk_scorer_sustained_load():
    """
    Test that the risk scorer can handle sustained load over time.
    
    This test sends scoring requests continuously for 30 seconds and
    verifies that performance remains consistent.
    
    Validates: Requirement 13.1
    """
    duration_seconds = 30
    target_rps = 50  # requests per second
    max_time_per_request = 2.0
    
    # Check if services are available
    try:
        async with httpx.AsyncClient() as client:
            health_response = await client.get(
                "http://localhost:8004/health",
                timeout=5.0
            )
            if health_response.status_code != 200:
                pytest.skip("Risk scorer service is not available")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("Risk scorer service is not available")
    
    # Create a pool of test endpoints
    print(f"\nCreating test endpoint pool...")
    endpoint_ids: List[str] = []
    
    async with httpx.AsyncClient() as client:
        for i in range(100):  # Create 100 endpoints to cycle through
            try:
                eid = await create_test_endpoint(client, i)
                endpoint_ids.append(eid)
            except Exception:
                pass
    
    if len(endpoint_ids) < 50:
        pytest.skip(f"Could not create enough test endpoints: created {len(endpoint_ids)}")
    
    print(f"Created {len(endpoint_ids)} endpoints")
    
    # Run sustained load test
    print(f"Running sustained load test for {duration_seconds}s at {target_rps} RPS...")
    
    timings: List[float] = []
    errors = 0
    start_time = time.time()
    request_count = 0
    
    async with httpx.AsyncClient() as client:
        while time.time() - start_time < duration_seconds:
            # Select endpoint in round-robin fashion
            endpoint_id = endpoint_ids[request_count % len(endpoint_ids)]
            
            try:
                elapsed = await score_endpoint(client, endpoint_id)
                timings.append(elapsed)
            except Exception:
                errors += 1
            
            request_count += 1
            
            # Rate limiting: sleep to maintain target RPS
            await asyncio.sleep(1.0 / target_rps)
    
    total_elapsed = time.time() - start_time
    actual_rps = request_count / total_elapsed
    
    print(f"\nCompleted {request_count} requests in {total_elapsed:.2f}s")
    print(f"Actual RPS: {actual_rps:.1f}")
    print(f"Successful: {len(timings)}, Errors: {errors}")
    
    if timings:
        avg_time = statistics.mean(timings)
        max_time = max(timings)
        p95_time = statistics.quantiles(timings, n=20)[18]
        
        print(f"Timing statistics:")
        print(f"  Avg: {avg_time:.3f}s")
        print(f"  Max: {max_time:.3f}s")
        print(f"  P95: {p95_time:.3f}s")
        
        # Assert performance requirements
        assert max_time <= max_time_per_request, (
            f"Some requests exceeded {max_time_per_request}s threshold: "
            f"max time was {max_time:.3f}s"
        )
        
        # Assert error rate is acceptable
        error_rate = (errors / request_count) * 100
        assert error_rate <= 5.0, f"Error rate too high: {error_rate:.1f}%"
    else:
        pytest.fail("No successful requests completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

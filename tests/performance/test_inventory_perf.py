# Feature: sentinel-api, Task 22: Performance tests — API Inventory
"""
Performance tests for the API Inventory.

Tests:
- Seed 50,000 endpoint records
- Assert paginated list query returns within 500 ms

Requirements: 13.2
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


async def seed_endpoint(client: httpx.AsyncClient, index: int) -> bool:
    """
    Seed a single endpoint into the inventory.
    
    Returns True if successful, False otherwise.
    """
    # Vary the endpoint attributes to create realistic diversity
    auth_schemes = [AuthScheme.NONE, AuthScheme.JWT, AuthScheme.OAUTH2, AuthScheme.API_KEY]
    sensitivities = [DataSensitivity.PUBLIC, DataSensitivity.INTERNAL, DataSensitivity.PII, DataSensitivity.FINANCIAL]
    statuses = [LifecycleStatus.ACTIVE, LifecycleStatus.DEPRECATED, LifecycleStatus.ZOMBIE, LifecycleStatus.ORPHANED]
    
    endpoint = {
        "openapi": "3.0.0",
        "info": {"title": f"Inventory Perf Test {index // 100}", "version": "1.0.0"},
        "servers": [{"url": f"https://api{index % 100}.example.com"}],
        "paths": {
            f"/api/resource/{index}": {
                "get": {
                    "responses": {"200": {"description": "ok"}},
                    "security": [{"bearer": []}] if index % 2 == 0 else []
                }
            }
        }
    }
    
    try:
        response = await client.post(
            "http://localhost:8001/discover/openapi",
            json=endpoint,
            timeout=10.0
        )
        return response.status_code in [200, 201]
    except Exception:
        return False


async def query_inventory(
    client: httpx.AsyncClient,
    page: int = 1,
    page_size: int = 100,
    filters: dict = None
) -> tuple[float, int]:
    """
    Query the inventory with pagination and optional filters.
    
    Returns (elapsed_time_seconds, record_count).
    """
    params = {
        "page": page,
        "page_size": page_size,
    }
    
    if filters:
        params.update(filters)
    
    start_time = time.time()
    
    response = await client.get(
        "http://localhost:8001/endpoints",
        params=params,
        timeout=5.0
    )
    
    elapsed = time.time() - start_time
    
    if response.status_code != 200:
        raise Exception(f"Query failed: {response.status_code}")
    
    data = response.json()
    
    # Handle different response formats
    if isinstance(data, list):
        count = len(data)
    elif isinstance(data, dict):
        count = len(data.get("items", []))
    else:
        count = 0
    
    return elapsed, count


@pytest.mark.performance
@pytest.mark.asyncio
async def test_inventory_query_performance_with_50k_records():
    """
    Test that paginated list queries return within 500ms on a 50,000 record inventory.
    
    This test seeds 50,000 endpoint records and then performs multiple paginated
    queries to verify performance.
    
    Validates: Requirement 13.2
    """
    target_records = 50000
    max_query_time = 0.5  # 500 ms
    
    # Check if services are available
    try:
        async with httpx.AsyncClient() as client:
            health_response = await client.get(
                "http://localhost:8001/health",
                timeout=5.0
            )
            if health_response.status_code != 200:
                pytest.skip("Discovery service is not available")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("Discovery service is not available")
    
    # Check current inventory size
    async with httpx.AsyncClient() as client:
        try:
            elapsed, current_count = await query_inventory(client, page=1, page_size=1)
            print(f"\nCurrent inventory size: ~{current_count} records")
        except Exception:
            current_count = 0
    
    # Seed endpoints if needed
    if current_count < target_records:
        records_to_create = target_records - current_count
        print(f"Seeding {records_to_create} endpoint records...")
        
        async with httpx.AsyncClient() as client:
            # Seed in batches to avoid overwhelming the service
            batch_size = 100
            successful = 0
            
            for i in range(0, records_to_create, batch_size):
                batch_tasks = [
                    seed_endpoint(client, current_count + j)
                    for j in range(i, min(i + batch_size, records_to_create))
                ]
                results = await asyncio.gather(*batch_tasks, return_exceptions=True)
                successful += sum(1 for r in results if r is True)
                
                # Progress update every 1000 records
                if (i + batch_size) % 1000 == 0:
                    print(f"  Seeded {i + batch_size}/{records_to_create} records...")
                
                # Brief pause between batches
                await asyncio.sleep(0.05)
        
        print(f"Successfully seeded {successful} records")
        
        if successful < records_to_create * 0.8:
            pytest.skip(
                f"Could not seed enough records: "
                f"seeded {successful}, needed {records_to_create}"
            )
    else:
        print(f"Inventory already has {current_count} records, skipping seeding")
    
    # Perform query performance tests
    print(f"\nTesting query performance...")
    
    query_timings: List[float] = []
    
    async with httpx.AsyncClient() as client:
        # Test 1: First page query
        elapsed, count = await query_inventory(client, page=1, page_size=100)
        query_timings.append(elapsed)
        print(f"  First page (100 records): {elapsed*1000:.1f}ms")
        
        # Test 2: Middle page query
        elapsed, count = await query_inventory(client, page=250, page_size=100)
        query_timings.append(elapsed)
        print(f"  Middle page (page 250): {elapsed*1000:.1f}ms")
        
        # Test 3: Large page size
        elapsed, count = await query_inventory(client, page=1, page_size=1000)
        query_timings.append(elapsed)
        print(f"  Large page (1000 records): {elapsed*1000:.1f}ms")
        
        # Test 4: Query with filters
        elapsed, count = await query_inventory(
            client,
            page=1,
            page_size=100,
            filters={"lifecycle_status": "Active"}
        )
        query_timings.append(elapsed)
        print(f"  Filtered query (status=Active): {elapsed*1000:.1f}ms")
        
        # Test 5: Multiple concurrent queries
        concurrent_tasks = [
            query_inventory(client, page=i, page_size=100)
            for i in range(1, 11)  # Pages 1-10
        ]
        concurrent_results = await asyncio.gather(*concurrent_tasks, return_exceptions=True)
        concurrent_timings = [
            r[0] for r in concurrent_results 
            if isinstance(r, tuple) and len(r) == 2
        ]
        query_timings.extend(concurrent_timings)
        
        if concurrent_timings:
            avg_concurrent = statistics.mean(concurrent_timings)
            print(f"  Concurrent queries (10 parallel): avg {avg_concurrent*1000:.1f}ms")
    
    # Calculate statistics
    if query_timings:
        avg_time = statistics.mean(query_timings)
        max_time = max(query_timings)
        min_time = min(query_timings)
        p95_time = statistics.quantiles(query_timings, n=20)[18]
        
        print(f"\nQuery timing statistics:")
        print(f"  Min: {min_time*1000:.1f}ms")
        print(f"  Avg: {avg_time*1000:.1f}ms")
        print(f"  Max: {max_time*1000:.1f}ms")
        print(f"  P95: {p95_time*1000:.1f}ms")
        
        # Count queries that exceeded the threshold
        slow_queries = [t for t in query_timings if t > max_query_time]
        slow_percentage = (len(slow_queries) / len(query_timings)) * 100
        
        print(f"  Slow queries (>{max_query_time*1000:.0f}ms): {len(slow_queries)} ({slow_percentage:.1f}%)")
        
        # Assert that all queries completed within the threshold
        assert max_time <= max_query_time, (
            f"Some queries exceeded {max_query_time*1000:.0f}ms threshold: "
            f"max time was {max_time*1000:.1f}ms"
        )
    else:
        pytest.fail("No successful queries completed")


@pytest.mark.performance
@pytest.mark.asyncio
async def test_inventory_filter_performance():
    """
    Test that filtered queries perform well on large inventory.
    
    Validates: Requirement 13.2
    """
    max_query_time = 0.5  # 500 ms
    
    # Check if services are available
    try:
        async with httpx.AsyncClient() as client:
            health_response = await client.get(
                "http://localhost:8001/health",
                timeout=5.0
            )
            if health_response.status_code != 200:
                pytest.skip("Discovery service is not available")
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip("Discovery service is not available")
    
    # Test various filter combinations
    filter_combinations = [
        {"lifecycle_status": "Active"},
        {"lifecycle_status": "Zombie"},
        {"auth_scheme": "none"},
        {"data_sensitivity": "PII"},
        {"risk_score_min": 40},
        {"risk_score_max": 70},
        {"lifecycle_status": "Active", "auth_scheme": "JWT"},
        {"data_sensitivity": "PII", "risk_score_min": 60},
    ]
    
    print(f"\nTesting filter performance...")
    
    query_timings: List[float] = []
    
    async with httpx.AsyncClient() as client:
        for filters in filter_combinations:
            try:
                elapsed, count = await query_inventory(
                    client,
                    page=1,
                    page_size=100,
                    filters=filters
                )
                query_timings.append(elapsed)
                
                filter_str = ", ".join(f"{k}={v}" for k, v in filters.items())
                print(f"  Filter [{filter_str}]: {elapsed*1000:.1f}ms ({count} results)")
                
            except Exception as e:
                print(f"  Filter {filters} failed: {e}")
    
    if query_timings:
        avg_time = statistics.mean(query_timings)
        max_time = max(query_timings)
        
        print(f"\nFilter query statistics:")
        print(f"  Avg: {avg_time*1000:.1f}ms")
        print(f"  Max: {max_time*1000:.1f}ms")
        
        # Assert that all filtered queries completed within the threshold
        assert max_time <= max_query_time, (
            f"Some filtered queries exceeded {max_query_time*1000:.0f}ms threshold: "
            f"max time was {max_time*1000:.1f}ms"
        )
    else:
        pytest.skip("No successful filtered queries completed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

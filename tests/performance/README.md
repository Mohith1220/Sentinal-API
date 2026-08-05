# Performance Tests

Performance tests verify that the SentinelAPI platform meets its scalability and latency requirements under load.

## Prerequisites

- Docker and Docker Compose installed
- All services started with `docker compose up --wait`
- Sufficient system resources (CPU, memory) for load testing
- Python packages: `pytest`, `pytest-asyncio`, `httpx`, `aiokafka`

## Running Performance Tests

Run all performance tests:
```bash
pytest tests/performance/ -v -s
```

Run specific performance test categories:
```bash
# Risk scorer performance
pytest tests/performance/test_risk_scorer_perf.py -v -s

# Inventory performance
pytest tests/performance/test_inventory_perf.py -v -s

# Stream processor performance
pytest tests/performance/test_stream_processor_perf.py -v -s
```

Run with the performance marker:
```bash
pytest -m performance -v -s
```

**Note:** Use `-s` flag to see progress output during long-running tests.

## Test Coverage

### Risk Scorer Performance (`test_risk_scorer_perf.py`)

**Test 1: Concurrent Requests**
- Sends 1,000 concurrent scoring requests
- Validates all complete within 2 seconds each
- Measures min, avg, max, P95, and P99 latencies

**Test 2: Sustained Load**
- Runs continuous load for 30 seconds at 50 RPS
- Verifies consistent performance over time
- Validates error rate < 5%

**Requirements validated:** 13.1

### Inventory Performance (`test_inventory_perf.py`)

**Test 1: Large Inventory Query**
- Seeds 50,000 endpoint records
- Tests paginated queries with various page sizes
- Validates query time < 500ms
- Tests concurrent queries

**Test 2: Filter Performance**
- Tests various filter combinations
- Validates filtered queries < 500ms
- Covers lifecycle status, auth scheme, risk score, and data sensitivity filters

**Requirements validated:** 13.2

### Stream Processor Performance (`test_stream_processor_perf.py`)

**Test 1: Throughput**
- Produces 10,000 events/second for 10 seconds
- Validates system can sustain target throughput
- Measures actual event rate

**Test 2: Latency**
- Measures end-to-end latency from production to processing
- Validates P99 latency < 10 seconds
- Tests 1,000 events with timestamp tracking

**Test 3: Consumer Scaling**
- Verifies events are distributed across 3 partitions
- Tests horizontal scaling capability
- Validates partition assignment

**Requirements validated:** 13.3, 13.5

## Performance Targets

| Metric | Target | Test |
|--------|--------|------|
| Risk scoring latency | < 2s per request | `test_risk_scorer_concurrent_requests` |
| Risk scorer throughput | 1,000 concurrent requests | `test_risk_scorer_concurrent_requests` |
| Inventory query latency | < 500ms | `test_inventory_query_performance_with_50k_records` |
| Inventory size | 50,000 records | `test_inventory_query_performance_with_50k_records` |
| Stream processor throughput | 10,000 events/sec | `test_stream_processor_throughput` |
| Stream processor P99 latency | < 10s | `test_stream_processor_latency` |
| Consumer instances | 3 parallel consumers | `test_stream_processor_consumer_scaling` |

## Expected Results

Performance tests should pass when:
- All services are running and healthy
- System has sufficient resources (4+ CPU cores, 8+ GB RAM recommended)
- No other heavy processes are competing for resources

## Troubleshooting

If tests fail:

1. **Timeout errors**: Increase system resources or reduce test load
2. **Connection errors**: Ensure all services are running and healthy
3. **Slow queries**: Check database indexes and query optimization
4. **Kafka errors**: Verify Kafka is running and topics are created
5. **Memory errors**: Reduce batch sizes or test duration

## Performance Tuning

To improve performance:

1. **Database**: Ensure indexes are created on frequently queried columns
2. **Kafka**: Increase partition count for better parallelism
3. **Services**: Scale horizontally by adding more container instances
4. **Resources**: Allocate more CPU and memory to containers

## CI/CD Integration

Performance tests can be run in CI/CD with reduced load:

```bash
# Start services
docker compose up --wait

# Run performance tests with reduced load
pytest tests/performance/ -v -s \
  --maxfail=1 \
  --tb=short

# Stop services
docker compose down
```

For full performance validation, run on dedicated performance testing infrastructure.

## Monitoring During Tests

Monitor system metrics during performance tests:

```bash
# Watch container resource usage
docker stats

# View service logs
docker compose logs -f <service-name>

# Check Kafka consumer lag
docker compose exec kafka kafka-consumer-groups.sh \
  --bootstrap-server localhost:9092 \
  --describe --group sentinel-stream-processor
```

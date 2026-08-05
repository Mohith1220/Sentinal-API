# Smoke Tests

Smoke tests verify that the SentinelAPI platform is correctly deployed and all services are operational.

## Prerequisites

- Docker and Docker Compose installed
- All services started with `docker compose up --wait`

## Running Smoke Tests

Run all smoke tests:
```bash
pytest tests/smoke/ -v
```

Run specific smoke test categories:
```bash
# Health checks only
pytest tests/smoke/test_health_checks.py -v

# Docker Compose validation
pytest tests/smoke/test_docker_compose.py -v

# TLS and metrics configuration
pytest tests/smoke/test_tls_config.py -v
```

Run with the smoke marker:
```bash
pytest -m smoke -v
```

## Test Coverage

### Health Checks (`test_health_checks.py`)
- Verifies each service's `/health` endpoint returns HTTP 200
- Tests all 8 microservices individually
- Validates that all services are healthy simultaneously

**Requirements validated:** 13.1, 15.5

### Docker Compose (`test_docker_compose.py`)
- Validates docker-compose.yml configuration
- Verifies all containers reach healthy state
- Checks that all required services are running

**Requirements validated:** 13.1, 15.2

### TLS Configuration (`test_tls_config.py`)
- Verifies TLS 1.2+ for inter-service communication (when configured)
- Tests Prometheus `/metrics` endpoint on each service
- Validates metrics format and content

**Requirements validated:** 13.2, 15.2

## Expected Results

All smoke tests should pass when:
- Docker Compose services are running
- All health checks are passing
- Services are properly configured

## Troubleshooting

If tests fail:

1. **Connection errors**: Ensure `docker compose up` has completed and all services are running
2. **Health check failures**: Check service logs with `docker compose logs <service-name>`
3. **Timeout errors**: Services may still be starting up - wait 30-60 seconds and retry
4. **TLS tests skipped**: TLS is not configured in development mode (this is expected)

## CI/CD Integration

These tests are designed to run in CI/CD pipelines after deployment:

```bash
# Start services
docker compose up --wait

# Run smoke tests
pytest tests/smoke/ -v --tb=short

# Stop services
docker compose down
```

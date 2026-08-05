#!/usr/bin/env python3
"""
Populate Neo4j with sample graph data for SentinelAPI demo
"""

from neo4j import GraphDatabase
import os

URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
USER = os.getenv("NEO4J_USER", "neo4j")
PASSWORD = os.getenv("NEO4J_PASSWORD", "sentinel_secret")

def populate_graph():
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    
    with driver.session() as session:
        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        
        # Create API Endpoint nodes
        endpoints = [
            {
                "id": "users-profile-v1",
                "name": "GET /v1/users/{id}/profile",
                "host": "api.internal.com",
                "path": "/v1/users/profile",
                "auth_scheme": "None",
                "data_sensitivity": "PII",
                "lifecycle_status": "Active",
                "risk_score": 85,
                "request_count_24h": 1250
            },
            {
                "id": "admin-bulk-delete",
                "name": "POST /v1/admin/users/bulk-delete",
                "host": "api.internal.com",
                "path": "/v1/admin/users/bulk-delete",
                "auth_scheme": "BasicAuth",
                "data_sensitivity": "PII",
                "lifecycle_status": "Active",
                "risk_score": 92,
                "request_count_24h": 45
            },
            {
                "id": "payments-transactions",
                "name": "GET /v2/payments/transactions",
                "host": "api.internal.com",
                "path": "/v2/payments/transactions",
                "auth_scheme": "OAuth2",
                "data_sensitivity": "Financial",
                "lifecycle_status": "Active",
                "risk_score": 78,
                "request_count_24h": 3200
            },
            {
                "id": "products-v1",
                "name": "GET /v1/products",
                "host": "api.internal.com",
                "path": "/v1/products",
                "auth_scheme": "OAuth2",
                "data_sensitivity": "Public",
                "lifecycle_status": "Active",
                "risk_score": 35,
                "request_count_24h": 15000
            },
            {
                "id": "orders-v1",
                "name": "POST /v1/orders",
                "host": "api.internal.com",
                "path": "/v1/orders",
                "auth_scheme": "OAuth2",
                "data_sensitivity": "Internal",
                "lifecycle_status": "Active",
                "risk_score": 42,
                "request_count_24h": 8500
            },
            {
                "id": "inventory-stock",
                "name": "GET /v1/inventory/stock",
                "host": "api.internal.com",
                "path": "/v1/inventory/stock",
                "auth_scheme": "OAuth2",
                "data_sensitivity": "Internal",
                "lifecycle_status": "Active",
                "risk_score": 28,
                "request_count_24h": 5600
            },
            {
                "id": "health-check",
                "name": "GET /health",
                "host": "api.internal.com",
                "path": "/health",
                "auth_scheme": "None",
                "data_sensitivity": "Public",
                "lifecycle_status": "Active",
                "risk_score": 5,
                "request_count_24h": 50000
            }
        ]
        
        for ep in endpoints:
            session.run(
                """
                CREATE (n:API_Endpoint {
                    id: $id,
                    name: $name,
                    host: $host,
                    path: $path,
                    auth_scheme: $auth_scheme,
                    data_sensitivity: $data_sensitivity,
                    lifecycle_status: $lifecycle_status,
                    risk_score: $risk_score,
                    request_count_24h: $request_count_24h
                })
                """,
                **ep
            )
        
        # Create Service nodes
        services = [
            {"id": "user-service", "name": "User Service", "host": "user-service.internal.com", "description": "Manages user profiles and account data"},
            {"id": "payment-service", "name": "Payment Service", "host": "payment-service.internal.com", "description": "Processes payments and transactions"},
            {"id": "order-service", "name": "Order Service", "host": "order-service.internal.com", "description": "Manages orders and fulfillment"},
            {"id": "inventory-service", "name": "Inventory Service", "host": "inventory-service.internal.com", "description": "Tracks inventory and stock levels"}
        ]
        
        for svc in services:
            session.run(
                """
                CREATE (n:Service {
                    id: $id,
                    name: $name,
                    host: $host,
                    description: $description
                })
                """,
                **svc
            )
        
        # Create DataAsset nodes
        assets = [
            {"id": "user-database", "name": "User Database", "type": "PostgreSQL", "sensitivity": "PII", "description": "Contains user profiles, emails, and personal information"},
            {"id": "payment-database", "name": "Payment Database", "type": "PostgreSQL", "sensitivity": "Financial", "description": "Contains payment records and transaction history"},
            {"id": "inventory-database", "name": "Inventory Database", "type": "PostgreSQL", "sensitivity": "Internal", "description": "Contains product inventory and stock information"}
        ]
        
        for asset in assets:
            session.run(
                """
                CREATE (n:DataAsset {
                    id: $id,
                    name: $name,
                    type: $type,
                    sensitivity: $sensitivity,
                    description: $description
                })
                """,
                **asset
            )
        
        # Create EXPOSES relationships
        exposes = [
            ("user-service", "users-profile-v1"),
            ("user-service", "admin-bulk-delete"),
            ("payment-service", "payments-transactions"),
            ("order-service", "orders-v1"),
            ("inventory-service", "inventory-stock")
        ]
        
        for service_id, endpoint_id in exposes:
            session.run(
                """
                MATCH (s:Service {id: $service_id}), (e:API_Endpoint {id: $endpoint_id})
                CREATE (s)-[:EXPOSES]->(e)
                """,
                service_id=service_id,
                endpoint_id=endpoint_id
            )
        
        # Create ACCESSES relationships
        accesses = [
            ("users-profile-v1", "user-database"),
            ("admin-bulk-delete", "user-database"),
            ("payments-transactions", "payment-database"),
            ("orders-v1", "inventory-database"),
            ("inventory-stock", "inventory-database")
        ]
        
        for endpoint_id, asset_id in accesses:
            session.run(
                """
                MATCH (e:API_Endpoint {id: $endpoint_id}), (a:DataAsset {id: $asset_id})
                CREATE (e)-[:ACCESSES]->(a)
                """,
                endpoint_id=endpoint_id,
                asset_id=asset_id
            )
        
        # Create CALLS relationships
        calls = [
            ("orders-v1", "inventory-stock"),
            ("orders-v1", "payments-transactions"),
            ("order-service", "inventory-service"),
            ("order-service", "payment-service")
        ]
        
        for from_id, to_id in calls:
            session.run(
                """
                MATCH (a {id: $from_id}), (b {id: $to_id})
                CREATE (a)-[:CALLS]->(b)
                """,
                from_id=from_id,
                to_id=to_id
            )
        
        # Verify
        result = session.run("""
            RETURN 
                (size([(n:API_Endpoint) RETURN n])) as api_endpoints,
                (size([(n:Service) RETURN n])) as services,
                (size([(n:DataAsset) RETURN n])) as data_assets,
                (size([(r:EXPOSES) RETURN r])) as exposes_rels,
                (size([(r:ACCESSES) RETURN r])) as accesses_rels,
                (size([(r:CALLS) RETURN r])) as calls_rels
        """)
        
        for record in result:
            print(f"✓ Created {record['api_endpoints']} API Endpoints")
            print(f"✓ Created {record['services']} Services")
            print(f"✓ Created {record['data_assets']} Data Assets")
            print(f"✓ Created {record['exposes_rels']} EXPOSES relationships")
            print(f"✓ Created {record['accesses_rels']} ACCESSES relationships")
            print(f"✓ Created {record['calls_rels']} CALLS relationships")
    
    driver.close()
    print("\n✓ Graph population complete!")

if __name__ == "__main__":
    populate_graph()

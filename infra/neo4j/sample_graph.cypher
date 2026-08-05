// SentinelAPI — Sample Graph Data for Neo4j
// Creates API endpoints, services, and data assets with relationships

// Clear existing data
MATCH (n) DETACH DELETE n;

// ---------------------------------------------------------------------------
// Create API Endpoint Nodes
// ---------------------------------------------------------------------------

CREATE (users_profile:API_Endpoint {
  id: "users-profile-v1",
  name: "GET /v1/users/{id}/profile",
  host: "api.internal.com",
  path: "/v1/users/profile",
  auth_scheme: "None",
  data_sensitivity: "PII",
  lifecycle_status: "Active",
  risk_score: 85,
  request_count_24h: 1250
});

CREATE (admin_bulk_delete:API_Endpoint {
  id: "admin-bulk-delete",
  name: "POST /v1/admin/users/bulk-delete",
  host: "api.internal.com",
  path: "/v1/admin/users/bulk-delete",
  auth_scheme: "BasicAuth",
  data_sensitivity: "PII",
  lifecycle_status: "Active",
  risk_score: 92,
  request_count_24h: 45
});

CREATE (payments_transactions:API_Endpoint {
  id: "payments-transactions",
  name: "GET /v2/payments/transactions",
  host: "api.internal.com",
  path: "/v2/payments/transactions",
  auth_scheme: "OAuth2",
  data_sensitivity: "Financial",
  lifecycle_status: "Active",
  risk_score: 78,
  request_count_24h: 3200
});

CREATE (products:API_Endpoint {
  id: "products-v1",
  name: "GET /v1/products",
  host: "api.internal.com",
  path: "/v1/products",
  auth_scheme: "OAuth2",
  data_sensitivity: "Public",
  lifecycle_status: "Active",
  risk_score: 35,
  request_count_24h: 15000
});

CREATE (orders:API_Endpoint {
  id: "orders-v1",
  name: "POST /v1/orders",
  host: "api.internal.com",
  path: "/v1/orders",
  auth_scheme: "OAuth2",
  data_sensitivity: "Internal",
  lifecycle_status: "Active",
  risk_score: 42,
  request_count_24h: 8500
});

CREATE (inventory:API_Endpoint {
  id: "inventory-stock",
  name: "GET /v1/inventory/stock",
  host: "api.internal.com",
  path: "/v1/inventory/stock",
  auth_scheme: "OAuth2",
  data_sensitivity: "Internal",
  lifecycle_status: "Active",
  risk_score: 28,
  request_count_24h: 5600
});

CREATE (health:API_Endpoint {
  id: "health-check",
  name: "GET /health",
  host: "api.internal.com",
  path: "/health",
  auth_scheme: "None",
  data_sensitivity: "Public",
  lifecycle_status: "Active",
  risk_score: 5,
  request_count_24h: 50000
});

// ---------------------------------------------------------------------------
// Create Service Nodes
// ---------------------------------------------------------------------------

CREATE (auth_service:Service {
  id: "auth-service",
  name: "Authentication Service",
  host: "auth-service.internal.com",
  description: "Handles user authentication and token validation"
});

CREATE (user_service:Service {
  id: "user-service",
  name: "User Service",
  host: "user-service.internal.com",
  description: "Manages user profiles and account data"
});

CREATE (payment_service:Service {
  id: "payment-service",
  name: "Payment Service",
  host: "payment-service.internal.com",
  description: "Processes payments and transactions"
});

CREATE (order_service:Service {
  id: "order-service",
  name: "Order Service",
  host: "order-service.internal.com",
  description: "Manages orders and fulfillment"
});

CREATE (inventory_service:Service {
  id: "inventory-service",
  name: "Inventory Service",
  host: "inventory-service.internal.com",
  description: "Tracks inventory and stock levels"
});

// ---------------------------------------------------------------------------
// Create Data Asset Nodes
// ---------------------------------------------------------------------------

CREATE (user_db:DataAsset {
  id: "user-database",
  name: "User Database",
  type: "PostgreSQL",
  sensitivity: "PII",
  description: "Contains user profiles, emails, and personal information"
});

CREATE (payment_db:DataAsset {
  id: "payment-database",
  name: "Payment Database",
  type: "PostgreSQL",
  sensitivity: "Financial",
  description: "Contains payment records and transaction history"
});

CREATE (inventory_db:DataAsset {
  id: "inventory-database",
  name: "Inventory Database",
  type: "PostgreSQL",
  sensitivity: "Internal",
  description: "Contains product inventory and stock information"
});

CREATE (user_cache:DataAsset {
  id: "user-cache",
  name: "User Cache",
  type: "Redis",
  sensitivity: "PII",
  description: "Cached user session and profile data"
});

// ---------------------------------------------------------------------------
// Create Relationships (EXPOSES)
// ---------------------------------------------------------------------------

MATCH (auth_service), (health)
CREATE (auth_service)-[:EXPOSES {observed_at: datetime()}]->(health);

MATCH (user_service), (users_profile)
CREATE (user_service)-[:EXPOSES {observed_at: datetime()}]->(users_profile);

MATCH (user_service), (admin_bulk_delete)
CREATE (user_service)-[:EXPOSES {observed_at: datetime()}]->(admin_bulk_delete);

MATCH (payment_service), (payments_transactions)
CREATE (payment_service)-[:EXPOSES {observed_at: datetime()}]->(payments_transactions);

MATCH (order_service), (orders)
CREATE (order_service)-[:EXPOSES {observed_at: datetime()}]->(orders);

MATCH (inventory_service), (inventory)
CREATE (inventory_service)-[:EXPOSES {observed_at: datetime()}]->(inventory);

// ---------------------------------------------------------------------------
// Create Relationships (ACCESSES - API to Data)
// ---------------------------------------------------------------------------

MATCH (users_profile), (user_db)
CREATE (users_profile)-[:ACCESSES {schema_ref: "users.profile"}]->(user_db);

MATCH (users_profile), (user_cache)
CREATE (users_profile)-[:ACCESSES {schema_ref: "cache.user_session"}]->(user_cache);

MATCH (admin_bulk_delete), (user_db)
CREATE (admin_bulk_delete)-[:ACCESSES {schema_ref: "users.*"}]->(user_db);

MATCH (payments_transactions), (payment_db)
CREATE (payments_transactions)-[:ACCESSES {schema_ref: "payments.transactions"}]->(payment_db);

MATCH (orders), (inventory_db)
CREATE (orders)-[:ACCESSES {schema_ref: "inventory.stock"}]->(inventory_db);

MATCH (inventory), (inventory_db)
CREATE (inventory)-[:ACCESSES {schema_ref: "inventory.*"}]->(inventory_db);

// ---------------------------------------------------------------------------
// Create Relationships (CALLS - API to API)
// ---------------------------------------------------------------------------

MATCH (orders), (inventory)
CREATE (orders)-[:CALLS {source: "traffic", observed_at: datetime()}]->(inventory);

MATCH (orders), (payments_transactions)
CREATE (orders)-[:CALLS {source: "traffic", observed_at: datetime()}]->(payments_transactions);

MATCH (users_profile), (health)
CREATE (users_profile)-[:CALLS {source: "static_analysis", observed_at: datetime()}]->(health);

MATCH (admin_bulk_delete), (users_profile)
CREATE (admin_bulk_delete)-[:CALLS {source: "traffic", observed_at: datetime()}]->(users_profile);

// ---------------------------------------------------------------------------
// Create Relationships (CALLS - Service to Service)
// ---------------------------------------------------------------------------

MATCH (order_service), (inventory_service)
CREATE (order_service)-[:CALLS {source: "traffic", observed_at: datetime()}]->(inventory_service);

MATCH (order_service), (payment_service)
CREATE (order_service)-[:CALLS {source: "traffic", observed_at: datetime()}]->(payment_service);

MATCH (user_service), (auth_service)
CREATE (user_service)-[:CALLS {source: "traffic", observed_at: datetime()}]->(auth_service);

MATCH (payment_service), (auth_service)
CREATE (payment_service)-[:CALLS {source: "traffic", observed_at: datetime()}]->(auth_service);

// Return summary
RETURN 
  (SELECT count(*) FROM (MATCH (n:API_Endpoint) RETURN n)) as api_endpoints,
  (SELECT count(*) FROM (MATCH (n:Service) RETURN n)) as services,
  (SELECT count(*) FROM (MATCH (n:DataAsset) RETURN n)) as data_assets;

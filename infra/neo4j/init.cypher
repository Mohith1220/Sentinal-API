// SentinelAPI — Neo4j constraint and index initialisation script
// Creates node uniqueness constraints and property indexes for all node labels
// and relationship types from design §4.2.
//
// Run once against a fresh Neo4j 5 instance.
// All statements are idempotent (IF NOT EXISTS).

// ---------------------------------------------------------------------------
// Node label: API_Endpoint
// ---------------------------------------------------------------------------

// Uniqueness constraint on the primary key (mirrors PostgreSQL api_endpoints.id)
CREATE CONSTRAINT api_endpoint_id_unique IF NOT EXISTS
    FOR (n:API_Endpoint)
    REQUIRE n.id IS UNIQUE;

// Index on lifecycle_status for fast Zombie/Orphaned lookups
CREATE INDEX api_endpoint_lifecycle_status IF NOT EXISTS
    FOR (n:API_Endpoint)
    ON (n.lifecycle_status);

// Index on risk_score for heatmap and blast-radius queries
CREATE INDEX api_endpoint_risk_score IF NOT EXISTS
    FOR (n:API_Endpoint)
    ON (n.risk_score);

// Index on deleted_at so soft-delete filters are efficient
CREATE INDEX api_endpoint_deleted_at IF NOT EXISTS
    FOR (n:API_Endpoint)
    ON (n.deleted_at);

// ---------------------------------------------------------------------------
// Node label: Service
// ---------------------------------------------------------------------------

CREATE CONSTRAINT service_id_unique IF NOT EXISTS
    FOR (n:Service)
    REQUIRE n.id IS UNIQUE;

CREATE INDEX service_name IF NOT EXISTS
    FOR (n:Service)
    ON (n.name);

CREATE INDEX service_deleted_at IF NOT EXISTS
    FOR (n:Service)
    ON (n.deleted_at);

// ---------------------------------------------------------------------------
// Node label: DataAsset
// ---------------------------------------------------------------------------

CREATE CONSTRAINT data_asset_id_unique IF NOT EXISTS
    FOR (n:DataAsset)
    REQUIRE n.id IS UNIQUE;

CREATE INDEX data_asset_sensitivity IF NOT EXISTS
    FOR (n:DataAsset)
    ON (n.sensitivity);

CREATE INDEX data_asset_deleted_at IF NOT EXISTS
    FOR (n:DataAsset)
    ON (n.deleted_at);

// ---------------------------------------------------------------------------
// Relationship type: CALLS  (API_Endpoint -> API_Endpoint)
// ---------------------------------------------------------------------------
// Neo4j 5 supports relationship property indexes.

CREATE INDEX calls_observed_at IF NOT EXISTS
    FOR ()-[r:CALLS]-()
    ON (r.observed_at);

// ---------------------------------------------------------------------------
// Relationship type: EXPOSES  (Service -> API_Endpoint)
// ---------------------------------------------------------------------------
// No additional property index needed beyond node constraints.

// ---------------------------------------------------------------------------
// Relationship type: ACCESSES  (API_Endpoint -> DataAsset)
// ---------------------------------------------------------------------------

CREATE INDEX accesses_schema_ref IF NOT EXISTS
    FOR ()-[r:ACCESSES]-()
    ON (r.schema_ref);

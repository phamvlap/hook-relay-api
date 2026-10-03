from dataclasses import dataclass


class RateLimitTierName:
    """Pre-defined names for rate limit tiers."""

    INGESTION = "ingest"
    READS = "reads"
    WRITES = "writes"
    SENSITIVE = "sensitive"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Configuration definition for a specific rate limit tier."""

    capacity: int
    refill_rate: float
    name: str
    description: str = ""

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError("RateLimitConfig capacity must be greater than 0.")
        if self.refill_rate <= 0:
            raise ValueError("RateLimitConfig refill_rate must be greater than 0.")


class RateLimitTiers:
    """Pre-configured rate limiting tiers categorized by endpoint workload and risk profile."""

    # Tier 1: High-Volume Ingestion (POST /api/v1/events)
    # Allows fast asynchronous ingestion with high bursts while smoothing traffic to workers.
    INGESTION = RateLimitConfig(
        capacity=100,
        refill_rate=50.0,
        name=RateLimitTierName.INGESTION,
        description="High-volume webhook ingestion",
    )

    # Tier 2: Read & Pagination Queries (GET /api/v1/...)
    # Protects PostgreSQL read replicas and connection pools from expensive SELECT and JOIN scans.
    READS = RateLimitConfig(
        capacity=40,
        refill_rate=20.0,
        name=RateLimitTierName.READS,
        description="Read queries, listings, and pagination",
    )

    # Tier 3: Resource Mutations (POST/PATCH/DELETE /api/v1/endpoints)
    # Limits relational writes, table locks, and configuration changes.
    WRITES = RateLimitConfig(
        capacity=20,
        refill_rate=10.0,
        name=RateLimitTierName.WRITES,
        description="Endpoint creations, updates, and deletions",
    )

    # Tier 4: Sensitive Operations & Manual Triggers (rotate-secret, retry delivery)
    # Restricts CPU-intensive crypto hashing operations and manual background job dispatching.
    SENSITIVE = RateLimitConfig(
        capacity=5,
        refill_rate=2.0,
        name=RateLimitTierName.SENSITIVE,
        description="Cryptographic secret rotation and manual delivery retries",
    )

    # Tier 5: Public / Unauthenticated Fallback (IP-based)
    # Defends against unauthenticated port scanning and credential brute-forcing.
    PUBLIC = RateLimitConfig(
        capacity=15,
        refill_rate=5.0,
        name=RateLimitTierName.PUBLIC,
        description="Unauthenticated and public endpoint protection",
    )

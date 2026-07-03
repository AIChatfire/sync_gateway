# ADR-0001: Keep a Modular Gateway With Runtime Resilience Boundaries

## Status
Accepted

## Context
Sync Gateway routes synchronous generation requests to multiple downstream Providers.
The system needs higher availability and future extensibility, but the current scale and
team context do not justify splitting routing, transformation, configuration, and proxying
into separate deployable services yet.

Key forces:

- Synchronous image/text generation calls are usually downstream I/O bound and can be slow.
- One broken Provider script or one unhealthy downstream must not break other Providers.
- Config changes should be hot-applied through Nacos without restarting all instances.
- The service should remain stateless enough to run multiple replicas behind a load balancer.
- Operational complexity should stay low while the Provider surface is still evolving.

## Decision
Keep Sync Gateway as a modular FastAPI service and introduce explicit runtime boundaries:

- `GatewayRuntimeState` owns the active config snapshot, compiled Provider transformers,
  provider build errors, and last config error.
- `NacosConfigManager` applies config through listeners and keeps bounded history with source
  metadata for rollback and diagnostics.
- `ProxyClient` owns downstream HTTP connection pooling plus Provider-level concurrency,
  failure counting, circuit breaking, and opt-in retries.
- `/live`, `/ready`, and `/health` expose separate liveness, readiness, and diagnostic semantics.
- Provider extension remains configuration-first through `routes`, `endpoints`, mappings,
  scripts, and `resilience`.

## Consequences

### Positive
- A bad Provider can degrade independently while other Providers keep serving traffic.
- Multi-instance deployment stays simple because request processing remains stateless.
- K8s, Docker Compose, and load balancers can remove unready instances via `/ready`.
- Adding a Provider or endpoint remains mostly config-driven.
- Future extraction to separate services remains possible because module boundaries are clearer.

### Negative
- Circuit breaker state is per process, not shared across replicas.
- Config history remains local to each instance; Nacos/Git remains the source of truth.
- Provider scripts still execute in-process, so script complexity must be controlled.

### Neutral
- Retries default to zero because synchronous POST generation can be non-idempotent.
- Global HTTP connection pool limits and per-Provider concurrency limits need production tuning.

## Alternatives Considered

**Split into microservices now**

Rejected for now. It would add network hops, deployment orchestration, and observability burden
before the Provider boundaries and traffic profile are stable.

**Keep existing globals and only add more config**

Rejected. It would not address hot-update race clarity, provider isolation, or future ownership
of runtime state.

**Use a shared Redis-backed circuit breaker**

Deferred. It may be useful at larger scale, but process-local circuit state is enough for the
current Docker/K8s-ready deployment model and avoids adding a hard runtime dependency.

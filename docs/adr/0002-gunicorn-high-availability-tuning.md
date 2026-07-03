# ADR-0002: Tune Gunicorn Defaults for High Availability

## Status
Accepted

## Context
Sync Gateway handles synchronous downstream generation calls. Requests can run close to
provider timeouts, so a production restart or worker recycle must avoid dropping in-flight
requests where possible. The service also runs in containers behind a load balancer, where
socket backlog, forwarded headers, worker heartbeats, and stop grace periods affect observed
availability.

## Decision
Use conservative Gunicorn defaults aimed at HA container deployments:

- Keep a multi-worker default with at least two workers per instance.
- Set `graceful_timeout` to the same default as `timeout` so rolling restarts can finish
  long synchronous requests.
- Use `/dev/shm` for worker temporary heartbeat files when available.
- Add backlog, request header limits, forwarded-header trust configuration, access log
  correlation fields, output capture, and optional StatsD emission.
- Align Docker Compose `stop_grace_period` with Gunicorn graceful shutdown timing.

## Consequences

### Positive
- Rolling deploys and worker recycling are less likely to interrupt in-flight requests.
- Worker heartbeats are less exposed to container filesystem stalls.
- Short traffic spikes can be queued by the master socket before workers accept them.
- Logs and optional StatsD metrics give operators better visibility into worker behavior.

### Negative
- Longer graceful shutdown can slow deploy rollback if many requests are still running.
- `GUNICORN_FORWARDED_ALLOW_IPS=*` is convenient behind a trusted load balancer but should be
  narrowed if the container is exposed directly.

### Neutral
- Explicit `GUNICORN_WORKERS` values remain operator-controlled and are not capped by the
  default worker limit.

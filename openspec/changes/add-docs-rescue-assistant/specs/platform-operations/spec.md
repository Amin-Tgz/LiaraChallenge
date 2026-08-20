## Purpose

Keeps the system honest when things go wrong — every failure names its own cause, readiness reflects whether the system can actually answer, provider outages degrade gracefully, and deployments roll back rather than serving a broken index.

## ADDED Requirements

### Requirement: Every error identifies its own cause

The system SHALL NOT emit a generic failure or empty-result message that conflates distinct causes. Every failure SHALL carry a stable machine-readable code, a user-facing message in Persian stating the actual cause, and structured log context.

#### Scenario: Empty index and empty results are distinct

- **WHEN** a question is asked while no index is active, and separately when a healthy index returns nothing above threshold
- **THEN** the two cases produce different error codes and different user-facing messages, one identifying a system fault and the other identifying an absence of relevant documentation

#### Scenario: Consistent vocabulary

- **WHEN** a failure is surfaced in an API response, recorded in logs, and counted on the dashboard
- **THEN** the same error code identifies it in all three places

#### Scenario: Internal detail not leaked

- **WHEN** an unexpected internal failure occurs
- **THEN** the user receives a message stating the cause category and next step, without stack traces or provider internals

### Requirement: Liveness and readiness are distinct

The system SHALL expose a liveness endpoint reporting only that the process is running, and a readiness endpoint reporting the status of each dependency individually. Readiness SHALL be negative if any dependency check fails, including the absence of an active index.

#### Scenario: Per-dependency reporting

- **WHEN** the readiness endpoint is queried
- **THEN** the response reports each dependency's status individually rather than a single opaque value

#### Scenario: No active index blocks readiness

- **WHEN** the system is running with all infrastructure reachable but no active index version
- **THEN** readiness is negative and identifies the missing index as the reason

#### Scenario: Traffic withheld

- **WHEN** a newly deployed instance reports negative readiness
- **THEN** it does not receive user traffic and the previously healthy release continues serving

### Requirement: Correlation across components

Requests SHALL carry correlation identifiers — trace, session, conversation, job, provider request, and index version — through logs and telemetry wherever applicable.

#### Scenario: Request traceable end to end

- **WHEN** a question produces retrieval and generation activity
- **THEN** the resulting log records share correlation identifiers allowing the request to be reconstructed

### Requirement: Provider resilience

Model requests SHALL pass through a gateway providing retries with backoff, honoring server-supplied retry delays, provider and model fallback, circuit breaking, and request timeouts. Retries SHALL apply only to transient failures; validation and authentication failures SHALL fail immediately.

#### Scenario: Transient failure retried

- **WHEN** a provider returns a timeout, rate-limit, or server error
- **THEN** the request is retried with backoff

#### Scenario: Permanent failure not retried

- **WHEN** a provider returns a validation or authentication error
- **THEN** the request fails immediately without retry

#### Scenario: Fallback on primary failure

- **WHEN** the primary provider is unavailable and a secondary is configured
- **THEN** the request is served by the secondary and the fallback occurrence is recorded

#### Scenario: All providers unavailable

- **WHEN** no configured provider can serve the request
- **THEN** the user's question and job are preserved, a distinct error code is returned, and the user is told the service is temporarily unavailable

#### Scenario: Retry amplification prevented

- **WHEN** the gateway is retrying a model request
- **THEN** the worker does not simultaneously retry the same model request, limiting its own retries to infrastructure failures

### Requirement: Abuse and cost controls

The system SHALL rate limit by client address and session, bound the accepted question length and conversation history depth, and enforce token budgets.

#### Scenario: Rate limit enforced

- **WHEN** a client exceeds the configured request rate
- **THEN** further requests are rejected with the rate-limited error code until the window resets

#### Scenario: Oversized input rejected

- **WHEN** a submitted question exceeds the configured maximum length
- **THEN** it is rejected with a message stating the limit

### Requirement: Secret protection

Credentials SHALL be supplied through deployment environment configuration only. They SHALL NOT appear in the repository, in client-delivered assets, or in logs.

#### Scenario: Secrets absent from client

- **WHEN** the web application is delivered to a browser
- **THEN** no provider credential is present in the delivered assets

#### Scenario: Logs redacted

- **WHEN** a log record would contain a credential, cookie, or token
- **THEN** that value is redacted

### Requirement: Telemetry failure is never user-visible

Failures in tracing, metrics, or logging infrastructure SHALL NOT cause a user request to fail.

#### Scenario: Telemetry backend unavailable

- **WHEN** the telemetry backend is unreachable during a request
- **THEN** the user's request completes normally and the telemetry failure is recorded locally

### Requirement: Operational metrics recorded

The system SHALL record request counts, latency, and error rates; queue depth and wait time; job outcomes including retries; provider fallback occurrences and circuit state; token usage and cost; cache hit rate; retrieval latency; FAQ resolution outcomes; transitions to each rescue tool; the active index commit and status; and the count of questions answered without sufficient evidence.

The API SHALL expose runtime counters and latency distributions in Prometheus
exposition format. Prometheus SHALL persist metrics, Grafana SHALL persist
dashboards and alert rules, and Loki SHALL persist structured logs received
through Grafana Alloy. Opik SHALL remain the retrieval, generation, and agent
trace backend. Monitoring failures SHALL remain isolated from user requests.

#### Scenario: Monitoring survives restart

- **WHEN** Prometheus, Grafana, or Loki is restarted or redeployed
- **THEN** retained metrics, dashboards, alert rules, and logs remain available from persistent storage

#### Scenario: Monitoring backend unavailable

- **WHEN** Prometheus, Grafana, Loki, Alloy, or Opik is unavailable during a rescue request
- **THEN** the request continues and the telemetry delivery failure is logged without exposing credentials


#### Scenario: Cost attributable

- **WHEN** a request consumes model tokens
- **THEN** the token usage and computed cost are recorded against that request

### Requirement: Deployment safety

Deployment SHALL proceed only after continuous integration succeeds, SHALL use versioned immutable images, SHALL apply migrations in a controlled manner, SHALL verify readiness after deployment, and SHALL roll back on failure.

#### Scenario: Failed readiness rolls back

- **WHEN** a deployed release fails its post-deployment readiness verification
- **THEN** the deployment is rolled back and the prior release continues serving

#### Scenario: Graceful shutdown

- **WHEN** a service is instructed to shut down
- **THEN** it stops accepting new work, completes or safely releases in-flight work, and closes streaming connections so clients can reconnect

# ADR 0001: Signal and semaphore hardening

## Status

Accepted.

## Context

UniversalCrawlerProplus coordinates PyQt6 GUI updates, Web UI configuration writes, EventBus fan-out, crawler threads, and download workers. These boundaries must stay responsive and crash-safe under high concurrency.

## Decision

- Use a single application EventBus for runtime configuration events.
- Dispatch GUI-facing runtime setting updates onto the Qt GUI thread.
- Bound nested EventBus publication with a thread-local depth guard.
- Capture uncaught Python exceptions through `sys.excepthook` and route them to `debug_logger`.
- Protect crawler emissions with crawl budgets, per-platform rate limits, and PII sanitization.
- Store Qt connection handles and clean them up through scoped registries.
- Release download dispatch semaphore slots from `finally` paths.
- Keep short `QRunnable` tasks decoupled from panels through weak references and QObject signal carriers.

## Consequences

The GUI and Web UI remain more responsive because crawler/download backpressure and config fan-out are explicit. The tradeoff is slightly more guardrail code in low-level helpers, but failures now surface as observable logs instead of silent UI stalls or process crashes.

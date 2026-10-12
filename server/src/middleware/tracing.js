import crypto from "crypto";

/**
 * Distributed tracing middleware:
 * Ensures every incoming HTTP request carries an x-trace-id correlation header.
 * Propagates traceId down to async workers, logger, and downstream ML service calls.
 */
export function tracingMiddleware(req, res, next) {
  const incomingTraceId = req.headers["x-trace-id"] || req.headers["x-correlation-id"];
  const traceId = incomingTraceId || crypto.randomUUID();

  req.traceId = traceId;
  res.setHeader("x-trace-id", traceId);

  next();
}


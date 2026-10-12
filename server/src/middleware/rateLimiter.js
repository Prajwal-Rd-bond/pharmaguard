// Sliding window in-memory rate limiter middleware
export function rateLimiter({ windowMs = 15 * 60 * 1000, max = 100, message = "Too many requests, please try again later." } = {}) {
  const requests = new Map();

  // Periodic cleanup of expired IP records
  const interval = setInterval(() => {
    const now = Date.now();
    for (const [ip, timestamps] of requests.entries()) {
      const valid = timestamps.filter((t) => now - t < windowMs);
      if (valid.length === 0) {
        requests.delete(ip);
      } else {
        requests.set(ip, valid);
      }
    }
  }, windowMs);

  // Allow node process to exit cleanly without keeping interval alive
  if (interval.unref) interval.unref();

  return (req, res, next) => {
    const ip = req.ip || req.headers["x-forwarded-for"] || req.socket.remoteAddress || "unknown";
    const now = Date.now();
    const timestamps = (requests.get(ip) || []).filter((t) => now - t < windowMs);

    if (timestamps.length >= max) {
      const oldest = timestamps[0];
      const resetTime = Math.ceil((oldest + windowMs - now) / 1000);
      res.setHeader("Retry-After", resetTime);
      return res.status(429).json({ error: message, retryAfterSeconds: resetTime });
    }

    timestamps.push(now);
    requests.set(ip, timestamps);

    res.setHeader("X-RateLimit-Limit", max);
    res.setHeader("X-RateLimit-Remaining", max - timestamps.length);

    next();
  };
}


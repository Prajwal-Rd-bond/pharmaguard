import jwt from "jsonwebtoken";
import User from "../models/User.js";

export async function requireAuth(req, res, next) {
  const header = req.headers.authorization || "";
  if (!header.startsWith("Bearer ")) {
    return res.status(401).json({ error: "Missing or malformed Authorization header. Bearer token required." });
  }

  const token = header.slice(7).trim();
  if (!token) {
    return res.status(401).json({ error: "Missing bearer token" });
  }

  try {
    if (!process.env.JWT_SECRET || process.env.JWT_SECRET.length < 32) {
      throw new Error("Server misconfigured: JWT_SECRET missing or insecure");
    }

    const payload = jwt.verify(token, process.env.JWT_SECRET);
    const user = await User.findById(payload.sub);

    if (!user || !user.active) {
      return res.status(401).json({ error: "Invalid, inactive, or deactivated user account." });
    }

    if (payload.smart_context) {
      user.smartContext = {
        patient: payload.patient,
        encounter: payload.encounter,
        scope: payload.scope,
      };
    }

    req.user = user;
    next();
  } catch (err) {
    return res.status(401).json({ error: "Invalid or expired token" });
  }
}

export const authenticate = requireAuth;

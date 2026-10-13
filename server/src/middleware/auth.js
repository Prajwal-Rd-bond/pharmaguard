import jwt from "jsonwebtoken";
import User from "../models/User.js";

export async function requireAuth(req, res, next) {
  const header = req.headers.authorization || "";
  const token = header.startsWith("Bearer ") ? header.slice(7) : req.query?.token || null;
  if (!token) return res.status(401).json({ error: "Missing bearer token" });

  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET || "smart-fhir-dev-secret-pharma-2026");
    let user = await User.findById(payload.sub);
    if (!user && payload.smart_context) {
      // Ephemeral authenticated SMART EHR practitioner context
      user = {
        _id: payload.sub,
        name: `SMART Practitioner (${payload.sub})`,
        role: payload.role || "doctor",
        active: true,
        smartContext: {
          patient: payload.patient,
          encounter: payload.encounter,
          scope: payload.scope,
        },
      };
    }
    if (!user || !user.active) return res.status(401).json({ error: "Invalid or inactive user" });
    req.user = user;
    next();
  } catch (err) {
    return res.status(401).json({ error: "Invalid or expired token" });
  }
}

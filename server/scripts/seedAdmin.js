import "dotenv/config";
import readline from "node:readline";
import path from "node:path";
import { fileURLToPath } from "node:url";
import mongoose from "mongoose";
import { connectDB } from "../src/config/db.js";
import User from "../src/models/User.js";
import { logAction } from "../src/middleware/auditLogger.js";

export function promptInput(question, { input = process.stdin, output = process.stdout } = {}) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input, output });
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer);
    });
  });
}

export async function resolveAdminCredentials(options = {}) {
  const env = options.env || process.env;
  const promptFn = options.promptFn || promptInput;
  const allowPrompt = options.allowPrompt !== undefined ? options.allowPrompt : Boolean(process.stdin?.isTTY);

  let email = env.ADMIN_EMAIL?.trim();
  let password = env.ADMIN_PASSWORD;
  const name = env.ADMIN_NAME?.trim() || "System Administrator";

  if (!email && allowPrompt) {
    email = (await promptFn("Admin email: "))?.trim();
  }
  if (!password && allowPrompt) {
    password = await promptFn("Admin password (min 8 chars): ");
  }

  return { email, password, name };
}

export async function seedAdmin(options = {}) {
  const argv = options.argv || process.argv.slice(2);
  const forceRole = Boolean(options.forceRole || argv.includes("--force-role"));
  const { email, password, name } = await resolveAdminCredentials(options);

  if (!email || !password) {
    console.error("[seed] Error: ADMIN_EMAIL and ADMIN_PASSWORD must be provided via environment or interactive prompt.");
    return { ok: false, code: 1, reason: "missing_credentials" };
  }

  if (typeof password !== "string" || password.length < 8) {
    console.error("[seed] Error: ADMIN_PASSWORD must be at least 8 characters long.");
    return { ok: false, code: 1, reason: "short_password" };
  }

  const connect = options.connectDB || connectDB;
  const disconnect = options.disconnectDB || (() => mongoose.disconnect());
  const mongoUri = options.mongoUri || process.env.MONGO_URI || "mongodb://localhost:27017/pharmaguard";
  await connect(mongoUri);

  try {
    // Check if a user with this email already exists — never overwrite password or role unless --force-role is explicitly passed
    const existingUser = await User.findOne({ email: email.toLowerCase() });
    if (existingUser) {
      if (existingUser.role === "admin") {
        console.log("[seed] Admin user with this email already exists. Preserving existing password and role.");
        await disconnect();
        return { ok: true, code: 0, reason: "already_exists" };
      } else if (forceRole) {
        existingUser.role = "admin";
        await existingUser.save();
        await logAction({
          actor: existingUser._id,
          actorType: "system",
          action: "user.seed_admin_promote",
          details: { role: "admin", email: existingUser.email, forceRole: true },
        });
        console.log("[seed] Promoted existing user to admin via --force-role.");
        await disconnect();
        return { ok: true, code: 0, reason: "promoted" };
      } else {
        console.error("[seed] Error: A user with this email exists with a non-admin role. Refusing to promote or overwrite.");
        await disconnect();
        return { ok: false, code: 1, reason: "role_conflict" };
      }
    }

    // Check if any admin already exists in the system
    const existingAdminCount = await User.countDocuments({ role: "admin" });
    if (existingAdminCount > 0) {
      console.log("[seed] System already has an administrator configured. No action taken.");
      await disconnect();
      return { ok: true, code: 0, reason: "admin_already_configured" };
    }

    // Create the initial admin account
    const admin = new User({
      name,
      email: email.toLowerCase(),
      role: "admin",
      active: true,
    });
    await admin.setPassword(password);
    await admin.save();

    await logAction({
      actor: admin._id,
      actorType: "system",
      action: "user.seed_admin",
      details: { role: "admin", email: admin.email },
    });

    console.log("[seed] Initial administrator account provisioned successfully.");
    await disconnect();
    return { ok: true, code: 0, reason: "created" };
  } catch (err) {
    console.error("[seed] Seeding failed:", err.message);
    await disconnect();
    return { ok: false, code: 1, reason: "exception" };
  }
}

function isDirectScript() {
  if (!process.argv[1]) return false;
  try {
    return path.resolve(fileURLToPath(import.meta.url)).toLowerCase() === path.resolve(process.argv[1]).toLowerCase();
  } catch {
    return false;
  }
}

if (isDirectScript()) {
  seedAdmin().then((res) => process.exit(res.code));
}

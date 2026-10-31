import "dotenv/config";
import path from "node:path";
import { fileURLToPath } from "node:url";
import app from "./app.js";
import { connectDB } from "./config/db.js";
import { assertProductionSecrets, isDevOrTest } from "./config/secrets.js";

const PORT = process.env.PORT || 5000;

export const APPROVED_SEED_ENVIRONMENTS = ["development", "test"];

export function shouldAutoSeed(env, autoSeed) {
  const currentEnv = arguments.length > 0 ? env : process.env.NODE_ENV;
  const currentAutoSeed = arguments.length > 1 ? autoSeed : process.env.AUTO_SEED;

  if (!currentEnv || typeof currentEnv !== "string") return false;
  return APPROVED_SEED_ENVIRONMENTS.includes(currentEnv.trim().toLowerCase()) && currentAutoSeed === "true";
}

export function isDirectExecution(argv1 = process.argv[1], importMetaUrl = import.meta.url) {
  if (!argv1 || typeof argv1 !== "string") return false;
  try {
    const scriptPath = path.resolve(fileURLToPath(importMetaUrl));
    const executedPath = path.resolve(argv1);
    return scriptPath.toLowerCase() === executedPath.toLowerCase();
  } catch {
    return false;
  }
}

export async function start(options = {}) {
  const connect = options.connectDB || connectDB;
  const seeder = options.seedDatabase;
  const serverApp = options.app || app;
  const port = options.port || PORT;
  const env = "env" in options ? options.env : process.env.NODE_ENV;
  const autoSeed = "autoSeed" in options ? options.autoSeed : process.env.AUTO_SEED;
  const mongoUri = options.mongoUri || process.env.MONGO_URI || "mongodb://localhost:27017/pharmaguard";

  if (!isDevOrTest(env) && (options.enforceSecrets === true || !options.connectDB)) {
    assertProductionSecrets({ ...process.env, NODE_ENV: env, ...(options.secrets || {}) });
  }

  await connect(mongoUri);

  // Production safety gate: Seeding requires an explicitly approved non-production environment AND AUTO_SEED=true
  if (shouldAutoSeed(env, autoSeed)) {
    try {
      if (seeder) {
        await seeder();
      } else {
        const { seedDatabase } = await import("./seed.js");
        await seedDatabase();
      }
    } catch (err) {
      console.warn("[server] Auto-seed status:", err.message);
    }
  }

  if (typeof serverApp.listen === "function") {
    return serverApp.listen(port, () => console.log(`[server] PharmaGuard API listening on :${port}`));
  }
}

// Only execute bootstrap when run directly via Node CLI
if (isDirectExecution()) {
  start().catch((err) => {
    console.error("[server] failed to start:", err);
    process.exit(1);
  });
}

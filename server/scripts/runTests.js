process.env.NODE_ENV = "test";
import { spawnSync } from "node:child_process";
import process from "node:process";

const args = ["--test", "test/*.test.js", "tests/**/*.test.js", ...process.argv.slice(2)];
const res = spawnSync(process.execPath, args, { stdio: "inherit", env: process.env });
process.exit(res.status ?? 1);


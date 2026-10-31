process.env.NODE_ENV = "test";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const serverDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function findTestFiles(relDir) {
  const fullDir = path.join(serverDir, relDir);
  if (!fs.existsSync(fullDir)) return [];
  return fs
    .readdirSync(fullDir, { recursive: true })
    .filter((f) => f.endsWith(".test.js"))
    .map((f) => path.join(relDir, f).replace(/\\/g, "/"));
}

const testFiles = [...findTestFiles("test"), ...findTestFiles("tests")];
const args = ["--test", ...testFiles, ...process.argv.slice(2)];
const res = spawnSync(process.execPath, args, { stdio: "inherit", env: process.env, cwd: serverDir });
process.exit(res.status ?? 1);

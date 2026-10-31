import { test, describe } from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { isDirectExecution, shouldAutoSeed, start } from "../src/index.js";

describe("Phase 1 Follow-up — Entry Point & Startup Isolation", () => {
  test("1. isDirectExecution returns true only when resolved process.argv[1] matches script path", () => {
    const dummyUrl = pathToFileURL("C:/pharmaguard/server/src/index.js").href;
    const samePath = "C:/pharmaguard/server/src/index.js";
    const samePathBackslash = "C:\\pharmaguard\\server\\src\\index.js";
    const differentPath = "C:/pharmaguard/server/tests/some_test.js";

    assert.equal(isDirectExecution(samePath, dummyUrl), true);
    assert.equal(isDirectExecution(samePathBackslash, dummyUrl), true);
    assert.equal(isDirectExecution(differentPath, dummyUrl), false);
  });

  test("2. isDirectExecution safely returns false for missing or invalid argv[1]", () => {
    const dummyUrl = pathToFileURL("C:/pharmaguard/server/src/index.js").href;

    assert.equal(isDirectExecution(undefined, dummyUrl), false);
    assert.equal(isDirectExecution(null, dummyUrl), false);
    assert.equal(isDirectExecution("", dummyUrl), false);
    assert.equal(isDirectExecution(123, dummyUrl), false);
    assert.equal(isDirectExecution({}, dummyUrl), false);
  });

  test("3. start() executes seeder only when explicit non-prod env AND autoSeed=true are supplied", async () => {
    let connectCalled = false;
    let seedCalled = false;
    let listenCalled = false;

    const mockConnect = async (uri) => {
      connectCalled = true;
      assert.ok(uri);
    };

    const mockSeeder = async () => {
      seedCalled = true;
    };

    const mockApp = {
      listen: (port, cb) => {
        listenCalled = true;
        return { close: () => {} };
      },
    };

    // Positive case: explicit development and autoSeed=true
    await start({
      connectDB: mockConnect,
      seedDatabase: mockSeeder,
      app: mockApp,
      env: "development",
      autoSeed: "true",
      port: 0,
    });

    assert.equal(connectCalled, true);
    assert.equal(seedCalled, true);
    assert.equal(listenCalled, true);
  });

  test("4. start() skips seeder when env is production, unset, or autoSeed is false/missing", async () => {
    const testCases = [
      { env: "production", autoSeed: "true" },
      { env: undefined, autoSeed: "true" },
      { env: "", autoSeed: "true" },
      { env: "staging", autoSeed: "true" },
      { env: "development", autoSeed: "false" },
      { env: "development", autoSeed: undefined },
      { env: "test", autoSeed: "false" },
    ];

    for (const tc of testCases) {
      let seedCalled = false;
      const mockConnect = async () => {};
      const mockSeeder = async () => {
        seedCalled = true;
      };
      const mockApp = {
        listen: () => ({ close: () => {} }),
      };

      await start({
        connectDB: mockConnect,
        seedDatabase: mockSeeder,
        app: mockApp,
        env: tc.env,
        autoSeed: tc.autoSeed,
        port: 0,
      });

      assert.equal(
        seedCalled,
        false,
        `Seeder should not be called for env="${tc.env}" and autoSeed="${tc.autoSeed}"`
      );
    }
  });

  test("5. Importing index.js does not trigger start() or connect to DB/seeder/listener", async () => {
    const { spawnSync } = await import("node:child_process");
    const { fileURLToPath, pathToFileURL } = await import("node:url");

    const serverDir = path.resolve(fileURLToPath(new URL("..", import.meta.url)));
    const indexPath = path.resolve(serverDir, "src", "index.js");
    const indexUrl = pathToFileURL(indexPath).href;

    const child = spawnSync(
      process.execPath,
      ["--input-type=module", "-e", `import ${JSON.stringify(indexUrl)}; console.log("IMPORT_OK");`],
      {
        cwd: serverDir,
        timeout: 10000,
        encoding: "utf8",
        env: {
          NODE_ENV: "test",
          AUTO_SEED: "true",
          MONGO_URI: "mongodb://127.0.0.1:1/unreachable",
          // pipelineQueue.js attempts a Redis connection at import; known issue deferred to Phase 2
          DISABLE_REDIS: "true",
          PATH: process.env.PATH,
          SYSTEMROOT: process.env.SYSTEMROOT,
        },
      }
    );

    assert.equal(child.error, undefined, "Child process should not error or timeout");
    assert.equal(child.status, 0, `Child process exited with status ${child.status}, stderr: ${child.stderr}`);
    assert.match(child.stdout, /IMPORT_OK/, "stdout must contain IMPORT_OK");

    const combinedOutput = (child.stdout || "") + (child.stderr || "");
    assert.doesNotMatch(combinedOutput, /listening/i, "Output must not contain 'listening'");
    assert.doesNotMatch(combinedOutput, /failed to start/i, "Output must not contain 'failed to start'");
  });
});



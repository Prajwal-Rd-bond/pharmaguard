import axios from "axios";

const client = axios.create({
  baseURL: process.env.ML_SERVICE_URL || "http://localhost:8000",
  timeout: 60_000,
});

// Calls the FastAPI ML service's full pipeline (Module 7 orchestration).
// The FastAPI service performs: deidentify -> extract -> classify -> retrieve -> summarize.
export async function runPipeline({ pipelineRunId, rawText }) {
  const { data } = await client.post("/pipeline/run", { pipeline_run_id: pipelineRunId, raw_text: rawText });
  return data;
}

export default client;

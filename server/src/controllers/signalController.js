import axios from "axios";

const ML_SERVICE_URL = process.env.ML_SERVICE_URL || "http://localhost:8000";

export async function getSignalDashboard(req, res) {
  try {
    const response = await axios.get(`${ML_SERVICE_URL}/analytics/signals/overview`, { timeout: 4000 });
    return res.json(response.data);
  } catch (err) {
    return res.status(503).json({
      error: "signal_service_unavailable",
      message: "Quantitative FAERS signal service is currently unavailable. No synthetic numbers are returned to preserve data integrity.",
    });
  }
}

export async function detectSignal(req, res) {
  const { drug, reaction } = req.query;
  if (!drug || !reaction) {
    return res.status(400).json({ error: "Missing required query parameters 'drug' and 'reaction'" });
  }

  try {
    const response = await axios.get(`${ML_SERVICE_URL}/analytics/signals/detect`, {
      params: { drug, reaction },
      timeout: 4000,
    });
    return res.json(response.data);
  } catch (err) {
    return res.status(503).json({
      error: "signal_service_unavailable",
      message: "Quantitative FAERS signal service is currently unavailable. No synthetic numbers are returned to preserve data integrity.",
    });
  }
}

export async function getKnowledgeGraph(req, res) {
  const { drug } = req.query;
  try {
    const response = await axios.get(`${ML_SERVICE_URL}/analytics/graph/explore`, {
      params: { drug: drug || "amoxicillin" },
      timeout: 4000,
    });
    return res.json(response.data);
  } catch (err) {
    return res.status(503).json({
      error: "graph_service_unavailable",
      message: "Safety Knowledge Graph service is currently unavailable.",
    });
  }
}

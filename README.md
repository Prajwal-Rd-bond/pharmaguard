# PharmaGuard

LLM-Powered Pharmacovigilance and Drug Safety Intelligence Platform.

See `PharmaGuard_Planning.md` (parent folder) for epics, user stories, and architecture.

## Stack

- `client/` — React (Vite) frontend
- `server/` — Node.js + Express API, MongoDB, JWT/RBAC, orchestrates the ML pipeline
- `ml-service/` — Python FastAPI service: de-identification, LLM extraction, ML classification, RAG retrieval, summarization

## Local development (without Docker)

**1. Start Mongo and Qdrant** (or use `docker compose up mongo qdrant`)

**2. ML service**
```bash
cd ml-service
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**3. Server**
```bash
cd server
cp .env.example .env
npm install
npm run dev
```

**4. Client**
```bash
cd client
npm install
npm run dev
```

## Local development (Docker)

```bash
docker compose up --build
```

- Client: http://localhost:5173
- Server API: http://localhost:5000/api
- ML service: http://localhost:8000/docs
- Qdrant dashboard: http://localhost:6333/dashboard

## Default roles

`admin`, `pharmacist`, `doctor`, `researcher` — see `server/src/middleware/rbac.js`.

## Phase 1 (MVP) scope

Auth/RBAC, ADR report intake, de-identification, LLM extraction, ML risk classification,
RAG retrieval (reduced corpus), explainable summary, human approval workflow, minimal audit log.
Analytics dashboard, knowledge graph, and full RAG corpus are Phase 2 — see the planning doc.

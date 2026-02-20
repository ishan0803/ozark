# Ozark

> **High-Velocity Financial Graph Forensics & Network Intelligence**

Ozark is a purpose-built intelligence platform designed for the traversal, analysis, and visualization of multi-hop temporal transaction graphs. By synthesizing deterministic topological parsing with hardware-accelerated rendering, the system exposes money muling networks, multi-layered fraud rings, and obfuscated financial pathways in real-time.

## Architectural Philosophy

Ozark was engineered to solve the latency and serialization bottlenecks inherent in traditional anti-money laundering (AML) and network analysis tools.

- **Streamlined Compute Topologies:** Legacy forensics systems often rely on heavy, distributed message brokers (e.g., Celery/Redis) simply to manage state. Ozark abandons this in favor of a monolithic asynchronous compute pipeline. Utilizing FastAPI with `asyncpg` and SQLAlchemy 2.0, state mutation and analysis execution are bound tightly to the immediate lifecycle of the asynchronous worker. This drastically reduces I/O wait times and serialization overhead during graph ingestion.
- **WebGL-Accelerated Discovery:** Processing million-node graphs computationally is only half the battle; the resulting spatial representation must be fluid. The frontend drops traditional DOM-heavy graph renderers in favor of a `three.js`-backed 3D WebGL force-directed engine. The engine computes repulsive/attractive force vectors natively, allowing investigative analysts to manipulate deep topological maps at 60fps without browser lock-up.
- **Stateless Isomorphism:** Subgraph structural matching is executed deterministically and synchronously. We bypass expensive intermediate state storage, calculating deep structural clones directly in-memory using NetworkX, before flushing the annotated subgraph back to the persistence layer.

## Core Analytic Engines

### 1. Deterministic Ledger Ingestion
Raw unstructured transaction ledgers (CSV/JSON) are streamed directly into an in-memory Pandas dataframe, where edge-node relationships are extracted, deduplicated, and transformed into an adjacency matrix.

### 2. Heuristic Cycle Detection
The analysis runtime actively patrols the directed graph for Eulerian and non-Eulerian cycles. By mathematically proving that capital has returned to its mathematical origin (or a related cluster) over $N$ hops, the engine flags definitive signatures of financial layering and cycle-based money muling without human intervention.

### 3. VF2 Subgraph Isomorphism (Pattern Hunter)
Ozark implements a VF2-based subgraph isomorphism search. Analysts can select an identified threat node, and the engine will immediately scan the macro-graph for any structurally identical sub-networks (e.g., repeating fan-in/fan-out typologies or shell-account clusters) up to a configurable *k*-hop radius.

### 4. Dynamic Risk Stratification
Entities are not evaluated merely by localized volume, but rather by edge-velocity and cyclic participation. The scoring engine calculates structural risk (0 to 100), automatically stratifying nodes into High, Medium, and Low risk brackets, immediately painting the visual canvas to direct analyst attention.

## Technical Stack

### Interface & Visualization (Frontend)
- **Framework:** React 19 + Vite
- **Spatial Rendering:** `react-force-graph-3d` (WebGL / Three.js)
- **Styling & Physics:** TailwindCSS, Framer Motion
- **Identity & Access Management:** Clerk

### Compute & Persistence (Backend)
- **Runtime API:** FastAPI, Uvicorn
- **Graph Mathematics:** NetworkX, NumPy, Pandas
- **Persistence Layer:** PostgreSQL
- **Asynchronous Driver:** `asyncpg`, SQLAlchemy 2.0 (Async)

## Repository Structure

```text
.
├── backend/
│   ├── app/
│   │   ├── api/          # Asynchronous routing and REST interfaces
│   │   ├── core/         # DB config, environment state, and JWT verification
│   │   ├── graph/        # NetworkX logic: Cycle detection, VF2 isomorphism
│   │   ├── models/       # SQLAlchemy 2.0 ORM Definitions
│   │   └── schemas/      # Pydantic rigorous IO validation
│   └── requirements.txt  # Python environment definition
└── money-mulling-frontend/
    ├── src/
    │   ├── components/   # Shared UI (Bento Cards, HexGrid, ForceGraph Canvas)
    │   ├── lib/          # API abstractions
    │   └── pages/        # Route views (Dashboard, Analyzer, Upload)
    └── package.json
```

## Local Initialization

**1. Environment Configuration**
Ensure PostgreSQL is active. Create `.env` files in both the frontend and backend directories containing necessary Clerk keys and Database URIs.

**2. Backend Launch**
```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**3. Frontend Launch**
```bash
cd money-mulling-frontend
npm install
npm run dev
```

"""
Analysis pipeline — runs directly in FastAPI's thread pool via BackgroundTasks.
No Celery, no Redis, no broker. Pure Python + asyncio.

The computation (graph analysis, risk scoring) is CPU-bound and runs in
a ThreadPoolExecutor so it never blocks the uvicorn event loop.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import networkx as nx
import pandas as pd
import structlog
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.services.graph_service import (
    analyze_networks,
    assign_risk_scores,
    build_graph_payload,
    build_structured_output,
    flags_to_json,
    flags_from_json,
)
from app.services.isomorphism_service import find_structural_clones

logger = structlog.get_logger(__name__)

# ── Synchronous DB engine (used inside thread workers) ────────
_sync_engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
SyncSession = sessionmaker(bind=_sync_engine)


def _load_transactions_df(session: Session, dataset_id: str) -> pd.DataFrame:
    """Load all transactions for a dataset from PostgreSQL."""
    result = session.execute(
        text(
            """
            SELECT transaction_id, sender_id, receiver_id, amount, timestamp
            FROM transactions
            WHERE dataset_id = :did
            ORDER BY timestamp
            """
        ),
        {"did": dataset_id},
    )
    rows = result.fetchall()
    if not rows:
        raise ValueError(f"No transactions found for dataset {dataset_id}")

    return pd.DataFrame(
        rows,
        columns=["transaction_id", "sender_id", "receiver_id", "amount", "timestamp"],
    ).assign(
        timestamp=lambda d: pd.to_datetime(d["timestamp"], utc=True, errors="coerce")
    )


# ═══════════════════════════════════════════════════════════════
#  Full Analysis Pipeline  (called via BackgroundTasks)
# ═══════════════════════════════════════════════════════════════

def run_analysis_pipeline(analysis_id: str, dataset_id: str) -> None:
    """
    Full analysis pipeline — runs in a thread pool worker.
    Reads from PostgreSQL, runs graph analysis, writes results back.
    """
    logger.info("analysis_pipeline_start", analysis_id=analysis_id, dataset_id=dataset_id)

    with SyncSession() as session:
        try:
            # Mark as running
            session.execute(
                text("UPDATE analysis_results SET status = 'running' WHERE id = :aid"),
                {"aid": analysis_id},
            )
            session.commit()

            # 1. Load transactions
            t_start = time.monotonic()
            df = _load_transactions_df(session, dataset_id)
            logger.info("data_loaded", rows=len(df))

            # 2. Graph analysis + pattern detection
            G, flags = analyze_networks(df)

            # 3. Risk scoring
            risk_df = assign_risk_scores(list(G.nodes()), flags)

            # 4. D3 graph payload
            graph_payload = build_graph_payload(df, risk_df)

            # 5. Structured output
            processing_time = time.monotonic() - t_start
            structured_output = build_structured_output(G, flags, risk_df, processing_time)

            # 6. Stats
            high_risk_count = int((risk_df["score"] >= 40).sum())
            medium_risk_count = int(((risk_df["score"] > 0) & (risk_df["score"] < 40)).sum())
            stats = {
                "total_nodes": G.number_of_nodes(),
                "total_edges": G.number_of_edges(),
                "total_transactions": len(df),
                "high_risk_count": high_risk_count,
                "medium_risk_count": medium_risk_count,
                "cycles_detected": len(flags["cycles"]),
                "fan_in_detected": len(flags["fan_in"]),
                "fan_out_detected": len(flags["fan_out"]),
                "shells_detected": len(flags["shells"]),
                **structured_output,
            }

            # 7. Persist
            session.execute(
                text(
                    """
                    UPDATE analysis_results
                    SET status = 'completed',
                        graph_json = :graph,
                        risk_json  = :risk,
                        flags_json = :flags,
                        stats_json = :stats,
                        completed_at = :now
                    WHERE id = :aid
                    """
                ),
                {
                    "aid": analysis_id,
                    "graph": json.dumps(graph_payload),
                    "risk": json.dumps(risk_df.to_dict("records")),
                    "flags": flags_to_json(flags),
                    "stats": json.dumps(stats),
                    "now": datetime.now(timezone.utc),
                },
            )
            session.execute(
                text("UPDATE datasets SET status = 'completed' WHERE id = :did"),
                {"did": dataset_id},
            )
            session.commit()
            logger.info("analysis_pipeline_complete", analysis_id=analysis_id)

        except Exception as exc:
            session.rollback()
            session.execute(
                text(
                    """
                    UPDATE analysis_results
                    SET status = 'failed', error_message = :err
                    WHERE id = :aid
                    """
                ),
                {"aid": analysis_id, "err": str(exc)},
            )
            session.commit()
            logger.error("analysis_pipeline_failed", analysis_id=analysis_id, error=str(exc))


# ═══════════════════════════════════════════════════════════════
#  Isomorphism Search  (called via BackgroundTasks)
# ═══════════════════════════════════════════════════════════════

def run_isomorphism_search(
    analysis_id: str, dataset_id: str, target_node: str, hops: int
) -> dict:
    """
    Run VF2 isomorphism search in a thread worker.
    Updates analysis graph_json with match highlights and returns result dict.
    """
    logger.info(
        "isomorphism_search_start",
        analysis_id=analysis_id,
        target_node=target_node,
        hops=hops,
    )

    with SyncSession() as session:
        try:
            df = _load_transactions_df(session, dataset_id)
            G = nx.from_pandas_edgelist(
                df, "sender_id", "receiver_id", create_using=nx.DiGraph()
            )

            match_nodes, match_edges = find_structural_clones(G, target_node, hops)

            row = session.execute(
                text("SELECT risk_json FROM analysis_results WHERE id = :aid"),
                {"aid": analysis_id},
            ).fetchone()

            risk_records = json.loads(row[0]) if row and row[0] else []
            risk_df = pd.DataFrame(risk_records)

            graph_payload = build_graph_payload(df, risk_df, match_nodes, match_edges)

            session.execute(
                text("UPDATE analysis_results SET graph_json = :graph WHERE id = :aid"),
                {"aid": analysis_id, "graph": json.dumps(graph_payload)},
            )
            session.commit()

            result = {
                "match_nodes": match_nodes,
                "match_edges": [[e[0], e[1]] for e in match_edges],
                "match_count": len(match_nodes),
            }
            logger.info("isomorphism_search_complete", **result)
            return result

        except Exception as exc:
            session.rollback()
            logger.error("isomorphism_search_failed", error=str(exc))
            raise

"""Build the IVFFlat index on the CourtListener metadata vectors.

Administrative. Run manually, never from application startup or a request.
This is the only approved write to the live database.

The build takes hours and copies every vector into the index, so it refuses to
start unless the preflight passes: right database, right table, expected row
labels, cosine opclass present, no other index build running, and enough free
disk. Progress is polled from pg_stat_progress_create_index and logged.

    python scripts/build_ivfflat_index.py --check     # preflight only
    python scripts/build_ivfflat_index.py --build     # preflight, then build

Nothing here drops an index. Removing one is a separate, deliberate act.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

NAMESPACE = "courtlistener_metadata"
SOURCE_TYPE = "cluster_metadata"
TABLE = "public.vector_records"
INDEX = "ix_vector_records_cl_meta_cosine"
EXPECTED_DB = "Storage_Pourage"
EXPECTED_DIMS = 1024

# An IVFFlat index holds a copy of every vector, so the build needs at least
# that much free space again, plus room for the concurrent build's temporary
# state. 1.6x is deliberately generous; running a disk out mid-build on a 58 GB
# table is not a situation worth economising into.
DISK_HEADROOM = 1.6


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{stamp}  {message}", flush=True)


def connection_url() -> str:
    """Read the URL from the environment, or the private config as a fallback.

    Never printed. The caller sees failures by exception type only.
    """
    url = os.environ.get("VERIFIER_DATABASE_URL")
    if not url:
        env_path = os.environ.get("VERIFIER_ENV_FILE")
        if env_path and Path(env_path).is_file():
            for line in Path(env_path).read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                if line.strip().startswith("DATABASE_URL"):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not url:
        raise SystemExit(
            "No database URL. Set VERIFIER_DATABASE_URL, or VERIFIER_ENV_FILE "
            "to a file containing DATABASE_URL."
        )
    # SQLAlchemy-style driver suffixes are not valid libpq URLs.
    return re.sub(r"^postgresql\+\w+://", "postgresql://", url)


def connect() -> psycopg.Connection:
    try:
        return psycopg.connect(connection_url(), autocommit=True)
    except Exception as exc:  # noqa: BLE001 - never let a driver error echo the URL
        raise SystemExit(f"Connection failed: {type(exc).__name__}") from None


def preflight(cur) -> int:
    """Verify the live target. Returns the row count to index."""
    failures: list[str] = []

    cur.execute("SELECT current_database(), inet_server_port()")
    database, port = cur.fetchone()
    log(f"target: {database} on port {port}")
    if database != EXPECTED_DB:
        failures.append(f"wrong database: {database!r}, expected {EXPECTED_DB!r}")

    cur.execute("SELECT amname FROM pg_am WHERE amname = 'ivfflat'")
    if not cur.fetchone():
        failures.append("ivfflat access method is not available")

    cur.execute(
        "SELECT 1 FROM pg_opclass WHERE opcname = 'vector_cosine_ops' LIMIT 1"
    )
    if not cur.fetchone():
        failures.append("vector_cosine_ops opclass is missing")

    cur.execute(
        f"SELECT count(*) FROM {TABLE} "
        "WHERE namespace = %s AND source_type = %s",
        (NAMESPACE, SOURCE_TYPE),
    )
    rows = cur.fetchone()[0]
    log(f"rows to index: {rows:,}")
    if rows == 0:
        failures.append("no rows match the expected labels")

    cur.execute(
        f"SELECT count(*) FROM {TABLE} "
        "WHERE namespace = %s AND source_type = %s AND embedding IS NULL",
        (NAMESPACE, SOURCE_TYPE),
    )
    null_embeddings = cur.fetchone()[0]
    if null_embeddings:
        log(f"WARNING: {null_embeddings:,} rows have no embedding")

    cur.execute(
        f"SELECT vector_dims(embedding) FROM {TABLE} "
        "WHERE namespace = %s AND source_type = %s AND embedding IS NOT NULL "
        "LIMIT 1",
        (NAMESPACE, SOURCE_TYPE),
    )
    dims = (cur.fetchone() or [None])[0]
    log(f"vector dimensions: {dims}")
    if dims != EXPECTED_DIMS:
        failures.append(f"expected {EXPECTED_DIMS} dimensions, found {dims}")

    cur.execute("SELECT pid, phase FROM pg_stat_progress_create_index")
    running = cur.fetchall()
    if running:
        failures.append(f"another index build is running: {running}")

    cur.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (INDEX,))
    if cur.fetchone():
        failures.append(f"index {INDEX} already exists")

    cur.execute("SHOW data_directory")
    data_dir = cur.fetchone()[0]
    free = shutil.disk_usage(data_dir).free
    needed = int(rows * EXPECTED_DIMS * 4 * DISK_HEADROOM)
    log(f"free disk at {data_dir}: {free / 1e9:.1f} GB, need ~{needed / 1e9:.1f} GB")
    if free < needed:
        failures.append("not enough free disk for the index")

    if failures:
        for failure in failures:
            log(f"PREFLIGHT FAILED: {failure}")
        raise SystemExit(1)

    log("preflight passed")
    return rows


def lists_for(rows: int) -> int:
    """pgvector's documented guidance: rows/1000 up to 1M, sqrt(rows) beyond.

    Calibrated later against the benchmark; this is only a starting point and
    is logged so the value that shipped is recoverable.

    MEASURED LIMIT, 2026-09-20: this value cannot be used as-is on Windows.
    A build of 10,070,727 rows at lists=3173 was refused with

        memory required is 2619 MB, maintenance_work_mem is 1953 MB

    and Windows caps maintenance_work_mem at 2097151 kB, which is a platform
    limit with no setting that raises it. The k-means step needs roughly
    0.83 MB per list at 1024 dimensions, so the ceiling on this machine is
    about 2360 lists. Anything above that fails immediately, before doing any
    work, and leaves an invalid index stub that must be dropped before a retry.
    """
    return max(1, rows // 1000) if rows <= 1_000_000 else int(math.sqrt(rows))


def watch(conn: psycopg.Connection, stop_after: float | None = None) -> None:
    """Poll build progress on a second connection until the build finishes."""
    with conn.cursor() as cur:
        while True:
            cur.execute(
                "SELECT phase, blocks_done, blocks_total, tuples_done "
                "FROM pg_stat_progress_create_index"
            )
            row = cur.fetchone()
            if row is None:
                return
            phase, done, total, tuples = row
            pct = f"{100 * done / total:.1f}%" if total else "?"
            log(f"  {phase}  blocks {done}/{total} ({pct})  tuples {tuples:,}")
            if stop_after and time.time() > stop_after:
                return
            time.sleep(30)


def build(conn: psycopg.Connection, rows: int) -> None:
    lists = lists_for(rows)
    log(f"lists = {lists} (from {rows:,} rows)")

    with conn.cursor() as cur:
        # Session-scoped only. 64 MB is far too little to cluster 10M vectors
        # and the build would spill constantly. Windows caps this parameter at
        # 2 GB (2097151 kB), so ask for the largest value it will accept
        # rather than a figure that only works on Linux.
        cur.execute("SELECT max_val FROM pg_settings WHERE name = 'maintenance_work_mem'")
        max_kb = int(cur.fetchone()[0])
        want_kb = min(2_000_000, max_kb)
        cur.execute(f"SET maintenance_work_mem = '{want_kb}kB'")
        cur.execute("SET max_parallel_maintenance_workers = 4")
        cur.execute("SET statement_timeout = 0")
        log(
            f"maintenance_work_mem={want_kb / 1_000_000:.1f}GB "
            f"(cap {max_kb / 1_000_000:.1f}GB), parallel workers=4, "
            "no statement timeout"
        )

        sql = (
            f"CREATE INDEX CONCURRENTLY {INDEX} ON {TABLE} "
            f"USING ivfflat (embedding vector_cosine_ops) "
            f"WITH (lists = {lists}) "
            f"WHERE namespace = '{NAMESPACE}' AND source_type = '{SOURCE_TYPE}'"
        )
        log(f"executing: {sql}")
        started = time.time()
        cur.execute(sql)
        elapsed = time.time() - started
        log(f"build finished in {elapsed / 3600:.2f} hours")

    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_size_pretty(pg_relation_size(%s::regclass)), indisvalid "
            "FROM pg_index WHERE indexrelid = %s::regclass",
            (INDEX, INDEX),
        )
        size, valid = cur.fetchone()
        log(f"index size {size}, valid={valid}")
        if not valid:
            log(
                "WARNING: the index is INVALID. A concurrent build that fails "
                "leaves an unusable index behind. It must be dropped "
                "deliberately before retrying; this script will not do that."
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="preflight only")
    group.add_argument("--build", action="store_true", help="preflight, then build")
    group.add_argument("--watch", action="store_true", help="report a running build")
    args = parser.parse_args()

    if args.watch:
        with connect() as conn:
            watch(conn)
        return 0

    with connect() as conn, conn.cursor() as cur:
        cur.execute("SET statement_timeout = '120s'")
        rows = preflight(cur)

    if args.check:
        log(f"check only; would use lists = {lists_for(rows)}")
        return 0

    log("starting build; this takes hours and reads stay available")
    with connect() as conn:
        build(conn, rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())

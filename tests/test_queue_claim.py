"""dequeue_next: each pending item is claimed exactly once, even with many workers."""

import threading

from app.models import DatabaseManager, QueueModel


def _queue(tmp_path, n):
    db = DatabaseManager(str(tmp_path / "q.db"))
    db.bootstrap()
    conn = db.get_connection()
    conn.execute("PRAGMA foreign_keys = OFF")  # no experiment_runs row needed here
    for i in range(n):
        conn.execute(
            "INSERT INTO run_queue (run_id, operation_type, item_key, priority) VALUES (1, 'llm_call', ?, ?)",
            (f"k{i}", n - i),  # last inserted has the lowest priority value, so it goes first
        )
    conn.commit()
    conn.close()
    return QueueModel(db)


def test_claims_in_priority_order_then_empty(tmp_path):
    qm = _queue(tmp_path, 3)
    assert [qm.dequeue_next()["item_key"] for _ in range(3)] == ["k2", "k1", "k0"]
    assert qm.dequeue_next() is None


def test_concurrent_workers_never_share_an_item(tmp_path):
    n = 60
    qm = _queue(tmp_path, n)
    claimed, early_none, lock = [], [], threading.Lock()

    def pending():
        conn = qm.db.get_connection()
        try:
            return conn.execute("SELECT COUNT(*) FROM run_queue WHERE status='pending'").fetchone()[0]
        finally:
            conn.close()

    def worker():
        while (item := qm.dequeue_next()) is not None:
            with lock:
                claimed.append(item["id"])
        # None must mean "queue empty"; a lost race would make workers sleep with work waiting.
        # Nothing is added meanwhile and others only remove items, so a non-zero count here is a bug.
        if pending():
            early_none.append(1)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(claimed) == n and len(set(claimed)) == n
    assert not early_none


def test_retry_reset_handles_more_items_than_one_chunk(tmp_path):
    qm = _queue(tmp_path, 1200)
    conn = qm.db.get_connection()
    conn.execute("UPDATE run_queue SET status = 'error'")
    conn.commit()
    conn.close()
    assert qm.reset_items_for_retry(1) == 1200
    assert qm.get_run_progress(1)["pending"] == 1200

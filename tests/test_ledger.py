"""delivery ledger: persist-before-accept + retry ledger."""

from app import ledger


def test_begin_persists_before_processing():
    assert ledger.begin("d1", "push") is True
    row = ledger.recent(1)[0]
    assert row["delivery_id"] == "d1"
    assert row["event"] == "push"
    assert row["outcome"] == "received"
    assert row["attempts"] == 1
    assert row["received_at"]


def test_finish_records_outcome_and_metadata():
    ledger.begin("d1", "push")
    ledger.finish("d1", outcome="sent", repo="monologg/ghcord", feature="commits", duration_ms=12.5)
    row = ledger.recent(1)[0]
    assert row["outcome"] == "sent"
    assert row["repo"] == "monologg/ghcord"
    assert row["feature"] == "commits"
    assert row["duration_ms"] == 12.5
    assert row["completed_at"]


def test_successful_delivery_suppresses_redelivery():
    ledger.begin("d1", "push")
    ledger.finish("d1", outcome="sent")
    assert ledger.begin("d1", "push") is False


def test_ignored_and_unrouted_also_suppress():
    for delivery, outcome in [("d1", "ignored"), ("d2", "unrouted")]:
        ledger.begin(delivery, "push")
        ledger.finish(delivery, outcome=outcome)
        assert ledger.begin(delivery, "push") is False


def test_failed_delivery_allows_retry_and_counts_attempts():
    ledger.begin("d1", "push")
    ledger.finish("d1", outcome="failed", detail="HTTP 500")
    assert ledger.begin("d1", "push") is True
    row = ledger.recent(1)[0]
    assert row["attempts"] == 2
    assert row["outcome"] == "received"
    assert row["completed_at"] is None


def test_crashed_delivery_allows_retry():
    # crash mid-processing → outcome stays 'received' — GitHub redelivery must get through
    ledger.begin("d1", "push")
    assert ledger.begin("d1", "push") is True
    assert ledger.recent(1)[0]["attempts"] == 2


def test_recent_orders_newest_first_and_limits():
    for i in range(5):
        ledger.begin(f"d{i}", "push")
    rows = ledger.recent(3)
    assert [row["delivery_id"] for row in rows] == ["d4", "d3", "d2"]


def test_stats_success_rate_counts_only_attempted_sends():
    for delivery, outcome in [("d1", "sent"), ("d2", "sent"), ("d3", "failed"), ("d4", "ignored")]:
        ledger.begin(delivery, "push")
        ledger.finish(delivery, outcome=outcome)
    stats = ledger.stats()
    assert stats["totals"] == {"sent": 2, "failed": 1, "ignored": 1}
    assert stats["success_rate"] == 2 / 3


def test_stats_empty_ledger():
    stats = ledger.stats()
    assert stats["totals"] == {}
    assert stats["success_rate"] is None

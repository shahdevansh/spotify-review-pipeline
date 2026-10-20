"""Operational accounting tests use synthetic dispatches and never call APIs."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime

import pytest

import spotify_pipeline.engine as engine_module
from spotify_pipeline.engine import Engine, load_config
from spotify_pipeline.providers import ProviderError, ProviderResponse


class SyntheticProvider:
    endpoint = "synthetic://operational-tests"


@pytest.fixture
async def run(tmp_path):
    config = load_config()
    config.update(
        jev_transport="direct",
        ledger_path=str(tmp_path / "shared-spend.sqlite3"),
        requests_per_second=1_000_000,
        tokens_per_second=1_000_000_000,
        retry_backoff_seconds=0,
        transient_retries=1,
    )
    instance = Engine(
        config,
        tmp_path / "cache.sqlite3",
        tmp_path / "synthetic-run",
        providers={"jev": SyntheticProvider()},
    )
    try:
        yield instance
    finally:
        await instance.close()


def invoke(run, dispatch):
    return run._invoke(
        provider="jev",
        role="enrich",
        purpose="synthetic_operational_test",
        model="jev-1.13.0",
        review_ids=["synthetic-review-1"],
        request={"model": "jev-1.13.0", "state": "Synthetic review", "questions": {}},
        dispatch=dispatch,
    )


def prior_unknown_hold(run):
    """An old unresolved request must survive either cancellation path."""
    request_id = "synthetic-preexisting-unknown"
    run.ledger.reserve(
        request_id, "synthetic-prior-run", .125,
        global_cap_usd=18, run_cap_usd=1,
    )
    run.ledger.settle(request_id, None)
    return tuple(run.ledger.conn.execute(
        "SELECT * FROM spend WHERE request_id=?", (request_id,),
    ).fetchone())


def unchanged_prior_hold(run, previous):
    current = run.ledger.conn.execute(
        "SELECT * FROM spend WHERE request_id=?",
        ("synthetic-preexisting-unknown",),
    ).fetchone()
    assert tuple(current) == previous


@pytest.mark.asyncio
async def test_retry_after_sixty_seconds_is_honored_without_real_wait(run, monkeypatch):
    sleeps = []
    dispatched = 0

    async def record_sleep(delay):
        sleeps.append(delay)

    async def dispatch():
        nonlocal dispatched
        dispatched += 1
        if dispatched == 1:
            raise ProviderError(
                "Synthetic rate limit", status_code=429,
                transient=True, retry_after="60",
            )
        usage = {"input_tokens": 100, "output_tokens": 0}
        return ProviderResponse(
            {"synthetic": True},
            {"synthetic": True, "usage": usage},
            usage,
            "jev-1.13.0",
        )

    monkeypatch.setattr(engine_module, "reserve_request_slot", lambda *a, **kw: 0)
    monkeypatch.setattr(engine_module.asyncio, "sleep", record_sleep)
    data, _ = await invoke(run, dispatch)

    assert data == {"synthetic": True}
    assert dispatched == 2
    assert len(sleeps) == 1
    assert sleeps[0] >= 60
    assert [call["outcome"] for call in run.store.calls(run.run_id)] == [
        "failed", "succeeded",
    ]


def test_retry_after_supports_http_date_and_elapsed_date():
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
    future = datetime(2026, 10, 20, 12, 1, 30, tzinfo=timezone.utc)
    past = datetime(2026, 10, 20, 11, 59, tzinfo=timezone.utc)
    assert engine_module.retry_after_seconds(
        format_datetime(future, usegmt=True), now=now.timestamp(),
    ) == pytest.approx(90)
    assert engine_module.retry_after_seconds(
        format_datetime(past, usegmt=True), now=now.timestamp(),
    ) == 0
    assert engine_module.retry_after_seconds("60", now=now.timestamp()) == 60


@pytest.mark.asyncio
async def test_cancel_during_admission_releases_only_the_unsent_reservation(run, monkeypatch):
    previous = prior_unknown_hold(run)
    entered_sleep = asyncio.Event()
    dispatched = 0

    async def admission_sleep(delay):
        assert delay == 60
        entered_sleep.set()
        await asyncio.Event().wait()

    async def dispatch():
        nonlocal dispatched
        dispatched += 1
        raise AssertionError("A cancelled admission must never dispatch")

    monkeypatch.setattr(engine_module, "reserve_request_slot", lambda *a, **kw: 60)
    monkeypatch.setattr(engine_module.asyncio, "sleep", admission_sleep)
    task = asyncio.create_task(invoke(run, dispatch))
    try:
        await asyncio.wait_for(entered_sleep.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert dispatched == 0
    calls = run.store.calls(run.run_id)
    assert len(calls) == 1
    call = calls[0]
    assert call["outcome"] == "failed"
    assert call["dispatch_status"] == "not_dispatched"
    assert call["usage_source"] == "not_dispatched"
    assert call["cost_usd"] == 0
    assert call["billing_items"] == []
    assert call["unknown_charge_hold_usd"] == 0
    assert call["api_duration_seconds"] == 0
    assert run.ledger.totals(run.run_id)["committed_usd"] == 0
    assert run.ledger.totals()["unknown_charge_hold_usd"] == pytest.approx(.125)
    unchanged_prior_hold(run, previous)
    settled = run.ledger.conn.execute(
        "SELECT state, charged_nano FROM spend WHERE request_id=?",
        (call["request_id"],),
    ).fetchone()
    assert tuple(settled) == ("settled", 0)


@pytest.mark.asyncio
async def test_cancel_in_flight_keeps_new_and_preexisting_unknown_holds(run, monkeypatch):
    previous = prior_unknown_hold(run)
    entered_dispatch = asyncio.Event()
    dispatched = 0

    async def dispatch():
        nonlocal dispatched
        dispatched += 1
        entered_dispatch.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(engine_module, "reserve_request_slot", lambda *a, **kw: 0)
    task = asyncio.create_task(invoke(run, dispatch))
    try:
        await asyncio.wait_for(entered_dispatch.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert dispatched == 1
    calls = run.store.calls(run.run_id)
    assert len(calls) == 1
    call = calls[0]
    assert call["outcome"] == "failed"
    assert call["cost_usd"] is None
    assert call["usage_source"] == "unknown"
    assert call["billing_items"] == []
    assert call["unknown_charge_hold_usd"] == call["reserved_usd"] > 0
    assert run.ledger.totals(run.run_id)["unknown_charge_hold_usd"] == pytest.approx(
        call["reserved_usd"], abs=1e-9,
    )
    assert run.ledger.totals()["unknown_charge_hold_usd"] == pytest.approx(
        .125 + call["reserved_usd"], abs=1e-9,
    )
    assert run.ledger.totals()["reserved_usd"] == 0
    unchanged_prior_hold(run, previous)
    unsettled = run.ledger.conn.execute(
        "SELECT state, charged_nano FROM spend WHERE request_id=?",
        (call["request_id"],),
    ).fetchone()
    assert tuple(unsettled) == ("unknown", None)

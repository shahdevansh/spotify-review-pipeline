"""Failure-path tests use explicitly synthetic fixtures, never production records."""
import asyncio
import json
import pytest
from spotify_pipeline.engine import Engine, load_config
from spotify_pipeline.providers import ProviderResponse, TransientProviderError, JevProvider, OpenAIProvider, AuthenticationProviderError
from spotify_pipeline.storage import BudgetLedger, BudgetExceeded


def row(index, text=None):
    return dict(review_id=f"synthetic-{index}", review_text=text or f"Synthetic playback complaint {index}",
                review_rating="1", review_likes="0", app_version="", review_timestamp="2023-01-01")


class FakeJev:
    build_request = JevProvider.build_request
    model = "jev-1.13.0"
    def __init__(self, failures=None, confidence=.95, usage=True, latency=0):
        self.inputs, self.failures = [], list(failures or [])
        self.confidence, self.usage, self.latency = confidence, usage, latency
    async def classify(self, text, labels_prompt):
        self.inputs.append(text)
        if self.latency:
            await asyncio.sleep(self.latency)
        data = dict(topic="playback", intent="complaint", severity=4, sentiment=-.8,
                    confidence=dict(topic=self.confidence, intent=.95, severity=.95, sentiment=.95))
        if self.failures:
            event = self.failures.pop(0)
            if isinstance(event, Exception):
                raise event
            if event == "invalid":
                data["topic"] = "invented"
        usage = dict(input_tokens=100, output_tokens=0) if self.usage else None
        return ProviderResponse(data, dict(synthetic=True, answers=data), usage, self.model)


class FakeOpenAI:
    build_request = staticmethod(OpenAIProvider.build_request)
    def __init__(self, topic="playback"):
        self.requests, self.topic = [], topic
    async def structured(self, **kwargs):
        self.requests.append(kwargs)
        if "reviews" in kwargs["payload"]:
            result = {"reviews": [dict(review_id=r["review_id"], topic=self.topic, intent="complaint", severity=4,
                                       sentiment=-.8, entities=[], evidence_quote=r["review_text"], needs_review=False)
                                  for r in kwargs["payload"]["reviews"]]}
        else:
            result = {"answer": "Synthetic task result"}
        usage = dict(input_tokens=300, input_tokens_details=dict(cached_tokens=100, cache_write_tokens=0),
                     output_tokens=100, output_tokens_details=dict(reasoning_tokens=10))
        return ProviderResponse(result, dict(synthetic=True, output=result, usage=usage), usage, "gpt-6-luna")


@pytest.fixture
def config(tmp_path):
    value = load_config()
    value.update(ledger_path=str(tmp_path / "shared-spend.sqlite3"), requests_per_second=1_000_000, tokens_per_second=1_000_000_000, retry_backoff_seconds=0)
    return value


def engine(tmp_path, config, name="run", jev=None, openai=None, **kwargs):
    return Engine(config, tmp_path / "cache.sqlite3", tmp_path / name,
                  providers=dict(jev=jev or FakeJev(), openai=openai or FakeOpenAI()), **kwargs)


@pytest.mark.asyncio
async def test_duplicates_warm_cache_and_historic_evidence(tmp_path, config):
    rows = [row(1, "Synthetic identical text"), row(2, "Synthetic identical text"), row(3)]
    jev = FakeJev()
    cold = engine(tmp_path, config, "cold", jev=jev, workers=3)
    records = await cold.enrich(rows)
    assert len(jev.inputs) == 2 and len(records) == 3
    assert records[1]["cache_source_id"] == records[0]["review_id"]
    assert "cache_source_id" not in records[0]
    await cold.close()
    jev = FakeJev()
    warm = engine(tmp_path, config, "warm", jev=jev)
    assert await warm.enrich(rows) == records
    assert jev.inputs == [] and warm.summary()["requests"] == 0
    assert warm.summary()["cache_hits"] == 3
    assert len((warm.run_dir / "evidence_calls.jsonl").read_text().splitlines()) == 2
    await warm.close()


@pytest.mark.asyncio
async def test_cache_origin_outside_export_requires_new_call(tmp_path, config):
    first = engine(tmp_path, config, "first")
    await first.enrich([row(1, "Synthetic equal text")])
    await first.close()
    jev = FakeJev()
    second = engine(tmp_path, config, "second", jev=jev)
    records = await second.enrich([row(2, "Synthetic equal text")])
    assert len(jev.inputs) == 1 and "cache_source_id" not in records[0]
    await second.close()


@pytest.mark.asyncio
async def test_malformed_repaired_only_once_then_quarantined(tmp_path, config):
    jev = FakeJev(failures=["invalid", "invalid"])
    run = engine(tmp_path, config, jev=jev)
    records = await run.enrich([row(1)])
    assert len(jev.inputs) == 2 and records[0]["status"] == "quarantined"
    assert records[0]["attempt_count"] == 2
    assert [call["outcome"] for call in run.store.calls()] == ["failed", "failed"]
    assert run.summary()["api_cost_usd"] > 0
    await run.close()


@pytest.mark.asyncio
async def test_transient_retry_preserves_unknown_charge_hold(tmp_path, config):
    jev = FakeJev(failures=[TransientProviderError("synthetic network loss")])
    run = engine(tmp_path, config, jev=jev)
    assert (await run.enrich([row(1)]))[0]["status"] == "completed"
    assert len(jev.inputs) == 2 and run.summary()["spending"]["unknown_charge_hold_usd"] > 0
    first, second = run.store.calls()
    assert first["input_tokens"] is None and first["cost_usd"] is None
    assert second["input_tokens"] == 100
    await run.close()


@pytest.mark.asyncio
async def test_unknown_success_usage_does_not_invent_zero_charge(tmp_path, config):
    run = engine(tmp_path, config, jev=FakeJev(usage=False))
    await run.enrich([row(1)])
    assert not run.summary()["api_cost_complete"]
    assert run.summary()["spending"]["unknown_charge_hold_usd"] > 0
    assert run.store.calls()[0]["cost_usd"] is None
    await run.close()


def test_shared_ledger_limits_include_unknown_and_inflight_across_runs(tmp_path):
    a, b = BudgetLedger(tmp_path / "ledger.db"), BudgetLedger(tmp_path / "ledger.db")
    a.reserve("one", "cold", .6, global_cap_usd=1, run_cap_usd=1)
    with pytest.raises(BudgetExceeded):
        b.reserve("two", "warm", .5, global_cap_usd=1, run_cap_usd=1)
    a.settle("one", None)
    with pytest.raises(BudgetExceeded):
        b.reserve("three", "other", .5, global_cap_usd=1, run_cap_usd=1)
    b.reserve("four", "other", .4, global_cap_usd=1, run_cap_usd=1)
    b.settle("four", .1)
    assert a.totals()["committed_usd"] == pytest.approx(.7)
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_budget_stops_before_dispatch_leaving_explicit_pending(tmp_path, config):
    jev = FakeJev()
    run = engine(tmp_path, config, jev=jev, budget_usd=.00000001, workers=8)
    records = await run.enrich([row(index) for index in range(20)])
    assert jev.inputs == [] and {record["status"] for record in records} == {"pending"}
    assert run.summary()["api_cost_usd"] == 0
    await run.close()


@pytest.mark.asyncio
async def test_resume_does_not_relabel_completed_ids(tmp_path, config):
    rows = [row(index) for index in range(5)]
    run = engine(tmp_path, config, "recovery", workers=2)
    assert sum(record["status"] == "completed" for record in await run.enrich(rows, stop_after=2)) == 2
    await run.close()
    jev = FakeJev()
    resumed = engine(tmp_path, config, "recovery", jev=jev, workers=2)
    assert all(record["status"] == "completed" for record in await resumed.enrich(rows, phase="resume"))
    assert len(jev.inputs) == 3
    before = json.loads((resumed.run_dir / "checkpoint_before.json").read_text())
    after = json.loads((resumed.run_dir / "checkpoint_after.json").read_text())
    assert len(before["completed_ids"]) == 2 and len(after["completed_ids"]) == 5
    assert len([call for call in resumed.store.calls() if call["phase"] == "resume"]) == 3
    await resumed.close()


@pytest.mark.asyncio
async def test_fallback_five_percent_quota_and_consistent_alias(tmp_path, config):
    run = engine(tmp_path, config, jev=FakeJev(confidence=.2), openai=FakeOpenAI(topic="usability"), workers=4)
    rows = [row(index) for index in range(20)]
    rows.append(row("alias", rows[0]["review_text"]))
    records = await run.enrich(rows)
    fallback = [call for call in run.store.calls() if call["is_fallback"]]
    assert len(fallback) == 1 and len(fallback[0]["review_ids"]) == 1
    assert records[0]["topic"] == records[-1]["topic"] == "usability"
    assert records[-1]["cache_source_id"] == records[0]["review_id"]
    assert sum(record["needs_review"] for record in records) == 19
    await run.close()


@pytest.mark.asyncio
async def test_blind_verifier_detects_planted_error(tmp_path, config):
    openai = FakeOpenAI()
    run = engine(tmp_path, config, openai=openai)
    rows = [row(1), row(2)]
    records = await run.enrich(rows)
    records[0] = {**records[0], "topic": "billing"}  # synthetic test only
    results = await run.verify(rows, records, 2)
    payload = openai.requests[0]["payload"]
    assert all(set(r) == {"review_id", "review_text"} for r in payload["reviews"])
    assert "billing" not in json.dumps(payload)
    assert any("topic" in result["differences"] for result in results)
    assert openai.requests[0]["reasoning_effort"] == "none"
    await run.close()


@pytest.mark.asyncio
async def test_role_cache_across_run_directories_and_mutually_exclusive_billing(tmp_path, config):
    schema = dict(type="object", properties={"answer": dict(type="string")}, required=["answer"], additionalProperties=False)
    provider = FakeOpenAI()
    cold = engine(tmp_path, config, "cold", openai=provider)
    result = await cold.model_task("group", {"synthetic": True}, schema)
    assert len(provider.requests) == 1
    assert cold.store.calls()[0]["billing_items"] == [
        dict(category="input", units=200, rate_key="openai_input"),
        dict(category="cached_input", units=100, rate_key="openai_cached_input"),
        dict(category="output", units=100, rate_key="openai_output")]
    await cold.close()
    warm = engine(tmp_path, config, "warm", openai=provider)
    assert await warm.model_task("group", {"synthetic": True}, schema) == result
    assert len(provider.requests) == 1 and warm.summary()["requests"] == 0
    warm.finish()
    historic = [json.loads(line) for line in (warm.run_dir / "evidence_calls.jsonl").read_text().splitlines()]
    assert len(historic) == 1 and historic[0]["role"] == "group"
    await warm.close()


@pytest.mark.asyncio
async def test_prompt_change_invalidates_cache(tmp_path, config):
    first = engine(tmp_path, config, "first")
    await first.enrich([row(1)])
    await first.close()
    changed = {**config, "_prompts": {**config["_prompts"], "enrich": config["_prompts"]["enrich"] + "\nRevision."}}
    jev = FakeJev()
    second = engine(tmp_path, changed, "second", jev=jev)
    await second.enrich([row(1)])
    assert len(jev.inputs) == 1 and second.label_config != first.label_config
    await second.close()


@pytest.mark.asyncio
async def test_empty_text_without_calls(tmp_path, config):
    run = engine(tmp_path, config)
    empty = {**row(1), "review_text": " \n"}
    assert (await run.enrich([empty]))[0]["reason"] == "empty_review_text"
    assert run.store.calls() == []
    await run.close()


@pytest.mark.asyncio
async def test_missing_credentials_makes_no_attempt_or_spending_reservation(tmp_path, config, monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    run = Engine(config, tmp_path / "cache.sqlite3", tmp_path / "no-credentials")
    with pytest.raises(AuthenticationProviderError, match="TYPESAFE_API_KEY"):
        await run.enrich([row(1)])
    assert run.store.calls() == []
    assert run.ledger.totals()["committed_usd"] == 0
    assert run.records[0]["status"] == "pending"
    await run.close()


def test_unapproved_model_rejected_before_provider_setup(tmp_path, config):
    config["models"] = {**config["models"], "memo": "some-expensive-model"}
    with pytest.raises(ValueError, match="allowlist"):
        engine(tmp_path, config)


def test_weighted_token_pacing_shared_between_engines(tmp_path, monkeypatch):
    from spotify_pipeline.storage import reserve_request_slot
    monkeypatch.setattr("time.time", lambda: 1000)
    a, b = BudgetLedger(tmp_path / "ledger.db"), BudgetLedger(tmp_path / "ledger.db")
    assert reserve_request_slot(a, "jev", 10, 100, 200) == 0
    assert reserve_request_slot(b, "jev", 10, 100, 200) == .5
    assert reserve_request_slot(a, "jev", 10, 100, 200) == 1
    a.close()
    b.close()


@pytest.mark.asyncio
async def test_nonzero_cache_writes_are_unknown_charge_until_reconciled(tmp_path, config):
    run = engine(tmp_path, config)
    usage = dict(input_tokens=1000, input_tokens_details=dict(cached_tokens=100, cache_write_tokens=500), output_tokens=50)
    bill = run._billing("openai", usage)
    assert bill["cost_usd"] is None
    assert bill["billing_items"][0]["units"] == 400
    assert any("cache-write" in limitation for limitation in run.limitations)
    await run.close()

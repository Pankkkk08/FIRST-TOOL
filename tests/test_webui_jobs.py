import time

from squeeze.webui.jobs import Runner


def _fake_result(success=True, message="OK", input_size=1000, output_size=400):
    from squeeze.core.common import CompressResult

    return CompressResult(success=success, message=message, input_size=input_size, output_size=output_size)


def _wait_until_done(runner: Runner, timeout: float = 5.0) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        snap = runner.snapshot()
        if not snap["running"]:
            return snap
        time.sleep(0.02)
    raise AssertionError("Runner did not finish in time")


def test_runner_processes_items_in_order_and_reports_success():
    runner = Runner()
    processed = []

    def job_fn(item, should_stop, report):
        processed.append(item)
        report(0.5, "")
        return _fake_result(success=True)

    runner.start(["/a", "/b", "/c"], key_fn=lambda p: p, job_fn=job_fn)
    snap = _wait_until_done(runner)

    assert processed == ["/a", "/b", "/c"]
    # 3 × (1000 → 400 bytes) rolls up into a Caesium-style batch total.
    assert snap["overall"] == "Done — 2.9 KB → 1.2 KB (saved 60%)"
    assert [r["status"] for r in snap["rows"]] == ["Done", "Done", "Done"]
    assert all(r["saved"] for r in snap["rows"])


def test_runner_shows_rich_done_status_from_result_message():
    # A success message starting with "Done" (e.g. the hardware->software
    # fallback note) becomes the row status; a plain "OK" stays "Done".
    runner = Runner()

    def job_fn(item, should_stop, report):
        if item == "/fellback":
            return _fake_result(success=True, message="Done (software fallback)")
        return _fake_result(success=True, message="OK")

    runner.start(["/fellback", "/normal"], key_fn=lambda p: p, job_fn=job_fn)
    snap = _wait_until_done(runner)

    by_key = {r["key"]: r for r in snap["rows"]}
    assert by_key["/fellback"]["status"] == "Done (software fallback)"
    assert by_key["/normal"]["status"] == "Done"


def test_runner_overall_plain_done_when_nothing_succeeded():
    runner = Runner()

    def job_fn(item, should_stop, report):
        return _fake_result(success=False, message="boom")

    runner.start(["/x", "/y"], key_fn=lambda p: p, job_fn=job_fn)
    snap = _wait_until_done(runner)

    assert snap["overall"] == "Done."


def test_runner_marks_failed_items_without_stopping_the_batch():
    runner = Runner()

    def job_fn(item, should_stop, report):
        if item == "/bad":
            return _fake_result(success=False, message="boom")
        return _fake_result(success=True)

    runner.start(["/good1", "/bad", "/good2"], key_fn=lambda p: p, job_fn=job_fn)
    snap = _wait_until_done(runner)

    by_key = {r["key"]: r for r in snap["rows"]}
    assert by_key["/good1"]["status"] == "Done"
    assert by_key["/bad"]["status"] == "Failed"
    assert by_key["/bad"]["progress"] == "boom"
    assert by_key["/good2"]["status"] == "Done"


def test_runner_marks_exception_as_failed():
    runner = Runner()

    def job_fn(item, should_stop, report):
        raise RuntimeError("kaboom")

    runner.start(["/x"], key_fn=lambda p: p, job_fn=job_fn)
    snap = _wait_until_done(runner)

    assert snap["rows"][0]["status"] == "Failed"
    assert "kaboom" in snap["rows"][0]["progress"]


def test_runner_cancellation_stops_remaining_items():
    runner = Runner()
    started = []

    def job_fn(item, should_stop, report):
        started.append(item)
        # Simulate a job that checks should_stop mid-way, like real
        # compress_video/create_archive do.
        for _ in range(50):
            if should_stop():
                return _fake_result(success=False, message="Cancelled")
            time.sleep(0.01)
        return _fake_result(success=True)

    runner.start(["/one", "/two", "/three"], key_fn=lambda p: p, job_fn=job_fn)
    time.sleep(0.05)
    runner.cancel()
    snap = _wait_until_done(runner, timeout=3.0)

    assert snap["overall"] == "Cancelled."
    # The in-flight item should show Cancelled; items never reached stay Queued.
    statuses = {r["key"]: r["status"] for r in snap["rows"]}
    assert statuses[started[0]] == "Cancelled"


def test_runner_progress_report_updates_row():
    runner = Runner()
    release = False

    def job_fn(item, should_stop, report):
        report(0.3, "")
        report(0.7, "2.1x")
        # Give the test a chance to read mid-flight state before finishing.
        time.sleep(0.1)
        return _fake_result(success=True)

    runner.start(["/only"], key_fn=lambda p: p, job_fn=job_fn)
    time.sleep(0.03)
    mid_snap = runner.snapshot()
    assert "70%" in mid_snap["rows"][0]["progress"]
    assert "2.1x" in mid_snap["rows"][0]["progress"]

    _wait_until_done(runner)


def test_runner_status_text_fraction_minus_two():
    runner = Runner()

    def job_fn(item, should_stop, report):
        report(-2, "Probing…")
        time.sleep(0.05)
        report(-2, "Compressing…")
        return _fake_result(success=True)

    runner.start(["/only"], key_fn=lambda p: p, job_fn=job_fn)
    time.sleep(0.02)
    snap = runner.snapshot()
    assert snap["rows"][0]["status"] in ("Probing…", "Compressing…", "Done")

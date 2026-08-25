from app.worker.settings import WorkerSettings


def test_worker_registers_both_jobs():
    names = {f.__name__ for f in WorkerSettings.functions}
    assert "extract_skill_job" in names
    assert "run_experiment_job" in names


def test_job_timeout_exceeds_the_slowest_expected_model_call():
    # MEASURED against stealth/ox-alpha: a single structured extraction took
    # 7-8 minutes, not the ~48s the spec's latency probe suggested. An
    # 8-iteration analysis run is several multiples of that. A short timeout
    # would kill healthy runs.
    assert WorkerSettings.job_timeout >= 1800


def test_concurrency_is_bounded():
    assert 1 <= WorkerSettings.max_jobs <= 8


def test_results_are_retained_long_enough_to_be_read():
    assert WorkerSettings.keep_result >= 600

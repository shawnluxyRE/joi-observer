"""Separate actual debug slow callbacks from resource failure diagnostics."""

import asyncio
import json
import logging
import time

import pytest

from test_codec_backpressure_edges import _assert_asyncio_diagnostics


def test_real_debug_slow_callback_is_recorded_without_becoming_a_cleanup_failure(
        caplog, record_testsuite_property):
    async def scenario():
        loop = asyncio.get_running_loop()
        assert loop.get_debug() and loop.slow_callback_duration == 0.1
        finished = loop.create_future()

        def startup_work():
            time.sleep(0.11)
            finished.set_result(None)

        loop.call_soon(startup_work)
        await finished

    asyncio.run(scenario(), debug=True)
    records = [record for record in caplog.records
               if record.name == "asyncio" and record.levelno >= logging.WARNING]
    # The previous all-WARNING rejection would deterministically fail here,
    # despite no child, pipe, or cleanup work existing in this controlled loop.
    assert records and all(record.msg == "Executing %s took %.3f seconds" for record in records)
    properties = []

    def record_property(name, value):
        properties.append((name, value))
        record_testsuite_property(name, value)

    _assert_asyncio_diagnostics(caplog.records, record_property, "deterministic_startup")
    assert len(properties) == 1
    observed = json.loads(properties[0][1])
    assert len(observed) == len(records)
    assert all(item["seconds"] >= 0.1 and item["message"].startswith("Executing ")
               for item in observed)


@pytest.mark.parametrize("level,message,args", [
    (logging.WARNING, "Close running child process: kill %r", ("owned child",)),
    (logging.ERROR, "Task exception was never retrieved", ()),
    (logging.ERROR, "Task was destroyed but it is pending!", ()),
    (logging.WARNING, "Unclosed transport %r", ("owned transport",)),
    (logging.WARNING, "Executing %s took %.3f seconds", ("not a loop timing record", 0.11)),
])
def test_other_asyncio_warnings_and_errors_still_fail(caplog, level, message, args):
    logging.getLogger("asyncio").log(level, message, *args)
    recorded = []
    with pytest.raises(AssertionError) as caught:
        _assert_asyncio_diagnostics(caplog.records,
                                   lambda name, value: recorded.append((name, value)), "failure")
    assert caplog.records[-1].getMessage() in str(caught.value)
    assert recorded and json.loads(recorded[0][1]) == []


def test_actual_unretrieved_task_error_is_not_hidden_by_a_real_slow_callback(caplog):
    """Exercise both CPython logger paths, rather than only fabricated records."""
    import gc
    import weakref

    async def scenario():
        loop = asyncio.get_running_loop()
        assert loop.get_debug() and loop.slow_callback_duration == 0.1
        baseline = asyncio.all_tasks()

        async def failed_child():
            raise RuntimeError("controlled unobserved task failure")

        child = asyncio.create_task(failed_child(), name="diagnostic-probe")
        await asyncio.sleep(0)
        assert child.done()
        observed = weakref.ref(child)
        del child
        gc.collect()
        assert observed() is None

        finished = loop.create_future()

        def startup_work():
            time.sleep(0.11)
            finished.set_result(None)

        loop.call_soon(startup_work)
        await finished
        assert asyncio.all_tasks() == baseline

    asyncio.run(scenario(), debug=True)
    actual_errors = [record for record in caplog.records
                     if record.name == "asyncio" and record.levelno >= logging.ERROR]
    assert len(actual_errors) == 1
    assert actual_errors[0].funcName == "default_exception_handler"
    assert "Task exception was never retrieved" in actual_errors[0].getMessage()
    actual_slow = [record for record in caplog.records
                   if record.name == "asyncio" and record.levelno == logging.WARNING]
    assert actual_slow and all(record.funcName == "_run_once" for record in actual_slow)
    properties = []
    with pytest.raises(AssertionError, match="Task exception was never retrieved"):
        _assert_asyncio_diagnostics(caplog.records,
                                   lambda name, value: properties.append((name, value)), "actual_mixed")
    assert len(properties) == 1
    assert json.loads(properties[0][1]) == [
        {"message": record.getMessage(), "seconds": record.args[1]} for record in actual_slow]

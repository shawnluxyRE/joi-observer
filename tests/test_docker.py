"""REQ-003 黑盒契约：真实解析/采集入口，替身仅提供离线命令响应。

样本是按接口契约构造的最小 JSON，不是任何服务器的实采证据。所有未实现
断言仍期待正确业务行为；不将 NotImplementedError、xfail 或跳过作为成功。
"""

import asyncio
from dataclasses import FrozenInstanceError
import json

import pytest

from joi_observer.collectors.docker import (
    CommandOutput, DOCKER_INSPECT_TEMPLATE, DockerCollector, DockerOutputLimitError,
    LOCAL_DOCKER_HOST, MAX_OUTPUT_BYTES, build_docker_collectors, parse_inspect,
)
from joi_observer.config import ContainerConfig
from joi_observer.data.models import Metric, ObjectKey, ObjectSpec
from joi_observer.error_log import ErrorKind


pytestmark = pytest.mark.usefixtures("no_live_docker_io")


CONFIG = ContainerConfig("chat-service", "chat-container")
CONTAINER_ID = "a1" * 32
NEW_CONTAINER_ID = "b2" * 32


def document(*, name="/chat-container", identity=CONTAINER_ID, status="running"):
    return {"Id": identity, "Name": name, "State": {"Status": status}}


def response(data=None, *, stderr=b""):
    data = document() if data is None else data
    return CommandOutput(0, json.dumps(data).encode("utf-8"), stderr)


def assert_failure(result, kind, code, *, object_id=CONFIG.id):
    assert result.key == ObjectKey("docker", object_id)
    assert result.metrics == ()
    assert result.failure is not None
    assert (result.failure.kind, result.failure.code) == (kind, code)
    assert result.failure.reason and "PRIVATE" not in result.failure.reason


class OfflineCommand:
    """仅模拟 OS 命令结果与等待，不模拟 Collector/解析器的业务返回值。"""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.close_calls = 0

    async def run(self, argv, *, timeout):
        self.calls.append((argv, timeout))
        await asyncio.sleep(0)
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output

    async def close(self):
        self.close_calls += 1


@pytest.mark.parametrize("raw,expected", [
    ("created", "Created"), ("running", "Running"), ("paused", "Paused"),
    ("restarting", "Restarting"), ("removing", "Removing"), ("exited", "Exited"),
    ("dead", "Dead"),
])
def test_all_lifecycle_states_are_success_including_stopped_and_dead(raw, expected):
    result = parse_inspect(CONFIG, response(document(status=raw)))
    assert result.key == ObjectKey("docker", CONFIG.id)
    assert result.metrics == (Metric("state", expected),)
    assert result.failure is None


def test_response_and_result_are_immutable_values():
    output = response()
    with pytest.raises(FrozenInstanceError):
        output.returncode = 7


def test_health_error_and_other_fields_are_ignored_and_never_exposed(capsys):
    data = document()
    data["State"].update(Health={"Status": "unhealthy", "Log": ["PRIVATE"]},
                         Error="PRIVATE error", ExitCode=137)
    data["Config"] = {"Env": ["PRIVATE_TOKEN=secret"]}
    result = parse_inspect(CONFIG, response(data, stderr=b"PRIVATE warning"))
    assert result.metrics == (Metric("state", "Running"),)
    assert result.failure is None
    assert "PRIVATE" not in repr(result)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("target", ["chat-container", CONTAINER_ID])
def test_exact_name_or_complete_id_identifies_the_configured_object(target):
    result = parse_inspect(ContainerConfig("stable-id", target), response())
    assert result.key == ObjectKey("docker", "stable-id")
    assert result.metrics == (Metric("state", "Running"),)
    assert result.failure is None


@pytest.mark.parametrize("target", [CONTAINER_ID[:12], "chat", "container", "Chat-container",
                                    "/chat-container", "compose-project", NEW_CONTAINER_ID])
def test_prefix_substring_compose_or_unrelated_identity_does_not_bind(target):
    result = parse_inspect(ContainerConfig(CONFIG.id, target), response())
    assert_failure(result, ErrorKind.NOT_FOUND, "object.not_found")


def test_name_target_follows_same_name_recreation_but_id_target_does_not():
    recreated = response(document(identity=NEW_CONTAINER_ID, status="restarting"))
    by_name = parse_inspect(CONFIG, recreated)
    by_id = parse_inspect(ContainerConfig(CONFIG.id, CONTAINER_ID), recreated)
    assert by_name.metrics == (Metric("state", "Restarting"),)
    assert by_name.failure is None
    assert_failure(by_id, ErrorKind.NOT_FOUND, "object.not_found")


def test_full_id_target_cannot_bind_a_different_container_with_that_id_as_its_name():
    config = ContainerConfig(CONFIG.id, CONTAINER_ID)
    conflicting = response(document(identity=NEW_CONTAINER_ID, name="/" + CONTAINER_ID))
    assert_failure(parse_inspect(config, conflicting), ErrorKind.NOT_FOUND, "object.not_found")


def test_short_hex_target_can_match_an_exact_real_name_instead_of_only_an_id_prefix():
    target = CONTAINER_ID[:12]
    config = ContainerConfig(CONFIG.id, target)
    result = parse_inspect(config, response(document(identity=NEW_CONTAINER_ID, name="/" + target)))
    assert result.metrics == (Metric("state", "Running"),)
    assert result.failure is None


@pytest.mark.parametrize("raw", [
    b"", b"PRIVATE not json", b"\xff", b"[]", b"null", b"true", b"{} {}",
    b'{"Id":"PRIVATE","Id":"PRIVATE"}',
    json.dumps([document()]).encode(),
    (json.dumps(document()) + "\n" + json.dumps(document())).encode(),
    json.dumps({"Id": CONTAINER_ID, "Name": "/chat-container",
                "State": {"Status": "running"}}).replace(
                    '"Status": "running"', '"Status":"running","Status":"exited"').encode(),
])
def test_malformed_document_is_a_controlled_parse_failure(raw, capsys):
    result = parse_inspect(CONFIG, CommandOutput(0, raw))
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert "PRIVATE" not in repr(result)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_constants_are_rejected_even_in_ignored_fields(constant):
    raw = json.dumps(document())[:-1] + ', "Ignored": ' + constant + "}"
    assert_failure(parse_inspect(CONFIG, CommandOutput(0, raw.encode())),
                   ErrorKind.PARSE, "response.invalid")


def test_duplicate_keys_are_rejected_inside_ignored_nested_fields():
    raw = json.dumps(document())[:-1] + ', "Ignored": {"nested": {"key": 1, "key": 2}}}'
    assert_failure(parse_inspect(CONFIG, CommandOutput(0, raw.encode())),
                   ErrorKind.PARSE, "response.invalid")


def test_deeply_nested_malformed_response_is_a_controlled_parse_failure():
    # Unclosed arrays are invalid regardless of the decoder's recursion limit.
    raw = json.dumps(document())[:-1] + ', "Ignored": ' + "[" * 10000 + "0}"
    assert_failure(parse_inspect(CONFIG, CommandOutput(0, raw.encode())),
                   ErrorKind.PARSE, "response.invalid")


@pytest.mark.parametrize("character", ["\x00", "\t", "\x7f", "\u200b", "\u00a0"])
def test_nonprinting_or_whitespace_name_characters_fail_before_identity_matching(character):
    data = document(name="/chat" + character + "container")
    assert_failure(parse_inspect(CONFIG, response(data)), ErrorKind.PARSE, "response.invalid")


def test_valid_printable_unicode_name_is_matched_exactly():
    target = "容器-chat"
    result = parse_inspect(ContainerConfig(CONFIG.id, target), response(document(name="/" + target)))
    assert result.metrics == (Metric("state", "Running"),)
    assert result.failure is None


def test_invalid_state_takes_precedence_over_an_unmatched_identity():
    data = document(name="/different-container", status="PRIVATE")
    assert_failure(parse_inspect(CONFIG, response(data)), ErrorKind.PARSE, "response.invalid")


@pytest.mark.parametrize("field,value", [
    ("Id", None), ("Id", 42), ("Id", "short"), ("Id", "A" * 64),
    ("Name", None), ("Name", "chat-container"), ("Name", "/"),
    ("Name", "//chat-container"), ("Name", "/chat/container"),
    ("Name", "/chat container"), ("Name", "/chat\ncontainer"),
    ("State", None), ("State", []), ("State", {}),
    ("State", {"Status": None}), ("State", {"Status": 0}),
    ("State", {"Status": "Running"}), ("State", {"Status": "unhealthy"}),
    ("State", {"Status": "future-state"}),
])
def test_invalid_or_unknown_inspect_fields_fail_without_fabricated_state(field, value):
    data = document()
    data[field] = value
    assert_failure(parse_inspect(CONFIG, response(data)), ErrorKind.PARSE, "response.invalid")


@pytest.mark.parametrize("missing", ["Id", "Name", "State"])
def test_required_fields_cannot_be_omitted(missing):
    data = document()
    del data[missing]
    assert_failure(parse_inspect(CONFIG, response(data)), ErrorKind.PARSE, "response.invalid")


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_each_stream_has_an_independent_limit_before_exit_classification(stream):
    values = {"stdout": b"", "stderr": b"No such container: PRIVATE"}
    values[stream] = b"x" * (MAX_OUTPUT_BYTES + 1)
    assert_failure(parse_inspect(CONFIG, CommandOutput(1, **values)),
                   ErrorKind.PARSE, "response.invalid")


def test_exact_output_limit_and_surrounding_json_whitespace_are_accepted():
    raw = response().stdout
    padded = b"\n" + raw + b" " * (MAX_OUTPUT_BYTES - len(raw) - 1)
    result = parse_inspect(CONFIG, CommandOutput(0, padded, b"x" * MAX_OUTPUT_BYTES))
    assert result.metrics == (Metric("state", "Running"),)
    assert result.failure is None


@pytest.mark.parametrize("stderr,kind,code", [
    (b"permission denied while connecting: PRIVATE", ErrorKind.PERMISSION, "access.denied"),
    (b"PERMISSION DENIED; No such object: PRIVATE", ErrorKind.PERMISSION, "access.denied"),
    (b"Error: No such container: PRIVATE", ErrorKind.NOT_FOUND, "object.not_found"),
    (b"Error response from daemon: NO SUCH OBJECT: PRIVATE", ErrorKind.NOT_FOUND, "object.not_found"),
    (b"Cannot connect to Docker daemon: PRIVATE", ErrorKind.UNAVAILABLE, "source.unavailable"),
    (b"PRIVATE unknown command failure", ErrorKind.UNAVAILABLE, "source.unavailable"),
    (b"", ErrorKind.UNAVAILABLE, "source.unavailable"),
    (b"\xffPRIVATE", ErrorKind.UNAVAILABLE, "source.unavailable"),
])
def test_nonzero_exit_uses_controlled_error_categories_without_parsing_stdout(stderr, kind, code):
    result = parse_inspect(CONFIG, CommandOutput(1, b"PRIVATE invalid JSON", stderr))
    assert_failure(result, kind, code)
    assert "PRIVATE" not in repr(result)


def test_constructor_exposes_unknown_state_without_any_command_io():
    command = OfflineCommand()
    collector = DockerCollector(CONFIG, command=command, timeout=2.5)
    assert collector.spec == ObjectSpec(ObjectKey("docker", CONFIG.id), (Metric("state", None),))
    assert command.calls == [] and command.close_calls == 0


def test_collector_executes_one_local_read_with_target_as_single_argument(capsys):
    async def scenario():
        # This broad config value must remain one argv entry, never shell syntax.
        target = "--host=tcp://PRIVATE;$(PRIVATE)"
        config = ContainerConfig("target", target)
        command = OfflineCommand(response(document(name="/different")))
        collector = DockerCollector(config, command=command, timeout=2.5)
        result = await collector.collect()
        assert command.calls == [((
            "docker", "--host", "unix:///var/run/docker.sock", "container", "inspect",
            "--format", '{"Id":{{json .Id}},"Name":{{json .Name}},"State":{"Status":{{json .State.Status}}}}',
            "--", target), 2.5)]
        assert_failure(result, ErrorKind.NOT_FOUND, "object.not_found", object_id="target")
        assert LOCAL_DOCKER_HOST == "unix:///var/run/docker.sock"
        assert DOCKER_INSPECT_TEMPLATE == command.calls[0][0][6]
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error,kind,code", [
    (FileNotFoundError("PRIVATE missing CLI"), ErrorKind.UNAVAILABLE, "source.unavailable"),
    (PermissionError("PRIVATE denied"), ErrorKind.PERMISSION, "access.denied"),
    (OSError("PRIVATE OS fault"), ErrorKind.UNAVAILABLE, "source.unavailable"),
    (TimeoutError("PRIVATE timeout"), ErrorKind.TIMEOUT, "collection.timeout"),
    (DockerOutputLimitError(), ErrorKind.PARSE, "response.invalid"),
])
def test_expected_io_failures_are_controlled_and_do_not_print(error, kind, code, capsys):
    async def scenario():
        command = OfflineCommand(error)
        result = await DockerCollector(CONFIG, command=command).collect()
        assert_failure(result, kind, code)
        assert len(command.calls) == 1
        assert "PRIVATE" not in repr(result)
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_unknown_exception_is_left_for_monitor_instead_of_misclassified():
    async def scenario():
        command = OfflineCommand(RuntimeError("PRIVATE programming defect"))
        with pytest.raises(RuntimeError, match="PRIVATE programming defect"):
            await DockerCollector(CONFIG, command=command).collect()
    asyncio.run(scenario())


def test_cancellation_is_not_converted_to_failure():
    async def scenario():
        command = OfflineCommand(asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            await DockerCollector(CONFIG, command=command).collect()
        assert len(command.calls) == 1
    asyncio.run(scenario())


def test_each_sample_requeries_and_can_recover_after_error_then_recreation():
    async def scenario():
        command = OfflineCommand(
            response(document(status="exited")),
            CommandOutput(1, stderr=b"No such container: PRIVATE"),
            response(document(identity=NEW_CONTAINER_ID, status="restarting")),
            response(document(identity=NEW_CONTAINER_ID, status="running")),
        )
        collector = DockerCollector(CONFIG, command=command)
        results = [await collector.collect() for _ in range(4)]
        assert results[0].metrics == (Metric("state", "Exited"),)
        assert_failure(results[1], ErrorKind.NOT_FOUND, "object.not_found")
        assert results[2].metrics == (Metric("state", "Restarting"),)
        assert results[3].metrics == (Metric("state", "Running"),)
        assert len(command.calls) == 4
        assert len({args for args, _ in command.calls}) == 1
        assert all(result.key == collector.spec.key for result in results)
    asyncio.run(scenario())


def test_close_is_idempotent_and_does_not_close_another_collectors_port():
    async def scenario():
        first, second = OfflineCommand(), OfflineCommand(response())
        one = DockerCollector(CONFIG, command=first)
        two = DockerCollector(CONFIG, command=second)
        await one.close()
        await one.close()
        assert first.close_calls == 1 and second.close_calls == 0
        result = await two.collect()
        assert result.metrics == (Metric("state", "Running"),)
        with pytest.raises(RuntimeError):
            await one.collect()
        assert first.calls == []
        await two.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("count", [0, 1, 5, 6, 10, 31])
def test_factory_keeps_all_targets_and_order_with_distinct_ports_without_io(count):
    configs = tuple(ContainerConfig(f"docker-{index}", f"container-{index}") for index in range(count))
    commands = []

    def factory():
        command = OfflineCommand()
        commands.append(command)
        return command

    collectors = build_docker_collectors(configs, timeout=2.5, command_factory=factory)
    assert isinstance(collectors, tuple)
    assert len(collectors) == len(commands) == count
    assert [collector.spec.key for collector in collectors] == [ObjectKey("docker", item.id) for item in configs]
    assert [collector.config for collector in collectors] == list(configs)
    assert all(command.calls == [] and command.close_calls == 0 for command in commands)
    assert all(collector.timeout == 2.5 for collector in collectors)


def test_factory_does_not_merge_same_target_with_different_config_ids():
    async def scenario():
        configs = (ContainerConfig("first", CONFIG.name), ContainerConfig("second", CONFIG.name))
        commands = []

        def factory():
            command = OfflineCommand(response())
            commands.append(command)
            return command

        collectors = build_docker_collectors(configs, timeout=3, command_factory=factory)
        results = [await collector.collect() for collector in collectors]
        assert [result.key.object_id for result in results] == ["first", "second"]
        assert len(commands) == 2 and commands[0] is not commands[1]
        assert all(len(command.calls) == 1 for command in commands)
        assert all(result.metrics == (Metric("state", "Running"),) for result in results)
    asyncio.run(scenario())


def test_full_id_collector_follows_rename_without_rebinding_to_a_recreated_container():
    async def scenario():
        config = ContainerConfig("stable-id", CONTAINER_ID)
        command = OfflineCommand(
            response(document(status="exited")),
            response(document(name="/renamed-container", status="running")),
            response(document(identity=NEW_CONTAINER_ID, status="running")),
        )
        collector = DockerCollector(config, command=command)

        original, renamed, recreated = [await collector.collect() for _ in range(3)]

        assert original.metrics == (Metric("state", "Exited"),)
        assert renamed.metrics == (Metric("state", "Running"),)
        assert original.failure is renamed.failure is None
        assert_failure(recreated, ErrorKind.NOT_FOUND, "object.not_found", object_id=config.id)
        assert all(result.key == collector.spec.key for result in (original, renamed, recreated))
        assert [argv[-1] for argv, _ in command.calls] == [CONTAINER_ID] * 3
        await collector.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("error", [
    FileNotFoundError("PRIVATE missing CLI"),
    PermissionError("PRIVATE denied"),
    OSError("PRIVATE transient IO fault"),
    TimeoutError("PRIVATE timeout"),
    DockerOutputLimitError(),
])
def test_expected_io_failure_does_not_disable_later_collection(error):
    async def scenario():
        command = OfflineCommand(error, response(document(status="paused")))
        collector = DockerCollector(CONFIG, command=command)

        failed = await collector.collect()
        recovered = await collector.collect()

        assert failed.failure is not None and failed.metrics == ()
        assert recovered.failure is None
        assert recovered.metrics == (Metric("state", "Paused"),)
        assert failed.key == recovered.key == collector.spec.key
        assert len(command.calls) == 2 and command.calls[0] == command.calls[1]
        assert command.close_calls == 0
        await collector.close()
    asyncio.run(scenario())

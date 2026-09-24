"""Offline contract tests for the Codex CLI transport and LangGraph bridge."""

import json
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel

from tradingagents.llm_clients.codex_client import CodexChatModel
from tradingagents.llm_clients.factory import create_llm_client
from tradingagents.llm_clients.validators import validate_model


@tool
def stock_price(symbol: str) -> str:
    """Return an offline stock quote."""
    return f"{symbol}: 100 KRW"


class Decision(BaseModel):
    action: str
    confidence: float


@pytest.fixture
def cli(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.llm_clients.codex_client.shutil.which", lambda _: "codex.exe"
    )
    run = Mock()
    monkeypatch.setattr("tradingagents.llm_clients.codex_client.subprocess.run", run)

    def respond(text, returncode=0):
        def execute(command, **kwargs):
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text(text, encoding="utf-8")
            return subprocess.CompletedProcess(
                command, returncode, "debug must not be returned", "secret-token"
            )

        run.side_effect = execute

    run.respond = respond
    return run


def test_plain_invoke_uses_stdin_sandbox_and_isolated_cwd(cli):
    cli.respond("한국 분석")
    llm = create_llm_client("codex", "gpt-6-astra", timeout=42, reasoning_effort="low").get_llm()
    response = llm.invoke([("system", "한국어 사용"), ("user", "분석 ` $() secret")])
    assert response.content == "한국 분석"
    (command,) = cli.call_args.args
    options = cli.call_args.kwargs
    assert command[-1] == "-"
    assert "secret" not in " ".join(command)
    assert "분석 ` $() secret" in options["input"]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--ephemeral" in command
    assert not any("bypass" in arg for arg in command)
    assert options["shell"] is False
    assert options["timeout"] == 42
    assert not Path(options["cwd"]).exists()
    assert validate_model("codex", "custom-model")


def test_tools_execute_in_langgraph_and_preserve_results(cli):
    cli.respond(
        json.dumps(
            {
                "content": "",
                "tool_calls": [{"name": "stock_price", "arguments": '{"symbol":"005930"}'}],
            }
        )
    )
    llm = CodexChatModel(model="test")
    bound = llm.bind_tools([stock_price])
    request = bound.invoke("삼성전자 가격")
    assert request.tool_calls[0]["args"] == {"symbol": "005930"}
    graph = StateGraph(MessagesState)
    graph.add_node("tools", ToolNode([stock_price]))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    result = graph.compile().invoke({"messages": [request]})["messages"][-1]
    assert result.content == "005930: 100 KRW"
    cli.respond('{"content":"삼성전자 100원", "tool_calls":[]}')
    final = bound.invoke([HumanMessage(content="가격"), request, result])
    assert final.content == "삼성전자 100원"
    assert final.tool_calls == []
    prompt = cli.call_args.kwargs["input"]
    assert result.tool_call_id in prompt
    assert "005930: 100 KRW" in prompt
    assert '"role": "tool"' in prompt


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"content": "ok"}',
        '{"content": "", "tool_calls":[{"name":"unknown","arguments":"{}"}]}',
        '{"content": "", "tool_calls":[{"name":"stock_price","arguments":"[]"}]}',
        '{"content": "", "tool_calls":[{"name":"stock_price","arguments":"secret-token"}]}',
    ],
)
def test_malformed_tool_response_is_sanitized(cli, text):
    cli.respond(text)
    with pytest.raises(ValueError, match="invalid application tool output") as caught:
        CodexChatModel(model="test").bind_tools([stock_price]).invoke("test")
    assert "secret-token" not in str(caught.value)


def test_tool_choice_is_enforced(cli):
    cli.respond('{"content":"done", "tool_calls":[]}')
    with pytest.raises(ValueError, match="invalid application tool output"):
        CodexChatModel(model="test").bind_tools([stock_price], tool_choice="required").invoke(
            "test"
        )


def test_structured_output_schema_and_pydantic_result(cli):
    captured = {}
    cli.respond('{"action":"HOLD","confidence":0.8}')
    execute = cli.side_effect

    def inspect(command, **kwargs):
        captured.update(json.loads(Path(command[command.index("--output-schema") + 1]).read_text()))
        return execute(command, **kwargs)

    cli.side_effect = inspect
    result = CodexChatModel(model="test").with_structured_output(Decision).invoke("분석")
    assert result == Decision(action="HOLD", confidence=0.8)
    assert captured["additionalProperties"] is False
    assert set(captured["required"]) == {"action", "confidence"}


def test_structured_include_raw_and_validation_error(cli):
    cli.respond('{"action":"HOLD","confidence":"secret-token"}')
    llm = CodexChatModel(model="test")
    result = llm.with_structured_output(Decision, include_raw=True).invoke("test")
    assert isinstance(result["raw"], AIMessage)
    assert result["parsed"] is None
    assert isinstance(result["parsing_error"], ValueError)
    assert "secret-token" not in str(result["parsing_error"])
    with pytest.raises(ValueError, match="invalid structured output"):
        llm.with_structured_output(Decision).invoke("test")


def test_timeout_error_and_cleanup(cli):
    cli.side_effect = subprocess.TimeoutExpired("command secret-token", 1, output="secret-token")
    with pytest.raises(TimeoutError, match="timed out after 1 seconds") as caught:
        CodexChatModel(model="test", timeout=1).invoke("test")
    assert "secret-token" not in str(caught.value)
    assert not Path(cli.call_args.kwargs["cwd"]).exists()


def test_subprocess_error_and_empty_output_are_sanitized(cli):
    cli.respond("secret-token", returncode=1)
    with pytest.raises(RuntimeError, match="failed \\(exit 1\\)") as caught:
        CodexChatModel(model="test").invoke("test")
    assert "secret-token" not in str(caught.value)
    cli.respond("")
    with pytest.raises(RuntimeError, match="no final response"):
        CodexChatModel(model="test").invoke("test")


def test_invoke_calls_standard_langchain_callbacks(cli):
    class Recorder(BaseCallbackHandler):
        starts = 0
        ends = 0

        def on_chat_model_start(self, *args, **kwargs):
            self.starts += 1

        def on_llm_end(self, *args, **kwargs):
            self.ends += 1

    cli.respond("ok")
    callback = Recorder()
    CodexChatModel(model="test").invoke("test", config={"callbacks": [callback]})
    assert (callback.starts, callback.ends) == (1, 1)


def test_structured_json_schema_without_title(cli):
    cli.respond('{"action":"HOLD"}')
    schema = {
        "type": "object",
        "properties": {"action": {"type": "string"}},
        "required": ["action"],
    }
    result = CodexChatModel(model="test").with_structured_output(schema).invoke("test")
    assert result == {"action": "HOLD"}
    assert "title" not in schema


def test_windows_npm_shim_resolves_native_executable(cli, monkeypatch, tmp_path):
    shim = tmp_path / "codex.cmd"
    native = (
        tmp_path
        / "node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe"
    )
    native.parent.mkdir(parents=True)
    native.touch()
    monkeypatch.setattr("tradingagents.llm_clients.codex_client.shutil.which", lambda _: str(shim))
    monkeypatch.setattr("tradingagents.llm_clients.codex_client.platform.machine", lambda: "AMD64")
    cli.respond("ok")
    CodexChatModel(model="test").invoke("test")
    assert cli.call_args.args[0][0] == str(native)
    assert cli.call_args.kwargs["shell"] is False


def test_missing_codex_executable(cli, monkeypatch):
    monkeypatch.setattr("tradingagents.llm_clients.codex_client.shutil.which", lambda _: None)
    with pytest.raises(FileNotFoundError, match="not installed"):
        CodexChatModel(model="test").invoke("test")
    cli.assert_not_called()


def test_graph_config_kwarg_names(cli):
    llm = create_llm_client(
        "codex", "test", codex_command="custom-codex", codex_timeout=123
    ).get_llm()
    assert llm.cli_command == "custom-codex"
    assert llm.timeout == 123

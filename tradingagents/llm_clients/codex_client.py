"""Codex CLI adapter with LangChain tool and structured-output support.

The stdin / final-message-file transport is adapted from TradingAgents-KR's
cli_client.py at ce0aa456419800c29325516f984fc55a9a8f14dd. Application tools
are requested as JSON and executed by LangGraph, never by the CLI adapter.
"""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import RunnableLambda
from langchain_core.utils.function_calling import convert_to_openai_function, convert_to_openai_tool
from pydantic import BaseModel, Field

from .base_client import BaseLLMClient


def _prompt(messages: list[BaseMessage]) -> str:
    """Preserve tool results and call IDs across the application's agent loop."""
    transcript = []
    for message in messages:
        item = {"role": message.type, "content": message.content}
        if isinstance(message, AIMessage) and message.tool_calls:
            item["tool_calls"] = message.tool_calls
        if isinstance(message, ToolMessage):
            item["tool_call_id"] = message.tool_call_id
            item["name"] = message.name
        transcript.append(item)
    return (
        "You are the language model for a financial research application. Respond to the "
        "conversation below. Use only its supplied evidence and application tool results. "
        "Do not inspect local files, run commands, or use your own tools or web search. "
        "Application tool requests are returned as JSON for the host to execute.\n"
        + json.dumps(transcript, ensure_ascii=False)
    )


def _tool_response_schema(names: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "content": {"type": "string"},
            "tool_calls": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "enum": names},
                        "arguments": {"type": "string"},
                    },
                    "required": ["name", "arguments"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["content", "tool_calls"],
        "additionalProperties": False,
    }


class CodexChatModel(BaseChatModel):
    """One isolated ``codex exec`` per request; standard LangChain callbacks apply."""

    model: str
    cli_command: str = "codex"
    timeout: float = Field(default=300, gt=0)
    reasoning_effort: str | None = None

    @property
    def _llm_type(self) -> str:
        return "codex-cli"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "reasoning_effort": self.reasoning_effort}

    def bind_tools(self, tools: Sequence[Any], *, tool_choice=None, **kwargs):
        converted = [convert_to_openai_tool(tool) for tool in tools]
        names = [tool["function"]["name"] for tool in converted]
        if isinstance(tool_choice, dict):
            tool_choice = tool_choice.get("function", {}).get("name")
        if tool_choice is True or tool_choice == "any":
            tool_choice = "required"
        if tool_choice is False or tool_choice is None:
            tool_choice = "auto"
        if tool_choice not in ["auto", "none", "required", *names]:
            raise ValueError("Unsupported Codex tool_choice")
        if tool_choice == "required" and not names:
            raise ValueError("Required tool choice needs at least one tool")
        return self.bind(tools=converted, tool_choice=tool_choice, **kwargs)

    def with_structured_output(self, schema, *, include_raw=False, **kwargs):
        method = kwargs.pop("method", "json_schema")
        kwargs.pop("strict", None)
        if kwargs or method not in ("json_schema", "function_calling", "json_mode"):
            raise ValueError("Unsupported Codex structured-output options")
        schema_input = schema
        if isinstance(schema, dict) and schema.get("type") == "object":
            schema_input = {"title": "Response", **schema}
        response_schema = convert_to_openai_function(schema_input, strict=True)["parameters"]
        is_pydantic = isinstance(schema, type) and issubclass(schema, BaseModel)

        def parse(message):
            error = None
            parsed = None
            try:
                parsed = json.loads(message.content)
                if is_pydantic:
                    parsed = schema.model_validate(parsed)
            except (ValueError, TypeError):
                error = ValueError("Codex returned invalid structured output")
                if not include_raw:
                    raise error from None
            if include_raw:
                return {
                    "raw": message,
                    "parsed": parsed if error is None else None,
                    "parsing_error": error,
                }
            return parsed

        return self.bind(response_schema=response_schema) | RunnableLambda(parse)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        tools = kwargs.get("tools") or []
        response_schema = kwargs.get("response_schema")
        prompt = _prompt(messages)
        if tools:
            names = [tool["function"]["name"] for tool in tools]
            response_schema = _tool_response_schema(names)
            prompt += (
                "\nApplication tool definitions:\n"
                + json.dumps(tools, ensure_ascii=False)
                + "\nReturn content and tool_calls. Each call has name and arguments, "
                "where arguments is a JSON-encoded object matching that tool's parameters. "
                "Use an empty tool_calls array for a final answer. Tool choice: "
                + str(kwargs.get("tool_choice", "auto"))
            )
            if kwargs.get("parallel_tool_calls") is False:
                prompt += ". Return at most one tool call."
        elif response_schema:
            prompt += "\nReturn only a JSON object satisfying the supplied output schema."
        text = self._call_cli(prompt, response_schema)
        if tools:
            message = self._parse_tools(text, names, kwargs)
        else:
            if stop and not response_schema:
                for token in stop:
                    text = text.split(token, 1)[0]
            message = AIMessage(content=text)
        return ChatResult(generations=[ChatGeneration(message=message)])

    @staticmethod
    def _parse_tools(text, names, options) -> AIMessage:
        try:
            data = json.loads(text)
            content, calls = data["content"], data["tool_calls"]
            if not isinstance(content, str) or not isinstance(calls, list):
                raise ValueError
            parsed = []
            for call in calls:
                if call["name"] not in names:
                    raise ValueError
                args = json.loads(call["arguments"])
                if not isinstance(args, dict):
                    raise ValueError
                parsed.append(
                    {
                        "name": call["name"],
                        "args": args,
                        "id": "call_" + uuid.uuid4().hex,
                        "type": "tool_call",
                    }
                )
            choice = options.get("tool_choice", "auto")
            if choice == "none" and parsed:
                raise ValueError
            if choice == "required" and not parsed:
                raise ValueError
            if choice in names and (not parsed or any(c["name"] != choice for c in parsed)):
                raise ValueError
            if options.get("parallel_tool_calls") is False and len(parsed) > 1:
                raise ValueError
            return AIMessage(content=content, tool_calls=parsed)
        except (ValueError, TypeError, KeyError):
            raise ValueError("Codex returned invalid application tool output") from None

    def _call_cli(self, prompt: str, schema: dict | None) -> str:
        # Resolve before changing cwd. Bypass npm's Windows shell/Node shim so
        # timeouts terminate the native CLI, rather than leaving its child alive.
        executable = shutil.which(self.cli_command)
        if executable is None:
            raise FileNotFoundError("Codex CLI is not installed or is not on PATH")
        command = [executable]
        if Path(executable).suffix.lower() in (".cmd", ".bat", ".ps1"):
            packages = Path(executable).parent / "node_modules/@openai"
            arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
            triple = "aarch64" if arch == "arm64" else "x86_64"
            vendor_paths = [
                packages / f"codex-win32-{arch}/vendor",
                packages / f"codex/node_modules/@openai/codex-win32-{arch}/vendor",
                packages / "codex/vendor",
            ]
            candidates = [
                root / f"{triple}-pc-windows-msvc" / folder / "codex.exe"
                for root in vendor_paths
                for folder in ("bin", "codex")
            ]
            native = next((path for path in candidates if path.is_file()), None)
            if native is None:
                raise RuntimeError("Codex requires a native executable or the official npm CLI")
            command = [str(native)]
        with tempfile.TemporaryDirectory(prefix="tradingagents_codex_") as directory:
            output = Path(directory) / "response.txt"
            command += [
                "exec",
                "--model",
                self.model,
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--color",
                "never",
                "--output-last-message",
                str(output),
            ]
            if schema is not None:
                schema_file = Path(directory) / "schema.json"
                schema_file.write_text(json.dumps(schema), encoding="utf-8")
                command += ["--output-schema", str(schema_file)]
            if self.reasoning_effort:
                command += ["-c", "model_reasoning_effort=" + json.dumps(self.reasoning_effort)]
            command.append("-")
            try:
                result = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    cwd=directory,
                    shell=False,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"Codex CLI timed out after {self.timeout:g} seconds") from None
            except OSError:
                raise RuntimeError("Codex CLI could not be started") from None
            if result.returncode:
                # Do not put stderr/stdout, which may contain prompts or credentials,
                # into exceptions that upstream agents write to reports and logs.
                raise RuntimeError(
                    f"Codex CLI failed (exit {result.returncode}); check CLI login and model access"
                )
            try:
                response = output.read_text(encoding="utf-8").strip()
            except OSError:
                response = ""
            if not response:
                raise RuntimeError("Codex CLI returned no final response")
            return response


class CodexClient(BaseLLMClient):
    """Factory adapter; authentication is managed by ``codex login``."""

    def get_llm(self) -> CodexChatModel:
        return CodexChatModel(
            model=self.model,
            cli_command=self.kwargs.get("codex_command", self.kwargs.get("cli_command", "codex")),
            timeout=self.kwargs.get("codex_timeout", self.kwargs.get("timeout", 300)),
            reasoning_effort=self.kwargs.get("reasoning_effort"),
            callbacks=self.kwargs.get("callbacks"),
        )

    def validate_model(self) -> bool:
        return bool(self.model.strip())

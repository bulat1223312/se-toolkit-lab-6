"""Regression tests for the agent.py command-line interface."""

import json
import subprocess
from pathlib import Path


def _run_agent(question: str) -> dict:
    """Executes agent.py with a given question and parses the JSON output."""
    project_root = Path(__file__).parent.parent.parent.parent
    agent_path = project_root / "agent.py"

    result = subprocess.run(
        ["uv", "run", str(agent_path), question],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=project_root,
    )

    assert result.returncode == 0, f"agent.py failed with: {result.stderr}"

    output = result.stdout.strip()
    return json.loads(output)


def test_agent_outputs_valid_json_with_required_fields() -> None:
    """Validates that agent.py returns valid JSON containing all required fields."""
    data = _run_agent("What is 2+2?")

    assert "answer" in data, "Missing 'answer' field in output JSON"
    assert "tool_calls" in data, "Missing 'tool_calls' field in output JSON"
    assert isinstance(data["tool_calls"], list), "'tool_calls' must be an array"


def test_documentation_agent_uses_read_file_tool() -> None:
    """Verifies the agent invokes the read_file tool when answering documentation questions."""
    data = _run_agent("How do you resolve a merge conflict?")

    assert "answer" in data, "Missing 'answer' field"
    assert "source" in data, "Missing 'source' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Verify that the read_file tool was invoked
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "read_file" in tool_names, "Expected read_file tool to be called"

    # Ensure the source field references a wiki git-related markdown file
    assert "wiki/git" in data["source"], \
        f"Expected source to reference wiki/git*.md, got: {data['source']}"


def test_documentation_agent_uses_list_files_tool() -> None:
    """Verifies the agent invokes the list_files tool when answering directory questions."""
    data = _run_agent("What files are in the wiki?")

    assert "answer" in data, "Missing 'answer' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Verify that the list_files tool was invoked
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "list_files" in tool_names, "Expected list_files tool to be called"


def test_system_agent_uses_read_file_for_framework_question() -> None:
    """Verifies the agent uses read_file to locate framework information within source code."""
    data = _run_agent("What framework does the backend use?")

    assert "answer" in data, "Missing 'answer' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Verify read_file was used to inspect the source code
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "read_file" in tool_names, "Expected read_file tool to be called"


def test_system_agent_uses_query_api_for_data_question() -> None:
    """Verifies the agent uses query_api to retrieve data from the backend."""
    data = _run_agent("How many items are in the database?")

    assert "answer" in data, "Missing 'answer' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Verify that the query_api tool was invoked
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "query_api" in tool_names, "Expected query_api tool to be called"
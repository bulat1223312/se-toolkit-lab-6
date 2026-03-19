"""Regression test suite validating the CLI behavior of agent.py."""

import json
import subprocess
from pathlib import Path


def _run_agent(question: str) -> dict:
    """Auxiliary utility to execute agent.py and parse the resulting JSON payload."""
    project_root = Path(__file__).parent.parent.parent.parent
    agent_path = project_root / "agent.py"

    result = subprocess.run(
        ["uv", "run", str(agent_path), question],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=project_root,
    )

    assert result.returncode == 0, f"agent.py execution failed with: {result.stderr}"

    output = result.stdout.strip()
    return json.loads(output)


def test_agent_outputs_valid_json_with_required_fields() -> None:
    """Verify that the agent emits well-formed JSON containing all mandatory schema fields."""
    data = _run_agent("What is 2+2?")

    assert "answer" in data, "Missing 'answer' field in output JSON"
    assert "tool_calls" in data, "Missing 'tool_calls' field in output JSON"
    assert isinstance(data["tool_calls"], list), "'tool_calls' must be an array"


def test_documentation_agent_uses_read_file_tool() -> None:
    """Validate that the agent leverages the read_file tool when addressing documentation-related inquiries."""
    data = _run_agent("How do you resolve a merge conflict?")

    assert "answer" in data, "Missing 'answer' field"
    assert "source" in data, "Missing 'source' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Confirm that the read_file tool was invoked during execution
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "read_file" in tool_names, "Expected read_file tool to be called"

    # Ensure the source citation points to a wiki file concerning Git operations
    assert "wiki/git" in data["source"], \
        f"Expected source to reference wiki/git*.md, got: {data['source']}"


def test_documentation_agent_uses_list_files_tool() -> None:
    """Ensure the agent utilizes the list_files tool when responding to directory structure queries."""
    data = _run_agent("What files are in the wiki?")

    assert "answer" in data, "Missing 'answer' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Verify that the list_files tool was triggered
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "list_files" in tool_names, "Expected list_files tool to be called"


def test_system_agent_uses_read_file_for_framework_question() -> None:
    """Ascertain that the agent employs read_file to extract framework details from the source codebase."""
    data = _run_agent("What framework does the backend use?")

    assert "answer" in data, "Missing 'answer' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Validate that read_file was utilized to inspect underlying source artifacts
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "read_file" in tool_names, "Expected read_file tool to be called"


def test_system_agent_uses_query_api_for_data_question() -> None:
    """Confirm that the agent invokes query_api to retrieve dynamic data from the backend service."""
    data = _run_agent("How many items are in the database?")

    assert "answer" in data, "Missing 'answer' field"
    assert "tool_calls" in data, "Missing 'tool_calls' field"

    # Verify that the query_api tool was executed to fetch data
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "query_api" in tool_names, "Expected query_api tool to be called"
"""Regression test for agent.py CLI."""

import json
import subprocess
from pathlib import Path


def test_agent_outputs_valid_json_with_required_fields() -> None:
    """Test that agent.py outputs valid JSON with 'answer' and 'tool_calls' fields."""
    project_root = Path(__file__).parent.parent.parent.parent
    agent_path = project_root / "agent.py"

    result = subprocess.run(
        ["uv", "run", str(agent_path), "What is 2+2?"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=project_root,
    )

    assert result.returncode == 0, f"agent.py failed with: {result.stderr}"

    output = result.stdout.strip()
    data = json.loads(output)

    assert "answer" in data, "Missing 'answer' field in output JSON"
    assert "tool_calls" in data, "Missing 'tool_calls' field in output JSON"
    assert isinstance(data["tool_calls"], list), "'tool_calls' must be an array"
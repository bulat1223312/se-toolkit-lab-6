import subprocess
import json
import sys

def test_agent_basic():
    # Запускаем agent.py с тестовым вопросом
    result = subprocess.run(
        [sys.executable, "agent.py", "What does REST stand for?"],
        capture_output=True,
        text=True,
        timeout=60
    )

    # Проверяем код возврата
    assert result.returncode == 0, f"Non-zero exit code: {result.returncode}"

    # Парсим stdout как JSON
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError:
        assert False, f"stdout not valid JSON: {result.stdout}"

    # Проверяем наличие обязательных полей
    assert "answer" in output, "Missing 'answer' field"
    assert "tool_calls" in output, "Missing 'tool_calls' field"
    assert isinstance(output["tool_calls"], list), "'tool_calls' must be a list"
    assert output["answer"], "Answer is empty"


def test_merge_conflict():
    """Проверяет, что при вопросе о merge conflict вызывается read_file и source указывает на wiki/git-workflow.md"""
    result = subprocess.run(
        ["uv", "run", "agent.py", "How do you resolve a merge conflict?"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)

    assert "answer" in data
    assert "source" in data
    assert "wiki/git-workflow.md" in data["source"]
    assert "#" in data["source"]  # должен быть якорь

    # Проверяем, что среди tool_calls был read_file с путём wiki/git-workflow.md
    calls = data.get("tool_calls", [])
    assert any(
        c["tool"] == "read_file" and "wiki/git-workflow.md" in c["args"].get("path", "")
        for c in calls
    ), "Не найден вызов read_file с wiki/git-workflow.md"


def test_list_wiki():
    """Проверяет, что при вопросе о содержимом wiki вызывается list_files"""
    result = subprocess.run(
        ["uv", "run", "agent.py", "What files are in the wiki?"],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)

    calls = data.get("tool_calls", [])
    assert any(
        c["tool"] == "list_files" and c["args"].get("path") == "wiki"
        for c in calls
    ), "Не найден вызов list_files с path='wiki'"
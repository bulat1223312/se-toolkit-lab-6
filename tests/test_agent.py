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
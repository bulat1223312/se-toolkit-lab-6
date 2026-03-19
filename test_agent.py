"""Регрессионные тесты для CLI агента (agent.py)."""

import json
import subprocess
from pathlib import Path


def _run_agent(question: str) -> dict:
    """Вспомогательная функция для запуска agent.py и парсинга вывода."""
    project_root = Path(__file__).parent.parent.parent.parent
    agent_path = project_root / "agent.py"

    result = subprocess.run(
        ["uv", "run", str(agent_path), question],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=project_root,
    )

    assert result.returncode == 0, f"agent.py завершился с ошибкой: {result.stderr}"

    output = result.stdout.strip()
    return json.loads(output)


def test_agent_outputs_valid_json_with_required_fields() -> None:
    """Проверяет, что агент возвращает валидный JSON с обязательными полями."""
    data = _run_agent("What is 2+2?")

    assert "answer" in data, "Отсутствует поле 'answer' в выходном JSON"
    assert "tool_calls" in data, "Отсутствует поле 'tool_calls' в выходном JSON"
    assert isinstance(data["tool_calls"], list), "'tool_calls' должен быть массивом"


def test_documentation_agent_uses_read_file_tool() -> None:
    """Проверяет использование инструмента read_file для вопросов по документации."""
    data = _run_agent("How do you resolve a merge conflict?")

    assert "answer" in data, "Отсутствует поле 'answer'"
    assert "source" in data, "Отсутствует поле 'source'"
    assert "tool_calls" in data, "Отсутствует поле 'tool_calls'"

    # Убеждаемся, что был вызван инструмент read_file
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "read_file" in tool_names, "Ожидался вызов инструмента read_file"

    # Проверяем, что источник ссылается на файл вики по теме git
    assert "wiki/git" in data["source"], \
        f"Ожидалось, что source будет ссылаться на wiki/git*.md, получено: {data['source']}"


def test_documentation_agent_uses_list_files_tool() -> None:
    """Проверяет использование инструмента list_files для вопросов о содержимом директорий."""
    data = _run_agent("What files are in the wiki?")

    assert "answer" in data, "Отсутствует поле 'answer'"
    assert "tool_calls" in data, "Отсутствует поле 'tool_calls'"

    # Убеждаемся, что был вызван инструмент list_files
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "list_files" in tool_names, "Ожидался вызов инструмента list_files"


def test_system_agent_uses_read_file_for_framework_question() -> None:
    """Проверяет, что агент использует read_file для поиска информации о фреймворке в исходном коде."""
    data = _run_agent("What framework does the backend use?")

    assert "answer" in data, "Отсутствует поле 'answer'"
    assert "tool_calls" in data, "Отсутствует поле 'tool_calls'"

    # Убеждаемся, что read_file был использован для анализа исходного кода
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "read_file" in tool_names, "Ожидался вызов инструмента read_file"


def test_system_agent_uses_query_api_for_data_question() -> None:
    """Проверяет, что агент использует query_api для получения данных из бэкенда."""
    data = _run_agent("How many items are in the database?")

    assert "answer" in data, "Отсутствует поле 'answer'"
    assert "tool_calls" in data, "Отсутствует поле 'tool_calls'"

    # Убеждаемся, что был вызван инструмент query_api
    tool_names = [tc.get("tool") for tc in data["tool_calls"]]
    assert "query_api" in tool_names, "Ожидался вызов инструмента query_api"
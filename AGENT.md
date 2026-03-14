# Agent Documentation

## Overview
Agent теперь умеет читать файлы из папки `wiki` и отвечать на вопросы, ссылаясь на документацию. Для этого используются два инструмента (function calling).

## Инструменты (tools)
- **read_file(path)** – читает содержимое файла. `path` – относительный путь от корня проекта (например, `wiki/git-workflow.md`).
- **list_files(path)** – возвращает список файлов и папок в указанной директории (например, `wiki`).

Оба инструмента защищены от выхода за пределы проекта (проверка `safe_join`).

## Агентский цикл
1. Пользователь задаёт вопрос.
2. Системный промпт инструктирует агента использовать инструменты для поиска ответа в папке `wiki`.
3. Цикл до 10 итераций:
   - Запрос к LLM с описанием инструментов.
   - Если LLM вызывает инструменты – они выполняются, результаты возвращаются в историю.
   - Если LLM даёт текстовый ответ – из него извлекается строка `Source: ...` (указывает на файл и секцию) и возвращается финальный JSON.
4. Если за 10 итераций ответ не получен, возвращается последнее сообщение ассистента.

## Формат вывода
Всегда JSON с полями:
- `answer` (string) – ответ на вопрос (без строки Source).
- `source` (string) – ссылка на wiki-файл и секцию (например, `wiki/git-workflow.md#resolving-merge-conflicts`).
- `tool_calls` (array) – список всех выполненных вызовов инструментов. Каждый элемент содержит `tool`, `args`, `result`.

Пример:
```json
{
  "answer": "Edit the conflicting file, choose which changes to keep, then stage and commit.",
  "source": "wiki/git-workflow.md#resolving-merge-conflicts",
  "tool_calls": [
    {"tool": "list_files", "args": {"path": "wiki"}, "result": "git-workflow.md\n..."},
    {"tool": "read_file", "args": {"path": "wiki/git-workflow.md"}, "result": "..."}
  ]
}
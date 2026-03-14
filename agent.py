#!/usr/bin/env python
import os
import sys
import json
import requests
from openai import OpenAI
from dotenv import load_dotenv

# Загружаем переменные окружения из .env.agent.secret (LLM) и .env.docker.secret (LMS)
load_dotenv(".env.agent.secret")
load_dotenv(".env.docker.secret")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def safe_join(base, *paths):
    """Обеспечивает безопасное объединение путей, не позволяя выйти за пределы PROJECT_ROOT."""
    abs_path = os.path.abspath(os.path.join(base, *paths))
    if os.path.commonpath([abs_path, base]) != base:
        raise ValueError("Access denied: path outside project directory")
    return abs_path


def read_file(path):
    """Читает содержимое файла внутри проекта."""
    try:
        full_path = safe_join(PROJECT_ROOT, path)
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


def list_files(path):
    """Возвращает список файлов в указанной директории внутри проекта."""
    try:
        full_path = safe_join(PROJECT_ROOT, path)
        entries = os.listdir(full_path)
        return "\n".join(entries)
    except Exception as e:
        return f"Error listing directory: {e}"


def query_api(method: str, path: str, body: str = None) -> str:
    """
    Выполняет HTTP-запрос к развёрнутому бэкенду.
    Возвращает JSON-строку с полями status_code и body.
    """
    base_url = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")
    api_key = os.getenv("LMS_API_KEY")

    if not api_key:
        return json.dumps({"status_code": 500, "body": "LMS_API_KEY not set"})

    headers = {"Authorization": f"Bearer {api_key}"}
    # Убираем лишние слеши
    url = base_url.rstrip('/') + '/' + path.lstrip('/')
    try:
        json_body = json.loads(body) if body else None
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=headers,
            json=json_body,
            timeout=10
        )
        return json.dumps({
            "status_code": response.status_code,
            "body": response.text
        })
    except Exception as e:
        return json.dumps({"status_code": 500, "body": str(e)})


# Схемы инструментов для OpenAI function calling
tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the project (source code, wiki, configs).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from project root (e.g., wiki/git-workflow.md, backend/main.py)"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories in a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from project root (e.g., wiki, backend)"
                    }
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": "Call the running backend API. Use for dynamic data (item count, scores), status codes, or error reproduction.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "DELETE"],
                        "description": "HTTP method"
                    },
                    "path": {
                        "type": "string",
                        "description": "API path, e.g., '/items/' or '/analytics/completion-rate?lab=lab-99'"
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional JSON request body as a string (for POST/PUT)"
                    }
                },
                "required": ["method", "path"]
            }
        }
    }
]


def run_agent(question, client, model, system_prompt):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question}
    ]
    all_tool_calls = []

    for _ in range(10):  # максимум 10 итераций
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.0,
                timeout=50
            )
        except Exception as e:
            return {"error": f"LLM call failed: {e}"}

        message = response.choices[0].message

        if message.tool_calls:
            messages.append(message)
            for tool_call in message.tool_calls:
                func_name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                # Выполняем нужную функцию
                if func_name == "read_file":
                    result = read_file(args.get("path", ""))
                elif func_name == "list_files":
                    result = list_files(args.get("path", ""))
                elif func_name == "query_api":
                    # Извлекаем параметры с учётом optional body
                    method = args.get("method", "GET")
                    path = args.get("path", "")
                    body = args.get("body")
                    result = query_api(method, path, body)
                else:
                    result = f"Unknown tool: {func_name}"

                all_tool_calls.append({
                    "tool": func_name,
                    "args": args,
                    "result": result
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
            continue  # после обработки tool_calls запрашиваем следующий ответ LLM

        # Достигнут финальный ответ (без tool_calls)
        final_text = message.content or ""

        # Ищем строку Source: в конце (для вики-вопросов). Если нет – source останется пустым.
        source = ""
        lines = final_text.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            stripped = lines[i].strip()
            if stripped.startswith("Source:"):
                source = stripped[7:].strip()
                lines.pop(i)
                break
        clean_answer = "\n".join(lines).strip()

        return {
            "answer": clean_answer,
            "source": source,
            "tool_calls": all_tool_calls
        }

    # Если цикл завершился без возврата (слишком много итераций)
    last_message = messages[-1] if messages else None
    if last_message and last_message.get("role") == "assistant":
        return {
            "answer": last_message.content or "",
            "source": "",
            "tool_calls": all_tool_calls
        }
    else:
        return {"error": "Agent loop reached max iterations without final answer"}


def main():
    if len(sys.argv) < 2:
        print("Ошибка: не указан вопрос", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    # Чтение обязательных переменных для LLM
    llm_api_key = os.getenv("LLM_API_KEY")
    llm_api_base = os.getenv("LLM_API_BASE")
    llm_model = os.getenv("LLM_MODEL")

    if not all([llm_api_key, llm_api_base, llm_model]):
        print("Ошибка: не заданы LLM_API_KEY, LLM_API_BASE или LLM_MODEL", file=sys.stderr)
        sys.exit(1)

    # Переменные для query_api (AGENT_API_BASE_URL опциональна, LMS_API_KEY проверяется в функции)
    # При локальной разработке они должны быть загружены из .env.docker.secret

    client = OpenAI(api_key=llm_api_key, base_url=llm_api_base)

    # Обновлённый системный промпт с чёткими правилами выбора инструментов
    system_prompt = (
        "You are an assistant that helps developers understand a project. "
        "You have three tools: read_file, list_files, and query_api.\n"
        "- Use read_file/list_files for questions about the codebase, configuration, wiki (e.g., 'what framework', 'how to protect a branch').\n"
        "- Use query_api for questions about dynamic data (e.g., 'how many items', 'status code without auth') and to reproduce API errors.\n"
        "- If an API call returns an error, you may need to read the corresponding source code to diagnose the bug: first call query_api, then read_file on the relevant file.\n"
        "After you find the answer (from files), always append a line at the very end in the format: "
        "'Source: <file_path>#<section_anchor>' (for wiki questions). For system questions, you do not need to add a Source line.\n"
        "Answer concisely and include the requested information."
    )

    result = run_agent(question, client, llm_model, system_prompt)

    # Выводим результат в JSON (ensure_ascii=False для поддержки русского языка)
    print(json.dumps(result, ensure_ascii=False))

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
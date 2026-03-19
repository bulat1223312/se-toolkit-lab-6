#!/usr/bin/env python3
import os
import json
import sys
import requests
import openai
from typing import List, Dict, Any

# ---------- Переменные окружения ----------
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_API_BASE = os.getenv("LLM_API_BASE")
LLM_MODEL = os.getenv("LLM_MODEL")
LMS_API_KEY = os.getenv("LMS_API_KEY")
AGENT_API_BASE_URL = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")

# Проверка наличия обязательных переменных для LLM (необязательно для запуска, но для отладки)
if not all([LLM_API_KEY, LLM_API_BASE, LLM_MODEL]):
    print(json.dumps({"error": "Missing LLM environment variables (LLM_API_KEY, LLM_API_BASE, LLM_MODEL)"}), file=sys.stderr)
    sys.exit(1)

# ---------- Инструменты ----------
def read_file(path: str) -> str:
    """Читает содержимое файла. Путь относительно корня проекта."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {path}: {e}"

def list_files(path: str = ".") -> str:
    """Возвращает список файлов в директории."""
    try:
        files = os.listdir(path)
        return "\n".join(files)
    except Exception as e:
        return f"Error listing files in {path}: {e}"

def query_api(method: str, path: str, body: str = None, authenticate: bool = True) -> str:
    """
    Выполняет HTTP-запрос к бэкенду.
    Возвращает JSON-строку с полями status_code и body.
    """
    base_url = AGENT_API_BASE_URL
    url = base_url.rstrip('/') + '/' + path.lstrip('/')
    headers = {}
    if authenticate:
        if not LMS_API_KEY:
            return json.dumps({"status_code": 500, "body": "LMS_API_KEY not set"})
        headers["Authorization"] = f"Bearer {LMS_API_KEY}"
    try:
        method = method.upper()
        if method == "GET":
            resp = requests.get(url, headers=headers)
        elif method == "POST":
            data = json.loads(body) if body else None
            resp = requests.post(url, headers=headers, json=data)
        elif method == "PUT":
            data = json.loads(body) if body else None
            resp = requests.put(url, headers=headers, json=data)
        elif method == "DELETE":
            resp = requests.delete(url, headers=headers)
        else:
            return json.dumps({"status_code": 400, "body": "Unsupported method"})
        return json.dumps({"status_code": resp.status_code, "body": resp.text})
    except Exception as e:
        return json.dumps({"status_code": 500, "body": f"Request failed: {str(e)}"})

# ---------- Схемы инструментов для LLM ----------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use this to access wiki documentation or source code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file relative to project root"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory. Use this to explore the project structure.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default: current directory)"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_api",
            "description": "Send a request to the backend API. Use this to get dynamic data (e.g., item counts, analytics) or to test endpoint behaviour. Returns JSON with 'status_code' and 'body'. To get a count, parse the body (often a JSON array) and return its length.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                    "path": {"type": "string", "description": "API endpoint path, e.g., /items/ or /analytics/completion-rate?lab=lab-99"},
                    "body": {"type": "string", "description": "JSON request body (for POST/PUT)"},
                    "authenticate": {"type": "boolean", "description": "Whether to include the backend API key (default true)"}
                },
                "required": ["method", "path"]
            }
        }
    }
]

# ---------- Системный промпт (улучшенный) ----------
SYSTEM_PROMPT = """
You are an AI assistant with access to tools. Use them to answer questions about the project.

Available tools:
- read_file: read a file from the project (use for wiki or source code).
- list_files: list files in a directory.
- query_api: send HTTP requests to the backend API. Use this for questions about live data (item count, analytics) or to test API behaviour. By default it includes the backend API key; set authenticate=false to simulate unauthenticated requests.

When answering:

1. **Documentation questions** (wiki): use read_file on files under 'wiki/'.

2. **Source code questions** (framework, routes): use read_file on relevant .py files. Start with main backend files like 'backend/main.py' or 'backend/app.py'. Look for imports to identify the framework.

3. **Live data questions** (item counts, learners, scores): use query_api.
   - For questions asking "how many" or a count, after calling the API, parse the response body (which is often a JSON array) and return the length of the array.
   - Example: if the API returns [{"id":1}, {"id":2}], answer "2 items".

4. **Debugging errors**: first use query_api to see the error, then read_file on the relevant source code to locate the bug.
   - Look for common bug patterns: division by zero (operator `/`), operations on None, sorting without handling None (sorted(...) with None in list).
   - When asked about risky operations in analytics.py, specifically search for `/` (division) and `sorted()` calls that might receive None.

5. **Complex explanations** (e.g., request lifecycle): read all relevant files step by step (e.g., docker-compose.yml, Caddyfile, Dockerfile, main.py) and synthesize the information into a coherent answer.

6. **Comparisons** (e.g., ETL vs API error handling): read the code for each part separately (etl.py and routers/), then describe the differences in their error handling strategies (e.g., try/except blocks, return codes, logging).

Always output your reasoning step by step. When you need to use a tool, respond with a valid function call.
"""

# ---------- Вызов LLM (OpenAI) ----------
def call_llm(messages: List[Dict[str, str]], tools: List[Dict]) -> Dict[str, Any]:
    """
    Реальный вызов OpenAI API с поддержкой function calling.
    """
    try:
        # Настройка клиента (старый стиль openai<1.0.0, но многие ещё используют)
        openai.api_key = LLM_API_KEY
        openai.api_base = LLM_API_BASE

        response = openai.ChatCompletion.create(
            model=LLM_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        # Возвращаем сообщение (содержит content и/или tool_calls)
        return response.choices[0].message
    except Exception as e:
        # В случае ошибки возвращаем сообщение об ошибке, чтобы агент продолжил
        return {
            "content": f"LLM call failed: {str(e)}",
            "tool_calls": None
        }

# ---------- Основной цикл агента ----------
def run_agent(user_query: str) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_query}
    ]
    tool_calls_log = []
    max_iterations = 20  # увеличено для сложных многошаговых задач

    for _ in range(max_iterations):
        response = call_llm(messages, TOOLS)
        # Извлекаем content (может быть None) и tool_calls
        content = response.get("content")
        tool_calls = response.get("tool_calls")

        # Если есть вызовы инструментов – выполняем их
        if tool_calls:
            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}
                # Выполняем соответствующий инструмент
                if func_name == "read_file":
                    result = read_file(**args)
                elif func_name == "list_files":
                    result = list_files(**args)
                elif func_name == "query_api":
                    result = query_api(**args)
                else:
                    result = f"Unknown tool: {func_name}"
                tool_calls_log.append({
                    "tool": func_name,
                    "args": args,
                    "result": result
                })
                # Добавляем результат вызова в историю
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call_{len(tool_calls_log)}"),
                    "content": result
                })
        else:
            # Нет вызовов инструментов – это финальный ответ
            final_answer = content or ""
            return {
                "answer": final_answer,
                "tool_calls": tool_calls_log
            }

    # Если превышено число итераций
    return {
        "answer": "Agent stopped: too many iterations.",
        "tool_calls": tool_calls_log
    }

# ---------- Точка входа ----------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py 'your question'")
        sys.exit(1)
    question = sys.argv[1]
    result = run_agent(question)
    # Печатаем только JSON, без лишних логов
    print(json.dumps(result, indent=2, ensure_ascii=False))
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 АГЕНТ СИСТЕМНОЙ ПОДДЕРЖКИ (System Support Agent)
====================================================

Этот скрипт реализует интеллектуального агента на базе LLM, который:
- Отвечает на вопросы пользователя о проекте, документации и системе
- Использует инструменты для чтения файлов, листинга директорий и запросов к API
- Работает в цикле "мышление → действие → наблюдение → ответ"

Архитектура:
1. Загрузка конфигурации из .env файлов
2. Инициализация инструментов (read_file, list_files, query_api)
3. Цикл взаимодействия с LLM: отправка запроса → получение tool_call → выполнение → обратная связь
4. Формирование финального ответа в строгом JSON-формате

Безопасность:
- Все пути проверяются на наличие директорий-ссылок (../)
- Доступ разрешён только внутри PROJECT_ROOT
- API-запросы используют аутентификацию при наличии ключа

Автор: [Ваше имя/команда]
Дата: 2026
"""

# ============================================================================
# 📦 ИМПОРТ МОДУЛЕЙ
# ============================================================================
import json      # Работа с JSON: парсинг, сериализация, валидация
import os        # Доступ к переменным окружения и системным путям
import re        # Регулярные выражения для извлечения JSON из ответов LLM
import sys       # Работа с аргументами командной строки и потоками вывода
from pathlib import Path  # Объектно-ориентированная работа с файловыми путями

import requests  # HTTP-клиент для запросов к LLM API и бэкенду
from dotenv import load_dotenv  # Загрузка переменных из .env файлов

# ============================================================================
# 🔐 ЗАГРУЗКА КОНФИГУРАЦИИ ИЗ .ENV ФАЙЛОВ
# ============================================================================
# Поддерживаем многоуровневую конфигурацию: сначала агент, потом докер-секреты
# Это позволяет гибко управлять настройками в разных средах (dev/stage/prod)
env_files = [".env.agent.secret", ".env.docker.secret"]
for env_file in env_files:
    env_path = Path(__file__).parent / env_file
    if env_path.exists():
        # load_dotenv автоматически добавит переменные в os.environ
        load_dotenv(env_path)

# ============================================================================
# ⚙️ КОНФИГУРАЦИЯ: LLM (Large Language Model)
# ============================================================================
# API-ключ для аутентификации запросов к провайдеру модели
API_KEY = os.getenv("LLM_API_KEY")
# Базовый URL эндпоинта для chat/completions (совместим с OpenAI API)
API_BASE = os.getenv("LLM_API_BASE")
# Имя модели по умолчанию; можно переопределить через .env
# Рекомендовано: qwen3-coder-plus для задач с кодом и архитектурой
MODEL = os.getenv("LLM_MODEL", "qwen3-coder-plus")

# ============================================================================
# 🌐 КОНФИГУРАЦИЯ: BACKEND API (LMS - Learning Management System)
# ============================================================================
# Ключ аутентификации для запросов к внутреннему API системы
LMS_API_KEY = os.getenv("LMS_API_KEY", "")
# Базовый URL агента-шлюза, через который идут все запросы к бэкенду
# По умолчанию: локальный хост на порту 42002 (Caddy reverse proxy)
AGENT_API_BASE_URL = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")

# ============================================================================
# 🔒 БЕЗОПАСНОСТЬ: КОРЕНЬ ПРОЕКТА ДЛЯ ПРОВЕРКИ ПУТЕЙ
# ============================================================================
# Абсолютный путь к корню проекта — используется для валидации всех файловых операций
# Это предотвращает выход за пределы разрешённой директории (path traversal атаки)
PROJECT_ROOT = Path(__file__).parent.resolve()

# ============================================================================
# 🔄 ОГРАНИЧЕНИЯ: МАКСИМАЛЬНОЕ КОЛИЧЕСТВО ВЫЗОВОВ ИНСТРУМЕНТОВ
# ============================================================================
# Чтобы избежать бесконечных циклов и чрезмерного расхода токенов,
# агент может сделать не более MAX_TOOL_CALLS итераций на один вопрос
MAX_TOOL_CALLS = 10

# ============================================================================
# 🧠 СИСТЕМНЫЙ ПРОМПТ: ИНСТРУКЦИИ ДЛЯ МОДЕЛИ
# ============================================================================
# Этот промпт определяет "личность", возможности и правила поведения агента.
# Он критически важен для корректной работы: модель должна строго следовать JSON-формату.
SYSTEM_PROMPT = """You are a system assistant that can read documentation files AND query a backend API.

Your task is to answer user questions using the appropriate tools.

🔧 Available tools:
• list_files: List files and directories at a given path (use for exploring wiki structure)
• read_file: Read the contents of a file (use for wiki docs or source code)
• query_api: Query the backend LMS API (use for data queries like item counts, analytics, scores, HTTP status codes)

📋 Tool selection guide:
1. For documentation questions (how-to, workflows, processes) → use list_files and read_file on wiki/
2. For system facts (framework, ports, status codes) → use read_file on source code (backend/)
3. For data queries (how many items, scores, analytics, HTTP responses) → use query_api
4. For bug diagnosis → use query_api to see errors, then read_file to check source code
5. For architecture questions (request flow, docker) → read relevant config files and synthesize an answer

🌐 query_api parameters:
• method: HTTP method (GET, POST, PUT, DELETE)
• path: API endpoint path with query params for GET (e.g., /items/, /analytics/completion-rate?lab=lab-99)
• body: JSON request body for POST/PUT only (as JSON string, do NOT use for GET requests)
• use_auth: Whether to include authentication (default: true, set to false to test unauthenticated access)

⚠️ For GET requests with parameters, ALWAYS include them in the path as query parameters (e.g., /analytics/top-learners?lab=lab-01&limit=10). Do NOT use the body field for GET requests.

❗ IMPORTANT RULES:
• You must respond with ONLY valid JSON. No other text, no explanations, no thinking out loud.
• Make ONLY ONE tool call at a time. Wait for the result before making another call.
• After gathering enough information (2-4 tool calls), provide a final answer.
• Don't keep calling tools indefinitely - synthesize what you learned into a clear answer.
• NEVER include any text outside the JSON object. Start your response with { and end with }.

📦 To call a tool, respond with EXACTLY this JSON format (ONE tool call per response):
{"tool_call": {"name": "tool_name", "arguments": {"arg1": "value1", ...}}}

✅ To give a final answer, respond with EXACTLY this JSON format:
{"final_answer": {"answer": "your answer here", "source": "wiki/file.md#section-anchor"}}

📍 For the source field:
• If you found the answer in a wiki file, use: wiki/file.md#section-anchor
• If you found the answer in source code, use: backend/path/to/file.py
• If you got the answer from the API, you can leave source empty or use: api/endpoint

💡 Examples of tool calls:
• {"tool_call": {"name": "read_file", "arguments": {"path": "wiki/git-workflow.md"}}}
• {"tool_call": {"name": "list_files", "arguments": {"path": "wiki"}}}
• {"tool_call": {"name": "query_api", "arguments": {"method": "GET", "path": "/items/"}}}
• {"tool_call": {"name": "query_api", "arguments": {"method": "GET", "path": "/items/", "use_auth": false}}}

🎯 Examples of final answers:
• {"final_answer": {"answer": "FastAPI", "source": "backend/app/main.py"}}
• {"final_answer": {"answer": "401 Unauthorized", "source": ""}}
• {"final_answer": {"answer": "Browser → Caddy (port 42002) → FastAPI (port 8000) → PostgreSQL (port 5432) → back through the chain", "source": "docker-compose.yml"}}
"""


# ============================================================================
# 🛡️ ФУНКЦИИ БЕЗОПАСНОСТИ И РАБОТЫ С ФАЙЛАМИ
# ============================================================================

def is_safe_path(path: str) -> bool:
    """
    🔐 Проверка безопасности пути: предотвращение директорий-ссылок и абсолютных путей
    
    Цель: защитить файловую систему от атак типа "path traversal" (../../etc/passwd)
    
    Args:
        path: Строка с путём, который нужно проверить
        
    Returns:
        bool: True если путь безопасен (относительный, без ..), False иначе
    """
    # Отклоняем пути с переходом на уровень вверх или абсолютные пути
    if ".." in path or path.startswith("/"):
        return False
    return True


def read_file(path: str) -> str:
    """
    📄 Чтение содержимого файла из репозитория проекта
    
    Безопасная обёртка над file.read_text() с проверками:
    - Валидация пути через is_safe_path()
    - Проверка существования файла
    - Обработка исключений при чтении
    
    Args:
        path: Относительный путь к файлу от корня проекта
        
    Returns:
        str: Содержимое файла ИЛИ строка с описанием ошибки
    """
    # Шаг 1: Проверка безопасности пути
    if not is_safe_path(path):
        return "Error: Access denied - invalid path"

    # Шаг 2: Формирование полного пути и проверка существования
    full_path = PROJECT_ROOT / path
    if not full_path.exists():
        return f"Error: File not found - {path}"
    if not full_path.is_file():
        return f"Error: Not a file - {path}"

    # Шаг 3: Чтение файла с явным указанием кодировки UTF-8
    try:
        return full_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error: Could not read file - {e}"


def list_files(path: str) -> str:
    """
    📁 Получение списка файлов и поддиректорий в указанной директории
    
    Полезно для исследования структуры wiki/, backend/ и других разделов проекта.
    Возвращает отсортированный по алфавиту список имён.
    
    Args:
        path: Относительный путь к директории от корня проекта
        
    Returns:
        str: Список имён (по одному в строке) ИЛИ строка с ошибкой
    """
    # Проверка безопасности пути
    if not is_safe_path(path):
        return "Error: Access denied - invalid path"

    full_path = PROJECT_ROOT / path
    if not full_path.exists():
        return f"Error: Directory not found - {path}"
    if not full_path.is_dir():
        return f"Error: Not a directory - {path}"

    try:
        # Получаем имена всех элементов и сортируем для предсказуемого вывода
        entries = sorted([e.name for e in full_path.iterdir()])
        return "\n".join(entries)
    except Exception as e:
        return f"Error: Could not list directory - {e}"


# ============================================================================
# 🌐 ФУНКЦИЯ ЗАПРОСОВ К ВНЕШНЕМУ API (LMS Backend)
# ============================================================================

def query_api(method: str, path: str, body: str = None, use_auth: bool = True) -> str:
    """
    🚀 Выполнение HTTP-запроса к бэкенд-сервису LMS
    
    Поддерживает методы: GET, POST, PUT, DELETE
    Автоматически добавляет Bearer-токен, если use_auth=True и ключ задан
    Возвращает результат в виде JSON-строки со статусом и телом ответа
    
    Args:
        method: HTTP-метод (регистр не важен)
        path: Путь эндпоинта, включая query-параметры для GET (напр. /items/?status=active)
        body: JSON-строка с телом запроса (только для POST/PUT)
        use_auth: Флаг добавления заголовка Authorization (по умолчанию True)
        
    Returns:
        str: JSON-строка вида {"status_code": 200, "body": {...}} или {"status_code": 0, "body": {"error": "..."}}
    """
    # Формируем полный URL из базового адреса и пути
    url = f"{AGENT_API_BASE_URL}{path}"
    
    # Базовые заголовки: указываем, что отправляем/принимаем JSON
    headers = {
        "Content-Type": "application/json",
    }
    
    # Добавляем аутентификацию только если явно разрешено и ключ существует
    if use_auth and LMS_API_KEY:
        headers["Authorization"] = f"Bearer {LMS_API_KEY}"
    
    try:
        # Выбор метода запроса с обработкой тела для POST/PUT
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method.upper() == "POST":
            # Парсим body из строки в dict, если передан
            data = json.loads(body) if body else {}
            response = requests.post(url, headers=headers, json=data, timeout=30)
        elif method.upper() == "PUT":
            data = json.loads(body) if body else {}
            response = requests.put(url, headers=headers, json=data, timeout=30)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers, timeout=30)
        else:
            # Неизвестный метод — возвращаем ошибку клиенту
            return json.dumps({"status_code": 400, "body": {"error": f"Unknown method: {method}"}})
        
        # Формируем унифицированный ответ: статус + тело (распарсенный JSON или пустой dict)
        result = {
            "status_code": response.status_code,
            "body": response.json() if response.content else {}
        }
        return json.dumps(result)
        
    except requests.exceptions.Timeout:
        return json.dumps({"status_code": 0, "body": {"error": "Request timed out after 30s"}})
    except requests.exceptions.ConnectionError:
        return json.dumps({"status_code": 0, "body": {"error": "Failed to connect to backend API"}})
    except json.JSONDecodeError:
        # Бэкенд вернул не-JSON ответ — возвращаем как есть
        return json.dumps({"status_code": response.status_code, "body": {"raw_response": response.text}})
    except Exception as e:
        # Любая другая ошибка — логируем и возвращаем безопасное сообщение
        return json.dumps({"status_code": 0, "body": {"error": str(e)}})


# ============================================================================
# 🧰 РЕЕСТР ДОСТУПНЫХ ИНСТРУМЕНТОВ (Tool Registry)
# ============================================================================
# Словарь: имя инструмента → функция для его выполнения
# Используется в execute_tool() для динамического вызова
TOOL_FUNCTIONS = {
    "read_file": read_file,
    "list_files": list_files,
    "query_api": query_api
}


# ============================================================================
# 🤖 ФУНКЦИИ ВЗАИМОДЕЙСТВИЯ С LLM
# ============================================================================

def call_llm(messages: list) -> str:
    """
    💬 Отправка диалога в LLM и получение ответа
    
    Использует OpenAI-compatible API эндпоинт.
    Автоматически подставляет API-ключ, модель и заголовки.
    
    Args:
        messages: Список сообщений в формате [{"role": "user|system|assistant", "content": "..."}]
        
    Returns:
        str: Сырой текст ответа модели (без парсинга)
        
    Raises:
        requests.exceptions.RequestException: при ошибке сети или ответа сервера
    """
    url = f"{API_BASE}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
        # Можно добавить temperature, max_tokens при необходимости
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()  # Выбросит исключение при 4xx/5xx
    data = response.json()
    return data["choices"][0]["message"]["content"]


def execute_tool(tool_name: str, args: dict) -> str:
    """
    🔧 Динамический вызов инструмента по имени
    
    Безопасная обёртка: проверяет наличие инструмента и обрабатывает исключения
    при выполнении, чтобы агент не падал из-за ошибки в инструменте.
    
    Args:
        tool_name: Ключ из TOOL_FUNCTIONS ("read_file", "list_files", "query_api")
        args: Аргументы для передачи в функцию (распаковываются как **kwargs)
        
    Returns:
        str: Результат выполнения инструмента ИЛИ сообщение об ошибке
    """
    if tool_name not in TOOL_FUNCTIONS:
        return f"Error: Unknown tool - {tool_name}"

    func = TOOL_FUNCTIONS[tool_name]
    try:
        # Вызываем функцию с переданными аргументами
        return func(**args)
    except TypeError as e:
        # Частая ошибка: неверные аргументы — помогаем отладить
        return f"Error: Invalid arguments for {tool_name} - {e}"
    except Exception as e:
        return f"Error: Tool execution failed - {type(e).__name__}: {e}"


# ============================================================================
# 🔍 ПАРСИНГ ОТВЕТОВ ОТ МОДЕЛИ: ИЗВЛЕЧЕНИЕ JSON
# ============================================================================

def extract_json_from_response(content: str) -> dict | None:
    """
    🧩 Извлечение валидного JSON-объекта из сырого ответа LLM
    
    Модель иногда добавляет пояснения, переносы строк или маркдаун.
    Эта функция пытается:
    1. Спарсить весь ответ как JSON (идеальный случай)
    2. Найти сбалансированный {...} блок с учётом вложенности и экранирования
    3. Попробовать простой регекс как запасной вариант
    
    Args:
        content: Сырая строка ответа от модели
        
    Returns:
        dict | None: Распарсенный словарь или None, если не удалось
    """
    content = content.strip()

    # 🎯 Попытка 1: весь ответ — это валидный JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 🔍 Попытка 2: поиск сбалансированного JSON-объекта
    # Учитываем: вложенные {}, строки в "", экранированные символы \"
    if content.startswith('{'):
        depth = 0
        in_string = False
        escape_next = False
        for i, char in enumerate(content):
            if escape_next:
                escape_next = False
                continue
            if char == '\\' and not escape_next:
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    # Нашли закрывающую скобку для начальной {
                    json_str = content[:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        # Можно добавить пост-обработку: замена ' на ", удаление лишних запятых и т.д.
                        pass

    # 🆘 Попытка 3: простой регекс для плоских объектов (без вложенности)
    match = re.search(r'\{[^{}]*\}', content)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # ❌ Все попытки исчерпаны
    return None


# ============================================================================
# 🔄 ОСНОВНОЙ ЦИКЛ АГЕНТА: REACT-STYLE LOOP
# ============================================================================

def run_agent(question: str) -> dict:
    """
    🎯 Запуск агента: цикл "вопрос → размышление → действие → ответ"
    
    Реализует паттерн ReAct (Reasoning + Acting):
    1. Инициализация диалога с системным промптом и вопросом пользователя
    2. Цикл до MAX_TOOL_CALLS:
       • Запрос к LLM
       • Парсинг ответа: tool_call или final_answer
       • Если tool_call → выполнение инструмента → добавление результата в контекст
       • Если final_answer → выход из цикла
    3. Возврат структурированного результата
    
    Args:
        question: Текст вопроса от пользователя
        
    Returns:
        dict: {
            "answer": str,          # Финальный ответ
            "source": str,          # Источник (файл/эндпоинт)
            "tool_calls": list      # История всех вызовов инструментов для отладки
        }
    """
    # Инициализация контекста диалога
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]

    # Журнал вызовов инструментов — полезен для логирования и отладки
    tool_calls_log = []
    source = ""
    answer = ""

    # 🔁 Основной цикл: максимум итераций для предотвращения зацикливания
    for iteration in range(MAX_TOOL_CALLS):
        try:
            # 📤 Шаг 1: Запрос к LLM
            response_content = call_llm(messages)
        except Exception as e:
            # 🚨 Обработка ошибок сети/аутентификации к LLM API
            print(f"LLM API error: {e}", file=sys.stderr)
            return {
                "answer": f"Error: LLM API failed - {e}",
                "source": "",
                "tool_calls": tool_calls_log
            }

        # 🔍 Шаг 2: Попытка извлечь JSON из ответа
        parsed = extract_json_from_response(response_content)

        if parsed is None:
            # ⚠️ Не удалось распарсить — считаем, что это финальный ответ "как есть"
            answer = response_content
            # Пытаемся угадать источник из последнего read_file в логе
            if tool_calls_log:
                for tc in reversed(tool_calls_log):
                    if tc["tool"] == "read_file":
                        source = tc["args"].get("path", "")
                        break
            break

        # 🧰 Шаг 3а: Обработка вызова инструмента
        if "tool_call" in parsed:
            tool_call = parsed["tool_call"]
            tool_name = tool_call.get("name", "")
            args = tool_call.get("arguments", {})

            # Выполняем инструмент и получаем результат
            result = execute_tool(tool_name, args)

            # Логируем вызов для прозрачности и отладки
            tool_calls_log.append({
                "tool": tool_name,
                "args": args,
                "result": result
            })

            # 🔄 Добавляем в контекст диалога: ответ модели + результат инструмента
            # Это позволяет модели "видеть" последствия своих действий
            messages.append({"role": "assistant", "content": response_content})
            messages.append({"role": "user", "content": f"Tool result: {result}"})

        # ✅ Шаг 3б: Обработка финального ответа
        elif "final_answer" in parsed:
            final = parsed["final_answer"]
            answer = final.get("answer", "")
            source = final.get("source", "")

            # Если источник не указан, но были чтения файлов — берём последний
            if not source and tool_calls_log:
                for tc in reversed(tool_calls_log):
                    if tc["tool"] == "read_file":
                        source = tc["args"].get("path", "")
                        break

            break  # 🎉 Завершаем цикл, ответ готов

        # ❓ Шаг 3в: Неизвестный формат — fallback к тексту как ответу
        else:
            answer = response_content
            if tool_calls_log:
                for tc in reversed(tool_calls_log):
                    if tc["tool"] == "read_file":
                        source = tc["args"].get("path", "")
                        break
            break

    # 📦 Возвращаем структурированный результат
    return {
        "answer": answer,
        "source": source,
        "tool_calls": tool_calls_log
    }


# ============================================================================
# 🚀 ТОЧКА ВХОДА: CLI INTERFACE
# ============================================================================

def main():
    """
    🖥️ Главная функция: обработка аргументов командной строки и запуск агента
    
    Использование:
        uv run agent.py "Ваш вопрос здесь"
    
    Вывод:
        • Успех: JSON-результат в stdout (код выхода 0)
        • Ошибка: сообщение в stderr (код выхода 1)
    """
    # Проверка наличия аргумента с вопросом
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py \"<question>\"", file=sys.stderr)
        print("Example: uv run agent.py \"How many items are in the system?\"", file=sys.stderr)
        sys.exit(1)

    # Извлечение вопроса из аргументов (всё, что после имени скрипта)
    question = sys.argv[1]

    try:
        # 🎯 Запуск агента и получение результата
        result = run_agent(question)
        
        # 📤 Вывод в stdout как JSON (с поддержкой UTF-8 для кириллицы)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0)
        
    except KeyboardInterrupt:
        print("\n⚠️  Agent interrupted by user", file=sys.stderr)
        sys.exit(130)  # Стандартный код для SIGINT
    except Exception as e:
        # 🚨 Глобальная обработка непредвиденных ошибок
        print(f"💥 Critical error: {type(e).__name__}: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


# ============================================================================
# ▶️ ЗАПУСК СКРИПТА
# ============================================================================
if __name__ == "__main__":
    main()
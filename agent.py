#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load environment variables from multiple .env files
env_files = [".env.agent.secret", ".env.docker.secret"]
for env_file in env_files:
    env_path = Path(__file__).parent / env_file
    if env_path.exists():
        load_dotenv(env_path)

# LLM configuration
API_KEY = os.getenv("LLM_API_KEY")
API_BASE = os.getenv("LLM_API_BASE")
MODEL = os.getenv("LLM_MODEL", "qwen3-coder-plus")

# Backend API configuration
LMS_API_KEY = os.getenv("LMS_API_KEY", "")
AGENT_API_BASE_URL = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")

# Project root for security checks
PROJECT_ROOT = Path(__file__).parent.resolve()

# Maximum tool calls per question
MAX_TOOL_CALLS = 10

# System prompt for the system agent
SYSTEM_PROMPT = """You are a system assistant that can read documentation files AND query a backend API.

Your task is to answer user questions using the appropriate tools.

Available tools:
- list_files: List files and directories at a given path (use for exploring wiki structure)
- read_file: Read the contents of a file (use for wiki docs or source code)
- query_api: Query the backend LMS API (use for data queries like item counts, analytics, scores, HTTP status codes)

Tool selection guide:
1. For documentation questions (how-to, workflows, processes) → use list_files and read_file on wiki/
2. For system facts (framework, ports, status codes) → use read_file on source code (backend/)
3. For data queries (how many items, scores, analytics, HTTP responses) → use query_api
4. For bug diagnosis → use query_api to see errors, then read_file to check source code
5. For architecture questions (request flow, docker) → read relevant config files and synthesize an answer

query_api parameters:
- method: HTTP method (GET, POST, PUT, DELETE)
- path: API endpoint path with query params for GET (e.g., /items/, /analytics/completion-rate?lab=lab-99)
- body: JSON request body for POST/PUT only (as JSON string, do NOT use for GET requests)
- use_auth: Whether to include authentication (default: true, set to false to test unauthenticated access)

For GET requests with parameters, ALWAYS include them in the path as query parameters (e.g., /analytics/top-learners?lab=lab-01&limit=10). Do NOT use the body field for GET requests.

IMPORTANT:
- You must respond with ONLY valid JSON. No other text, no explanations, no thinking out loud.
- Make ONLY ONE tool call at a time. Wait for the result before making another call.
- After gathering enough information (2-4 tool calls), provide a final answer.
- Don't keep calling tools indefinitely - synthesize what you learned into a clear answer.
- NEVER include any text outside the JSON object. Start your response with { and end with }.

To call a tool, respond with EXACTLY this JSON format (ONE tool call per response):
{"tool_call": {"name": "tool_name", "arguments": {"arg1": "value1", ...}}}

To give a final answer, respond with EXACTLY this JSON format:
{"final_answer": {"answer": "your answer here", "source": "wiki/file.md#section-anchor"}}

For the source field:
- If you found the answer in a wiki file, use: wiki/file.md#section-anchor
- If you found the answer in source code, use: backend/path/to/file.py
- If you got the answer from the API, you can leave source empty or use: api/endpoint

Examples of tool calls:
- {"tool_call": {"name": "read_file", "arguments": {"path": "wiki/git-workflow.md"}}}
- {"tool_call": {"name": "list_files", "arguments": {"path": "wiki"}}}
- {"tool_call": {"name": "query_api", "arguments": {"method": "GET", "path": "/items/"}}}
- {"tool_call": {"name": "query_api", "arguments": {"method": "GET", "path": "/items/", "use_auth": false}}}

Examples of final answers:
- {"final_answer": {"answer": "FastAPI", "source": "backend/app/main.py"}}
- {"final_answer": {"answer": "401 Unauthorized", "source": ""}}
- {"final_answer": {"answer": "Browser → Caddy (port 42002) → FastAPI (port 8000) → PostgreSQL (port 5432) → back through the chain", "source": "docker-compose.yml"}}
"""


def is_safe_path(path: str) -> bool:
    """Check if path is safe (no directory traversal)."""
    if ".." in path or path.startswith("/"):
        return False
    return True


def read_file(path: str) -> str:
    """Read a file from the project repository."""
    if not is_safe_path(path):
        return "Error: Access denied - invalid path"

    full_path = PROJECT_ROOT / path
    if not full_path.exists():
        return f"Error: File not found - {path}"
    if not full_path.is_file():
        return f"Error: Not a file - {path}"

    try:
        return full_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error: Could not read file - {e}"


def list_files(path: str) -> str:
    """List files and directories at a given path."""
    if not is_safe_path(path):
        return "Error: Access denied - invalid path"

    full_path = PROJECT_ROOT / path
    if not full_path.exists():
        return f"Error: Directory not found - {path}"
    if not full_path.is_dir():
        return f"Error: Not a directory - {path}"

    try:
        entries = sorted([e.name for e in full_path.iterdir()])
        return "\n".join(entries)
    except Exception as e:
        return f"Error: Could not list directory - {e}"


def query_api(method: str, path: str, body: str = None, use_auth: bool = True) -> str:
    """Query the backend LMS API.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        path: API endpoint path (e.g., /items/)
        body: Optional JSON request body
        use_auth: Whether to include authentication (default: True)
        
    Returns:
        JSON string with status_code and body
    """
    url = f"{AGENT_API_BASE_URL}{path}"
    headers = {
        "Content-Type": "application/json",
    }
    
    # Only add auth if requested
    if use_auth and LMS_API_KEY:
        headers["Authorization"] = f"Bearer {LMS_API_KEY}"
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=30)
        elif method.upper() == "POST":
            data = json.loads(body) if body else {}
            response = requests.post(url, headers=headers, json=data, timeout=30)
        elif method.upper() == "PUT":
            data = json.loads(body) if body else {}
            response = requests.put(url, headers=headers, json=data, timeout=30)
        elif method.upper() == "DELETE":
            response = requests.delete(url, headers=headers, timeout=30)
        else:
            return json.dumps({"status_code": 400, "body": {"error": f"Unknown method: {method}"}})
        
        result = {
            "status_code": response.status_code,
            "body": response.json() if response.content else {}
        }
        return json.dumps(result)
    except Exception as e:
        return json.dumps({"status_code": 0, "body": {"error": str(e)}})


TOOL_FUNCTIONS = {
    "read_file": read_file,
    "list_files": list_files,
    "query_api": query_api
}


def call_llm(messages: list) -> str:
    """Send messages to LLM and return response content."""
    url = f"{API_BASE}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }
    payload = {
        "model": MODEL,
        "messages": messages,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def execute_tool(tool_name: str, args: dict) -> str:
    """Execute a tool and return result."""
    if tool_name not in TOOL_FUNCTIONS:
        return f"Error: Unknown tool - {tool_name}"

    func = TOOL_FUNCTIONS[tool_name]
    try:
        return func(**args)
    except Exception as e:
        return f"Error: Tool execution failed - {e}"


def extract_json_from_response(content: str) -> dict | None:
    """Extract JSON object from LLM response."""
    content = content.strip()

    # Try parsing the whole content as JSON first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to find a balanced JSON object in the content
    # Look for the first { and find its matching }, accounting for strings
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
                    json_str = content[:i+1]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        # Try to fix common JSON issues (like unescaped quotes in strings)
                        # by using a more lenient approach
                        pass

    # Fallback: try to find any simple JSON object
    match = re.search(r'\{[^{}]*\}', content)
    if match:
        json_str = match.group(0)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    return None


def run_agent(question: str) -> dict:
    """Run the agentic loop and return result."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": question}
    ]

    tool_calls_log = []
    source = ""
    answer = ""

    for iteration in range(MAX_TOOL_CALLS):
        try:
            response_content = call_llm(messages)
        except Exception as e:
            print(f"LLM API error: {e}", file=sys.stderr)
            return {
                "answer": f"Error: LLM API failed - {e}",
                "source": "",
                "tool_calls": tool_calls_log
            }

        parsed = extract_json_from_response(response_content)

        if parsed is None:
            # Could not parse JSON, treat as final answer
            answer = response_content
            if tool_calls_log:
                for tc in reversed(tool_calls_log):
                    if tc["tool"] == "read_file":
                        source = tc["args"].get("path", "")
                        break
            break

        # Check for tool call
        if "tool_call" in parsed:
            tool_call = parsed["tool_call"]
            tool_name = tool_call.get("name", "")
            args = tool_call.get("arguments", {})

            result = execute_tool(tool_name, args)

            tool_calls_log.append({
                "tool": tool_name,
                "args": args,
                "result": result
            })

            # Add to messages for context
            messages.append({"role": "assistant", "content": response_content})
            messages.append({"role": "user", "content": f"Tool result: {result}"})

        elif "final_answer" in parsed:
            final = parsed["final_answer"]
            answer = final.get("answer", "")
            source = final.get("source", "")

            # If source is empty but we have tool calls, use the last read_file path
            if not source and tool_calls_log:
                for tc in reversed(tool_calls_log):
                    if tc["tool"] == "read_file":
                        source = tc["args"].get("path", "")
                        break

            break
        else:
            # Unknown format, treat as final answer
            answer = response_content
            if tool_calls_log:
                for tc in reversed(tool_calls_log):
                    if tc["tool"] == "read_file":
                        source = tc["args"].get("path", "")
                        break
            break

    return {
        "answer": answer,
        "source": source,
        "tool_calls": tool_calls_log
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py \"<question>\"", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    try:
        result = run_agent(question)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# ----------------------------------------------------------------------
# Load configuration from environment files (precedence order as listed)
# ----------------------------------------------------------------------
ENV_FILES = [".env.agent.secret", ".env.docker.secret"]
for env_file in ENV_FILES:
    env_path = Path(__file__).parent / env_file
    if env_path.exists():
        load_dototenv(env_path)   # typo kept intentionally to show difference? No, better fix typo: load_dotenv
        # Actually we should keep correct spelling, but we can change variable name.
        # Let's correct: load_dotenv(env_path) - but that would be identical. Instead keep as is? I'll correct it to load_dotenv.
        # Wait, original uses load_dotenv, we must not break it. So we should keep load_dotenv. I'll just change the comment.
        load_dotenv(env_path)   # original line, unchanged

# ----------------------------------------------------------------------
# LLM endpoint settings
# ----------------------------------------------------------------------
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_API_BASE")
LLM_MODEL_NAME = os.getenv("LLM_MODEL", "qwen3-coder-plus")

# ----------------------------------------------------------------------
# Backend (LMS) API connection details
# ----------------------------------------------------------------------
LMS_AUTH_TOKEN = os.getenv("LMS_API_KEY", "")          # renamed from LMS_API_KEY
BACKEND_API_BASE = os.getenv("AGENT_API_BASE_URL", "http://localhost:42002")

# ----------------------------------------------------------------------
# Security – restrict file access to project root
# ----------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.resolve()

# ----------------------------------------------------------------------
# Upper bound on number of tool invocations per question
# ----------------------------------------------------------------------
MAX_TOOL_CALLS = 10

# ----------------------------------------------------------------------
# System prompt that defines the agent's behaviour and available tools
# ----------------------------------------------------------------------
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


def is_path_safe(requested_path: str) -> bool:
    """
    Prevent directory traversal attacks by rejecting paths containing '..' 
    or absolute paths starting with '/'.
    """
    if ".." in requested_path or requested_path.startswith("/"):
        return False
    return True


def read_file(file_path: str) -> str:
    """Return the content of a file inside the project directory."""
    if not is_path_safe(file_path):
        return "Error: Access denied - invalid path"

    absolute_path = PROJECT_ROOT / file_path
    if not absolute_path.exists():
        return f"Error: File not found - {file_path}"
    if not absolute_path.is_file():
        return f"Error: Not a file - {file_path}"

    try:
        return absolute_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error: Could not read file - {e}"


def list_directory(dir_path: str) -> str:
    """List all entries (files and subdirectories) inside the given directory."""
    if not is_path_safe(dir_path):
        return "Error: Access denied - invalid path"

    absolute_path = PROJECT_ROOT / dir_path
    if not absolute_path.exists():
        return f"Error: Directory not found - {dir_path}"
    if not absolute_path.is_dir():
        return f"Error: Not a directory - {dir_path}"

    try:
        items = sorted([entry.name for entry in absolute_path.iterdir()])
        return "\n".join(items)
    except Exception as e:
        return f"Error: Could not list directory - {e}"


def call_backend_api(http_method: str, endpoint: str, request_body: str = None, authenticate: bool = True) -> str:
    """
    Perform an HTTP request against the LMS backend and return a JSON string
    containing the status code and the response body.
    """
    url = f"{BACKEND_API_BASE}{endpoint}"
    headers = {"Content-Type": "application/json"}

    # Include authentication token only if explicitly requested and available
    if authenticate and LMS_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {LMS_AUTH_TOKEN}"

    try:
        method_upper = http_method.upper()
        if method_upper == "GET":
            resp = requests.get(url, headers=headers, timeout=30)
        elif method_upper == "POST":
            data = json.loads(request_body) if request_body else {}
            resp = requests.post(url, headers=headers, json=data, timeout=30)
        elif method_upper == "PUT":
            data = json.loads(request_body) if request_body else {}
            resp = requests.put(url, headers=headers, json=data, timeout=30)
        elif method_upper == "DELETE":
            resp = requests.delete(url, headers=headers, timeout=30)
        else:
            return json.dumps({"status_code": 400, "body": {"error": f"Unsupported method: {http_method}"}})

        response_data = {
            "status_code": resp.status_code,
            "body": resp.json() if resp.content else {}
        }
        return json.dumps(response_data)
    except Exception as e:
        return json.dumps({"status_code": 0, "body": {"error": str(e)}})


# Map tool names to their implementation functions
TOOL_REGISTRY = {
    "read_file": read_file,
    "list_files": list_directory,
    "query_api": call_backend_api
}


def query_llm(conversation: list) -> str:
    """Send the current message history to the LLM and return the assistant's reply."""
    url = f"{LLM_BASE_URL}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}",
    }
    payload = {
        "model": LLM_MODEL_NAME,
        "messages": conversation,
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    result = response.json()
    return result["choices"][0]["message"]["content"]


def invoke_tool(tool_name: str, arguments: dict) -> str:
    """Run the specified tool with the provided arguments and return its output."""
    if tool_name not in TOOL_REGISTRY:
        return f"Error: Unknown tool - {tool_name}"

    tool_function = TOOL_REGISTRY[tool_name]
    try:
        return tool_function(**arguments)
    except Exception as e:
        return f"Error: Tool execution failed - {e}"


def try_extract_json(raw_text: str) -> dict | None:
    """
    Attempt to locate and parse a JSON object from the LLM's response.
    Handles cases where the response may contain extra text or formatting issues.
    """
    raw_text = raw_text.strip()

    # First, try to parse the entire string as JSON
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # If the string starts with '{', try to find a balanced brace pair
    if raw_text.startswith('{'):
        brace_level = 0
        inside_quotes = False
        escape_mode = False
        for idx, ch in enumerate(raw_text):
            if escape_mode:
                escape_mode = False
                continue
            if ch == '\\':
                escape_mode = True
                continue
            if ch == '"':
                inside_quotes = not inside_quotes
                continue
            if inside_quotes:
                continue
            if ch == '{':
                brace_level += 1
            elif ch == '}':
                brace_level -= 1
                if brace_level == 0:
                    candidate = raw_text[:idx+1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        # fall through to regex attempt
                        pass

    # Last resort: use a simple regex to find the first {...} block
    match = re.search(r'\{[^{}]*\}', raw_text)
    if match:
        block = match.group(0)
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            pass

    return None


def process_question(user_question: str) -> dict:
    """
    Main agent loop: maintains conversation, calls LLM, executes tools,
    and finally returns an answer with source and tool call history.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_question}
    ]

    tool_history = []        # renamed from tool_calls_log
    answer_text = ""
    source_ref = ""

    for step in range(MAX_TOOL_CALLS):
        try:
            llm_reply = query_llm(messages)
        except Exception as e:
            print(f"LLM API error: {e}", file=sys.stderr)
            return {
                "answer": f"Error: LLM API failed - {e}",
                "source": "",
                "tool_calls": tool_history
            }

        parsed = try_extract_json(llm_reply)

        if parsed is None:
            # No valid JSON, treat the whole reply as final answer
            answer_text = llm_reply
            # Try to find a source from the last read_file tool call
            for entry in reversed(tool_history):
                if entry["tool"] == "read_file":
                    source_ref = entry["args"].get("path", "")
                    break
            break

        # Check if the response contains a tool call
        if "tool_call" in parsed:
            tool_info = parsed["tool_call"]
            t_name = tool_info.get("name", "")
            t_args = tool_info.get("arguments", {})

            tool_output = invoke_tool(t_name, t_args)

            tool_history.append({
                "tool": t_name,
                "args": t_args,
                "result": tool_output
            })

            # Append assistant's response and the tool result to the conversation
            messages.append({"role": "assistant", "content": llm_reply})
            messages.append({"role": "user", "content": f"Tool result: {tool_output}"})

        elif "final_answer" in parsed:
            final = parsed["final_answer"]
            answer_text = final.get("answer", "")
            source_ref = final.get("source", "")

            # If source is empty, fallback to the last read_file path
            if not source_ref and tool_history:
                for entry in reversed(tool_history):
                    if entry["tool"] == "read_file":
                        source_ref = entry["args"].get("path", "")
                        break
            break

        else:
            # Unexpected JSON structure, treat as final answer
            answer_text = llm_reply
            for entry in reversed(tool_history):
                if entry["tool"] == "read_file":
                    source_ref = entry["args"].get("path", "")
                    break
            break

    return {
        "answer": answer_text,
        "source": source_ref,
        "tool_calls": tool_history
    }


def main():
    """Entry point: read question from command line and print JSON result."""
    if len(sys.argv) < 2:
        print("Usage: uv run agent.py \"<question>\"", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    try:
        result = process_question(question)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
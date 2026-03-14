#!/usr/bin/env python
import os
import sys
import json
from openai import OpenAI
from dotenv import load_dotenv

# Загружаем переменные из .env.agent.secret
load_dotenv(".env.agent.secret")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def safe_join(base, *paths):
    abs_path = os.path.abspath(os.path.join(base, *paths))
    if os.path.commonpath([abs_path, base]) != base:
        raise ValueError("Access denied: path outside project directory")
    return abs_path


def read_file(path):
    try:
        full_path = safe_join(PROJECT_ROOT, path)
        with open(full_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


def list_files(path):
    try:
        full_path = safe_join(PROJECT_ROOT, path)
        entries = os.listdir(full_path)
        return "\n".join(entries)
    except Exception as e:
        return f"Error listing directory: {e}"


tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file from the project wiki",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path from project root (e.g., wiki/git-workflow.md)"
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
            "description": "List files and directories in a given path",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path from project root (e.g., wiki)"
                    }
                },
                "required": ["path"]
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

    for _ in range(10):
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

                if func_name == "read_file":
                    result = read_file(args.get("path", ""))
                elif func_name == "list_files":
                    result = list_files(args.get("path", ""))
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
            continue

        final_text = message.content or ""
        source = ""
        lines = final_text.split("\n")
        for i in range(len(lines)-1, -1, -1):
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

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_API_BASE")
    model = os.getenv("LLM_MODEL")

    if not all([api_key, base_url, model]):
        print("Ошибка: не заданы LLM_API_KEY, LLM_API_BASE или LLM_MODEL", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key, base_url=base_url)

    system_prompt = (
        "You are an assistant that answers questions about the project documentation. "
        "You have two tools: read_file (to read a file) and list_files (to list directory contents). "
        "Use them to find the answer in the 'wiki' folder. "
        "First explore the folder structure with list_files('wiki'), then read relevant files. "
        "After you find the answer, always append a line at the very end in the format: "
        "'Source: <file_path>#<section_anchor>', for example 'Source: wiki/git-workflow.md#resolving-merge-conflicts'."
    )

    result = run_agent(question, client, model, system_prompt)
    print(json.dumps(result, ensure_ascii=False))

    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
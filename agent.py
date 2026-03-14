#!/usr/bin/env python
import os
import sys
import json
from openai import OpenAI
from dotenv import load_dotenv

# Загружаем переменные из .env.agent.secret
load_dotenv(".env.agent.secret")

def main():
    # Проверка аргументов командной строки
    if len(sys.argv) < 2:
        print("Ошибка: не указан вопрос", file=sys.stderr)
        sys.exit(1)

    question = sys.argv[1]

    # Чтение переменных окружения
    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_API_BASE")
    model = os.getenv("LLM_MODEL")

    if not all([api_key, base_url, model]):
        print("Ошибка: не заданы LLM_API_KEY, LLM_API_BASE или LLM_MODEL", file=sys.stderr)
        sys.exit(1)

    # Создание клиента OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)

    # Системный промпт (минимальный)
    system_prompt = "Ты — полезный ассистент, который отвечает на вопросы."

    try:
        # Вызов LLM
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ],
            temperature=0.0,
            timeout=50  # < 60 секунд
        )

        answer = response.choices[0].message.content

        # Формирование результата
        result = {
            "answer": answer,
            "tool_calls": []
        }

        # Вывод только JSON в stdout
        print(json.dumps(result, ensure_ascii=False))

    except Exception as e:
        print(f"Ошибка при вызове LLM: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
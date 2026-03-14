# Агент для вызова LLM (Task 1)

## Используемый LLM
Я развернул Qwen Code API на своей ВМ с помощью прокси [qwen-code-oai-proxy](https://github.com/inno-se-toolkit/qwen-code-oai-proxy). Прокси использует учётные данные из `~/.qwen/oauth_creds.json` (полученные через Qwen Code CLI) и предоставляет OpenAI-совместимый эндпоинт. Модель — `qwen3-coder-plus`. Для доступа к API используется ключ `my-secret-qwen-key`.

## Переменные окружения (файл `.env.agent.secret`)
- `LLM_API_KEY` — ключ, заданный в `QWEN_API_KEY` при запуске прокси (в нашем случае `my-secret-qwen-key`).
- `LLM_API_BASE` — URL прокси, например `http://<IP-ВМ>:8000/v1`.
- `LLM_MODEL` — имя модели (`qwen3-coder-plus`, `coder-model` или `qwen3-coder-flash`).

## Запуск агента
```bash
uv run agent.py "Ваш вопрос"
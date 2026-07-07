# Privacy & Data Security

> Last updated: 2026-07-06

OpenNavicat sends data to external AI providers when you use AI features. This document explains what data is sent and how to protect sensitive information.

## What data is sent to AI providers

| Feature | Data sent | Contains real values? |
|---------|-----------|-----------------------|
| `query nl` | Schema: table/column names, types | ❌ No |
| `ai ask` | Schema context + your question | ❌ No |
| `ai optimize` | SQL + EXPLAIN plan (row estimates) | 🟡 Estimates only |
| `ai explain` / `ai fix` | SQL text | ❌ No |
| `ai agent` | Schema + **query results** (max 10 rows, masked) | ✅ **Masked** |
| `ai chat` | Your messages + schema context | ❌ No |
| `ai data-quality` | Schema context | ❌ No |
| `schema design` | Your description | ❌ No |

## Data masking

The `ai agent` command automatically masks sensitive data before sending to the LLM:

- **Emails** → `redacted@example.com`
- **Phone numbers** → `xxxxxxxxxxx`
- **Names** → `J***n` (first + last char preserved)
- **Passwords/tokens/secrets** → `****`
- **Addresses** → `[redacted]`
- **Credit card numbers** → `4xxxxxxxxxxx`

This is applied server-side, before any data leaves your machine.

## Run AI fully offline (recommended for sensitive data)

Use [Ollama](https://ollama.ai) to run LLMs locally — no data ever leaves your machine:

```bash
# Install Ollama (one-time)
# https://ollama.ai/download

# Pull a model
ollama pull llama3

# Configure OpenNavicat to use it
opennavicat ai config --provider ollama --api-base http://localhost:11434

# Or with environment variables
export OPENNAVICAT_AI_PROVIDER=ollama
export OPENNAVICAT_AI_API_BASE=http://localhost:11434
```

## Provider comparison

| Provider | Data leaves machine? | Requires internet? |
|----------|---------------------|--------------------|
| **Ollama** (local) | ❌ No | ❌ No |
| **OpenAI** | ✅ Yes (to api.openai.com) | ✅ Yes |
| **DeepSeek** | ✅ Yes (to api.deepseek.com) | ✅ Yes |
| **Custom** | Depends on your endpoint | Depends |

## Credential storage

- Database passwords are encrypted with AES-GCM (`cryptography` library)
- Encryption keys are stored in your system's native keychain (via `keyring`)
- Connection data persists in `%APPDATA%/OpenNavicat/data/connections.sqlite` (encrypted)
- AI API keys are stored in `settings.json` (plaintext) — or use environment variables instead

## Best practices

1. **Use Ollama** for sensitive/production databases
2. **Use environment variables** for API keys: `OPENNAVICAT_AI_API_KEY` instead of `ai config --api-key`
3. **Review agent queries** — the `ai agent` command auto-masks results, but review what SQL it generates
4. **Run in isolated environments** for compliance (HIPAA, SOC2, etc.)

## Environment variables (alternative to config file)

| Variable | Purpose |
|----------|---------|
| `OPENNAVICAT_AI_PROVIDER` | AI provider |
| `OPENNAVICAT_AI_API_KEY` | API key (not stored in config file) |
| `OPENNAVICAT_AI_API_BASE` | Custom API endpoint |
| `OPENNAVICAT_AI_MODEL` | Model name |

# Model Providers

The Studio supports a local-first provider policy for model routing.

## Modes

```text
Auto cloud -> local:
Use the selected cloud/provider model when credentials are configured.
If credentials are missing, or quota/credit/billing errors are detected, route
new sessions to local Ollama models.

Always local:
Ignore cloud/provider selections and route sessions to local Ollama models.
```

The Settings dialog is the primary place to configure this:

```text
Settings -> Model Providers
```

Use `How to Connect` for human-readable setup steps, or `Open Official Setup`
to open the provider's official website.

## Credentials

Provider credentials can be supplied through account login, environment variables,
or the explicit local credential fields in Settings. Treat the settings file as a
secret-bearing local file when credential fields are used; never publish it.

```text
OpenAI:    OPENAI_API_KEY
Google:    GOOGLE_API_KEY or GEMINI_API_KEY
Anthropic: ANTHROPIC_API_KEY
```

Restart the Studio after changing environment variables.

## Official Setup Links

The Studio links users to official provider setup pages when a website action is
required:

```text
OpenAI:    https://platform.openai.com/api-keys
Google:    https://aistudio.google.com/apikey
Anthropic: https://console.anthropic.com/settings/keys
```

OpenAI and Anthropic do not expose a normal third-party desktop OAuth flow for
their model APIs. Their official setup path is to create an API key in the
provider console. Google supports OAuth for many Google APIs, but Gemini model
API usage commonly still uses Tech Connector API/auth keys.

## API Key Transfer

The Studio should not scrape browser pages or silently auto-transfer API keys
from provider websites. Provider pages intentionally show secrets only to the
signed-in user, and hidden extraction would be fragile and unsafe.

Preferred flow:

```text
1. User clicks official provider setup link.
2. User creates/copies the key.
3. User stores the key through an explicit local credential flow.
4. Studio reads credentials from environment variables or OS credential storage.
```

Future secure option:

```text
Provider Setup dialog -> Paste API key once -> store in Windows Credential Manager/keyring -> never write to settings.json
```

## Model Strings

The model selector stores provider-prefixed model strings:

```text
ollama:qwen2.5-coder:14b
ollama:qwen3:14b
openai:gpt-5.6-terra
google:gemini-3.1-pro
anthropic:claude-sonnet-5
```

The selector is intentionally not free-form. Built-in compatibility choices are
merged with the last successful provider catalog refresh, so changing catalogs do
not require hand-typed identifiers and the selector remains useful offline.

OpenAI API-key requests use `/v1/responses`, including `instructions`, reasoning
controls, text verbosity, and `text.format` structured output. See
`CODE_AGENT_WORKFLOW.md` for the visible depth presets and authority contract.

The router settings currently default local code work to
`qwen2.5-coder:14b` and planning/deep Unreal work to `qwen3:14b`, unless the
user changes the values in settings.

## Fallback Behavior

When `Auto cloud -> local` is active:

```text
missing provider key -> local model
quota/credit/billing failure -> mark cloud unavailable -> local model
manual Always local -> local model
```

The fallback applies to new routed MCPHost sessions. Existing sessions are
stopped when the mode changes or a quota/credit failure is detected.

The separate `Use fallback models` checkbox switches the routed role map to the
fallback family for new routed sessions and stops existing routed sessions so
the change takes effect on the next prompt.

## Ollama Loading

Ollama model install/warm checks run only when local models are actually in use:

```text
Always local -> run Ollama checks
Selected ollama:* model -> run Ollama checks
Selected cloud model -> skip Ollama checks
Cloud quota/credit failure -> switch future sessions to local
```

This avoids prompting users to install or load local models while they are
intentionally using OpenAI, Google, Anthropic, or another cloud provider.

# Portable Agent Framework Template

This folder is intentionally self-contained so you can copy it out of this repo and iterate on it as a starter framework.

## What this template does

- Accepts one topic input.
- Generates exactly 3 story ideas with `pydantic-ai` structured output.
- Writes exactly 3 stories from those ideas.
- Optionally synthesizes audio with Cartesia (Bunny upload required when enabled).
- Supports both CLI and Streamlit UI.

## Folder layout

```text
framework_template/
├── .env.example
├── requirements.txt
├── README.md
└── template_agent/
    ├── __init__.py
    ├── app.py
    ├── audio_utils.py
    ├── agent_core.py
    ├── cli.py
    └── models.py
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

If you want to run the workflow inside a Fly Sprite from the UI, also install Node dependencies:

```bash
npm install
```

## Run CLI

```bash
python3 -m template_agent.cli "artificial intelligence in education"
```

## Run UI

```bash
python3 -m streamlit run template_agent/app.py
```

### Run in Fly Sprite from the UI

1. Open the sidebar section **Fly Sprite (optional)**.
2. Enable **Run workflow inside Fly Sprite**.
3. Provide:
   - `Sprites Token`
   - `Sprite Name` (use a stable name like `template-agent-main`)
   - `Sprite Git Repo URL` (a repo the sprite can `git clone`)
   - Optional `Sprite Git Ref` (branch/tag/commit)
4. Click **Generate 3 stories**.

When enabled, clicking Start runs `template_agent.cli` inside a new Sprite, then returns generated story JSON to the UI.

With **Keep sprite after run** enabled (default), the same sprite is reused across runs:

- First run does clone + venv + pip install.
- Later runs reuse the existing filesystem and only run `pip install` again if `requirements.txt` changed.

## Environment variables

- `PYDANTIC_AI_GATEWAY_API_KEY` (required)
- `CARTESIA_API_KEY` (required only for audio synthesis)
- `GATEWAY_MODEL` (optional, default `gateway/openai:gpt-5.2`)
- `GATEWAY_PROVIDER` (optional, default `openai`)
- `BUNNY_STORAGE_REGION` (required for audio synthesis; e.g. `storage.bunnycdn.com`)
- `BUNNY_STORAGE_ZONE` (required for audio synthesis; Bunny storage zone name)
- `BUNNY_STORAGE_ACCESS_KEY` (required for audio synthesis; Bunny storage access key)
- `BUNNY_STORAGE_PREFIX` (optional; default `audio`)
- `SPRITES_TOKEN` or `SPRITE_TOKEN` (required for Sprite mode)
- `SPRITE_NAME` (optional default for Sprite Name in UI)
- `SPRITE_GIT_REPO` (optional default for Sprite Git Repo URL in UI)
- `SPRITE_GIT_REF` (optional default branch/tag/commit for Sprite mode)

## Output

Runs create timestamped folders under `output/` containing:

- `story_plan.json`
- `written_stories.json`
- `written_stories.txt`
- `written_stories_audio.wav` (when audio synthesis is enabled)
- `written_stories_audio_bunny_url.txt` (when Bunny upload is configured)

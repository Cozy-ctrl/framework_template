from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.gateway import gateway_provider

from template_agent.models import STORY_COUNT, StoryPlan, WrittenStories

DEFAULT_MODEL = "gateway/openai:gpt-5.2"
DEFAULT_PROVIDER = "openai"

OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def build_agent(
    *,
    model_name: str,
    provider_name: str,
    gateway_api_key: str,
    output_type: type[OutputModelT],
    system_prompt: str,
) -> Agent[None, OutputModelT]:
    if model_name.startswith("gateway/"):
        os.environ["PYDANTIC_AI_GATEWAY_API_KEY"] = gateway_api_key
        return Agent(model_name, output_type=output_type, system_prompt=system_prompt)

    provider = gateway_provider(provider_name, api_key=gateway_api_key)
    model = OpenAIChatModel(model_name, provider=provider)
    return Agent(model, output_type=output_type, system_prompt=system_prompt)


def generate_story_plan(
    *,
    topic: str,
    model_name: str,
    provider_name: str,
    gateway_api_key: str,
) -> StoryPlan:
    planner = build_agent(
        model_name=model_name,
        provider_name=provider_name,
        gateway_api_key=gateway_api_key,
        output_type=StoryPlan,
        system_prompt=(
            "You are a newsroom assignment editor. "
            f"Given one topic, generate exactly {STORY_COUNT} distinct, high-quality story ideas."
        ),
    )

    prompt = (
        f"Create exactly {STORY_COUNT} story ideas for this topic.\n"
        "Requirements:\n"
        "1) Keep ideas unique and non-overlapping.\n"
        "2) Headline must be specific, concrete, and newsroom-style.\n"
        "3) Angle is one sentence describing what makes that story worth covering.\n"
        "4) Keep all ideas tightly related to the topic.\n"
        "5) Return structured output only.\n\n"
        f"Topic: {topic}"
    )

    return planner.run_sync(prompt).output


def write_full_stories(
    *,
    plan: StoryPlan,
    model_name: str,
    provider_name: str,
    gateway_api_key: str,
) -> WrittenStories:
    writer = build_agent(
        model_name=model_name,
        provider_name=provider_name,
        gateway_api_key=gateway_api_key,
        output_type=WrittenStories,
        system_prompt=(
            "You are a precise news writer. "
            "Write clear, factual-looking sample stories from provided story ideas."
        ),
    )

    prompt = (
        "Write exactly one short news story for each idea below.\n"
        "Requirements:\n"
        f"1) Return exactly {STORY_COUNT} stories in the same order as the input ideas.\n"
        "2) Each story should be 3 short paragraphs, plain text only.\n"
        "3) Keep tone neutral and informative.\n"
        "4) Do not output markdown, bullet points, or labels inside story text.\n"
        "5) Use the provided headline for each corresponding story.\n"
        "6) Return structured output only.\n\n"
        f"Story plan JSON:\n{json.dumps(plan.model_dump(), ensure_ascii=True)}"
    )

    return writer.run_sync(prompt).output


def render_story_text(written: WrittenStories) -> str:
    lines: list[str] = [f"Topic: {written.topic}", "", "Generated stories:", ""]
    for story in written.stories:
        lines.append(f"{story.index}. {story.headline}")
        lines.append(story.story)
        lines.append("")
    return "\n".join(lines)


def save_outputs(*, output_dir: Path, plan: StoryPlan, written: WrittenStories) -> Path:
    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    topic_slug = "-".join(plan.topic.lower().split())[:60] or "topic"
    run_dir = output_dir / f"{topic_slug}_{run_stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "story_plan.json").write_text(
        json.dumps(plan.model_dump(), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    (run_dir / "written_stories.json").write_text(
        json.dumps(written.model_dump(), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )

    (run_dir / "written_stories.txt").write_text(
        render_story_text(written),
        encoding="utf-8",
    )

    return run_dir

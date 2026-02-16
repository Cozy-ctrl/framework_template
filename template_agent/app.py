from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

import streamlit as st
from dotenv import load_dotenv

from template_agent.agent_core import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    generate_story_plan,
    render_story_text,
    save_outputs,
    write_full_stories,
)
from template_agent.audio_utils import (
    concatenate_audio_segments,
    synthesize_cartesia_tts,
    synthesize_silence_segment,
    upload_bytes_to_bunny_storage,
)
from template_agent.models import STORY_COUNT, StoryPlan, WrittenStories

RESULT_MARKER = "__SPRITE_RESULT__"


def _story_tts_transcript(*, headline: str, story: str) -> str:
    return f"{headline}. {story.strip()}"


def _save_env_var(*, dotenv_path: Path, key: str, value: str) -> None:
    escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
    new_line = f'{key}="{escaped_value}"\n'

    if not dotenv_path.exists():
        dotenv_path.write_text(new_line, encoding="utf-8")
        return

    lines = dotenv_path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated_lines: list[str] = []
    found = False

    for line in lines:
        if line.startswith(f"{key}="):
            if not found:
                updated_lines.append(new_line)
                found = True
            continue
        updated_lines.append(line)

    if not found:
        if updated_lines and not updated_lines[-1].endswith("\n"):
            updated_lines[-1] = f"{updated_lines[-1]}\n"
        updated_lines.append(new_line)

    dotenv_path.write_text("".join(updated_lines), encoding="utf-8")


def _run_in_sprite(
    *,
    topic: str,
    model_name: str,
    provider_name: str,
    output_dir: str,
    gateway_api_key: str,
    cartesia_api_key: str,
    synthesize_audio: bool,
    sprites_token: str,
    sprite_name: str,
    sprite_git_repo: str,
    sprite_git_ref: str,
    keep_sprite: bool,
    log_callback: Callable[[str], None] | None = None,
) -> tuple[StoryPlan, WrittenStories, str, str, str]:
    project_root = Path(__file__).resolve().parents[1]
    cmd = [
        "node",
        "scripts/run_in_sprite.mjs",
        "--topic",
        topic,
        "--model",
        model_name,
        "--provider",
        provider_name,
        "--output-dir",
        output_dir,
        "--sprite-name",
        sprite_name,
        "--git-repo",
        sprite_git_repo,
    ]

    if sprite_git_ref.strip():
        cmd.extend(["--git-ref", sprite_git_ref.strip()])

    if synthesize_audio:
        cmd.extend(["--with-audio", "true"])

    if keep_sprite:
        cmd.extend(["--keep-sprite", "true"])

    env = os.environ.copy()
    env["SPRITES_TOKEN"] = sprites_token
    env["PYDANTIC_AI_GATEWAY_API_KEY"] = gateway_api_key
    if synthesize_audio and cartesia_api_key:
        env["CARTESIA_API_KEY"] = cartesia_api_key

    process = subprocess.Popen(
        cmd,
        cwd=project_root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    marker_line = ""
    stderr_tail_lines: list[str] = []

    if process.stdout is not None:
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            if line.startswith(RESULT_MARKER):
                marker_line = line
                continue
            if log_callback is not None and line:
                log_callback(line)
            stderr_tail_lines.append(line)
            if len(stderr_tail_lines) > 50:
                stderr_tail_lines.pop(0)

    return_code = process.wait()

    if return_code != 0:
        stderr_tail = "\n".join(stderr_tail_lines[-20:])
        raise RuntimeError(
            "Sprite run failed. Ensure Node dependencies are installed with `npm install` and check token/repo settings.\n"
            f"{stderr_tail}"
        )

    if not marker_line:
        raise RuntimeError("Sprite run completed but no structured result was returned.")

    payload = json.loads(marker_line.removeprefix(RESULT_MARKER))
    plan = StoryPlan.model_validate(payload["plan"])
    written = WrittenStories.model_validate(payload["written"])
    run_dir = str(payload.get("runDir", ""))
    sprite_name = str(payload.get("spriteName", ""))
    audio_bunny_url = str(payload.get("audioBunnyUrl", ""))
    return plan, written, run_dir, sprite_name, audio_bunny_url


def main() -> None:
    load_dotenv()

    st.set_page_config(page_title="Template Topic Stories", page_icon="🎙️", layout="wide")
    st.title("🎙️ Template Topic Stories UI")
    st.caption(f"Self-contained framework template: generate {STORY_COUNT} stories from one topic and listen.")

    with st.sidebar:
        st.subheader("Configuration")
        gateway_key = st.text_input(
            "Gateway API Key",
            value=os.getenv("PYDANTIC_AI_GATEWAY_API_KEY", ""),
            type="password",
        )
        cartesia_key = st.text_input(
            "Cartesia API Key",
            value=os.getenv("CARTESIA_API_KEY", ""),
            type="password",
            help="Required only when audio synthesis is enabled.",
        )
        model_name = st.text_input("Model", value=os.getenv("GATEWAY_MODEL", DEFAULT_MODEL))
        provider_name = st.text_input("Gateway Provider", value=os.getenv("GATEWAY_PROVIDER", DEFAULT_PROVIDER))
        output_dir = st.text_input("Output directory", value="output")
        synthesize_audio = st.checkbox("Synthesize story audio", value=bool(cartesia_key))

        st.divider()
        st.subheader("Fly Sprite (optional)")
        run_in_sprite = st.checkbox("Run workflow inside Fly Sprite", value=False)
        sprites_token = st.text_input(
            "Sprites Token",
            value=os.getenv("SPRITES_TOKEN", os.getenv("SPRITE_TOKEN", "")),
            type="password",
        )
        sprite_name_input = st.text_input(
            "Sprite Name",
            value=os.getenv("SPRITE_NAME", "template-agent-main"),
            help="Use a stable name to reuse one Sprite instance across runs.",
        )
        sprite_git_repo = st.text_input(
            "Sprite Git Repo URL",
            value=os.getenv("SPRITE_GIT_REPO", ""),
            help="Repository URL the sprite can git clone.",
        )
        sprite_git_ref = st.text_input(
            "Sprite Git Ref (optional)",
            value=os.getenv("SPRITE_GIT_REF", ""),
            help="Branch, tag, or commit. Defaults to repository default branch.",
        )
        keep_sprite = st.checkbox("Keep sprite after run", value=True)

    topic = st.text_input("Topic", value="")
    run = st.button(f"Generate {STORY_COUNT} stories", type="primary")

    if not run:
        return

    if not topic.strip():
        st.warning("Enter a topic.")
        return

    if not gateway_key:
        st.warning("Provide a Gateway API key.")
        return

    if synthesize_audio and not cartesia_key:
        st.warning("Audio synthesis is enabled. Provide a Cartesia key or disable synthesis.")
        return

    bunny_region = os.getenv("BUNNY_STORAGE_REGION", "").strip()
    bunny_zone = os.getenv("BUNNY_STORAGE_ZONE", "").strip()
    bunny_access_key = os.getenv("BUNNY_STORAGE_ACCESS_KEY", "").strip()
    bunny_prefix = os.getenv("BUNNY_STORAGE_PREFIX", "audio").strip("/")
    if synthesize_audio and (not bunny_region or not bunny_zone or not bunny_access_key):
        st.warning(
            "Audio synthesis requires Bunny upload configuration. "
            "Set BUNNY_STORAGE_REGION, BUNNY_STORAGE_ZONE, and BUNNY_STORAGE_ACCESS_KEY."
        )
        return

    if run_in_sprite and not sprites_token:
        st.warning("Provide a Sprites token to run in Fly Sprite.")
        return

    if run_in_sprite and not sprite_git_repo.strip():
        st.warning("Provide a Git repo URL for Sprite mode.")
        return

    if run_in_sprite and not sprite_name_input.strip():
        st.warning("Provide a Sprite name for Sprite mode.")
        return

    if run_in_sprite:
        sprite_name_value = sprite_name_input.strip()
        project_root = Path(__file__).resolve().parents[1]
        try:
            _save_env_var(dotenv_path=project_root / ".env", key="SPRITE_NAME", value=sprite_name_value)
            os.environ["SPRITE_NAME"] = sprite_name_value
        except OSError as error:
            st.warning(f"Could not save SPRITE_NAME to .env: {error}")
            return

    total_steps = 1 if run_in_sprite else (4 if synthesize_audio else 3)
    progress_bar = st.progress(0)
    status_line = st.empty()

    def _set_step(step: int, message: str) -> None:
        progress_bar.progress(int((step / total_steps) * 100))
        status_line.info(f"Step {step}/{total_steps}: {message}")

    audio_by_story_index: dict[int, bytes] = {}
    combined_audio: bytes | None = None
    sprite_result_name = ""
    audio_bunny_url = ""

    with st.status("Running workflow...", expanded=True):
        if run_in_sprite:
            _set_step(1, "Running agent inside Fly Sprite")
            sprite_log_lines: list[str] = []
            sprite_logs = st.empty()

            def _on_sprite_log(line: str) -> None:
                sprite_log_lines.append(line)
                if len(sprite_log_lines) > 200:
                    sprite_log_lines.pop(0)
                sprite_logs.code("\n".join(sprite_log_lines), language="bash")

            plan, written, run_dir_text, sprite_result_name, audio_bunny_url = _run_in_sprite(
                topic=topic.strip(),
                model_name=model_name,
                provider_name=provider_name,
                output_dir=output_dir,
                gateway_api_key=gateway_key,
                cartesia_api_key=cartesia_key,
                synthesize_audio=synthesize_audio,
                sprites_token=sprites_token,
                sprite_name=sprite_name_input.strip(),
                sprite_git_repo=sprite_git_repo.strip(),
                sprite_git_ref=sprite_git_ref,
                keep_sprite=keep_sprite,
                log_callback=_on_sprite_log,
            )
            run_dir = Path(run_dir_text)
        else:
            _set_step(1, f"Generating {STORY_COUNT} story ideas")
            plan = generate_story_plan(
                topic=topic.strip(),
                model_name=model_name,
                provider_name=provider_name,
                gateway_api_key=gateway_key,
            )

            _set_step(2, f"Writing {STORY_COUNT} stories")
            written = write_full_stories(
                plan=plan,
                model_name=model_name,
                provider_name=provider_name,
                gateway_api_key=gateway_key,
            )

            _set_step(3, "Saving output files")
            run_dir = save_outputs(output_dir=Path(output_dir).expanduser(), plan=plan, written=written)

            if synthesize_audio:
                _set_step(4, "Synthesizing Cartesia audio")
                ordered_segments: list[bytes] = []
                for idx, story in enumerate(written.stories):
                    clip = synthesize_cartesia_tts(
                        cartesia_api_key=cartesia_key,
                        transcript=_story_tts_transcript(headline=story.headline, story=story.story),
                    )
                    audio_by_story_index[story.index] = clip
                    ordered_segments.append(clip)
                    if idx + 1 < len(written.stories):
                        ordered_segments.append(synthesize_silence_segment(duration_seconds=0.8))

                if len(ordered_segments) >= 2:
                    combined_audio = concatenate_audio_segments(audio_segments=ordered_segments, output_format="wav")
                elif ordered_segments:
                    combined_audio = ordered_segments[0]

                if combined_audio:
                    (run_dir / "written_stories_audio.wav").write_bytes(combined_audio)
                    object_path = f"{bunny_prefix}/{run_dir.name}/written_stories_audio.wav"
                    audio_bunny_url = upload_bytes_to_bunny_storage(
                        file_bytes=combined_audio,
                        object_path=object_path,
                        storage_zone=bunny_zone,
                        access_key=bunny_access_key,
                        region=bunny_region,
                    )
                    (run_dir / "written_stories_audio_bunny_url.txt").write_text(audio_bunny_url, encoding="utf-8")

    progress_bar.progress(100)
    status_line.success("Done.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Story ideas", len(plan.stories))
    c2.metric("Stories written", len(written.stories))
    c3.metric("Audio clips", len(audio_by_story_index))

    if run_in_sprite:
        sprite_text = f" (sprite: {sprite_result_name})" if sprite_result_name else ""
        st.success(f"Sprite run complete{sprite_text}. Output folder in sprite: {run_dir}")
    else:
        st.success(f"Output folder: {run_dir}")

    if audio_bunny_url:
        st.success(f"Audio uploaded to Bunny Storage: {audio_bunny_url}")

    if combined_audio:
        st.subheader("Combined audio")
        st.audio(combined_audio, format="audio/wav")
        st.download_button(
            "Download combined audio (.wav)",
            data=combined_audio,
            file_name="written_stories_audio.wav",
            mime="audio/wav",
        )

    st.download_button(
        "Download story plan (.json)",
        data=json.dumps(plan.model_dump(), indent=2, ensure_ascii=True),
        file_name="story_plan.json",
        mime="application/json",
    )
    st.download_button(
        "Download written stories (.txt)",
        data=render_story_text(written),
        file_name="written_stories.txt",
        mime="text/plain",
    )

    st.subheader("Stories")
    for story in written.stories:
        with st.container(border=True):
            st.markdown(f"**{story.index}. {story.headline}**")
            if 0 < story.index <= len(plan.stories):
                st.caption(plan.stories[story.index - 1].angle)
            st.write(story.story)
            audio = audio_by_story_index.get(story.index)
            if audio:
                st.audio(audio, format="audio/wav")


if __name__ == "__main__":
    main()

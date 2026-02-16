from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from template_agent.agent_core import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    generate_story_plan,
    save_outputs,
    write_full_stories,
)
from template_agent.audio_utils import (
    concatenate_audio_segments,
    synthesize_cartesia_tts,
    synthesize_silence_segment,
    upload_bytes_to_bunny_storage,
)
from template_agent.models import STORY_COUNT


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Template CLI: generate {STORY_COUNT} stories from one topic, optionally with audio."
    )
    parser.add_argument("topic", help="Single topic to generate stories for.")
    parser.add_argument("--model", default=os.getenv("GATEWAY_MODEL", DEFAULT_MODEL))
    parser.add_argument("--provider", default=os.getenv("GATEWAY_PROVIDER", DEFAULT_PROVIDER))
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--cartesia-api-key", default=None)
    parser.add_argument("--with-audio", action="store_true", help="Enable Cartesia audio synthesis.")
    parser.add_argument("--output-dir", default="output")
    return parser.parse_args()


def _story_tts_transcript(*, headline: str, story: str) -> str:
    return f"{headline}. {story.strip()}"


def main() -> None:
    load_dotenv()
    args = parse_args()

    gateway_api_key = args.api_key or os.getenv("PYDANTIC_AI_GATEWAY_API_KEY")
    if not gateway_api_key:
        raise RuntimeError(
            "Missing API key. Set PYDANTIC_AI_GATEWAY_API_KEY or pass --api-key paig_<key>."
        )

    cartesia_key = args.cartesia_api_key or os.getenv("CARTESIA_API_KEY")
    if args.with_audio and not cartesia_key:
        raise RuntimeError("Audio requested, but CARTESIA_API_KEY is missing.")

    bunny_region = os.getenv("BUNNY_STORAGE_REGION", "").strip()
    bunny_zone = os.getenv("BUNNY_STORAGE_ZONE", "").strip()
    bunny_access_key = os.getenv("BUNNY_STORAGE_ACCESS_KEY", "").strip()
    bunny_prefix = os.getenv("BUNNY_STORAGE_PREFIX", "audio").strip("/")
    if args.with_audio and (not bunny_region or not bunny_zone or not bunny_access_key):
        raise RuntimeError(
            "Audio requested, but Bunny upload configuration is missing. "
            "Set BUNNY_STORAGE_REGION, BUNNY_STORAGE_ZONE, and BUNNY_STORAGE_ACCESS_KEY."
        )

    print(f"Step 1/3: Generating {STORY_COUNT} story ideas...")
    plan = generate_story_plan(
        topic=args.topic,
        model_name=args.model,
        provider_name=args.provider,
        gateway_api_key=gateway_api_key,
    )

    print(f"Step 2/3: Writing {STORY_COUNT} stories...")
    written = write_full_stories(
        plan=plan,
        model_name=args.model,
        provider_name=args.provider,
        gateway_api_key=gateway_api_key,
    )

    print("Step 3/3: Saving outputs...")
    run_dir = save_outputs(output_dir=Path(args.output_dir).expanduser(), plan=plan, written=written)

    if args.with_audio and cartesia_key:
        print(f"Audio: synthesizing {STORY_COUNT} story clips...")
        ordered_segments: list[bytes] = []
        for idx, story in enumerate(written.stories):
            ordered_segments.append(
                synthesize_cartesia_tts(
                    cartesia_api_key=cartesia_key,
                    transcript=_story_tts_transcript(headline=story.headline, story=story.story),
                )
            )
            if idx + 1 < len(written.stories):
                ordered_segments.append(synthesize_silence_segment(duration_seconds=0.8))

        if len(ordered_segments) >= 2:
            combined_audio = concatenate_audio_segments(audio_segments=ordered_segments, output_format="wav")
        elif ordered_segments:
            combined_audio = ordered_segments[0]
        else:
            combined_audio = b""

        if combined_audio:
            audio_file_path = run_dir / "written_stories_audio.wav"
            audio_file_path.write_bytes(combined_audio)

            object_path = f"{bunny_prefix}/{run_dir.name}/written_stories_audio.wav"
            uploaded_url = upload_bytes_to_bunny_storage(
                file_bytes=combined_audio,
                object_path=object_path,
                storage_zone=bunny_zone,
                access_key=bunny_access_key,
                region=bunny_region,
            )
            (run_dir / "written_stories_audio_bunny_url.txt").write_text(uploaded_url, encoding="utf-8")
            print(f"Audio uploaded to Bunny Storage: {uploaded_url}")

    print(f"Done. Output folder: {run_dir}")


if __name__ == "__main__":
    main()

from __future__ import annotations

from pydantic import BaseModel, Field

STORY_COUNT = 3


class StoryIdea(BaseModel):
    headline: str
    angle: str


class StoryPlan(BaseModel):
    topic: str
    stories: list[StoryIdea] = Field(min_length=STORY_COUNT, max_length=STORY_COUNT)


class WrittenStory(BaseModel):
    index: int
    headline: str
    story: str


class WrittenStories(BaseModel):
    topic: str
    stories: list[WrittenStory] = Field(min_length=STORY_COUNT, max_length=STORY_COUNT)

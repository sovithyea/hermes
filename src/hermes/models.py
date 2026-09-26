"""Data shapes shared across the pipeline. Everything is saved as JSON so it can be hand-edited."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NARRATOR = "Narrator"

LineType = Literal["narration", "dialogue", "thought", "mindspeech"]


class SfxCue(BaseModel):
    query: str
    position: Literal["before", "during", "after"] = "during"
    volume: float = 0.5


class ScriptLine(BaseModel):
    id: str  # "ch003-0042"
    chapter: int
    paragraph: int
    type: LineType
    speaker: str
    text: str
    emotion: str = "neutral"
    sfx: list[SfxCue] = Field(default_factory=list)
    ambience: str | None = None


class Character(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    gender: Literal["female", "male", "unknown"] = "unknown"
    age: Literal["child", "young", "adult", "old", "unknown"] = "unknown"
    kind: Literal["human", "dragon", "other"] = "human"
    description: str = ""
    voice: str | None = None  # assigned during casting
    line_count: int = 0


class Cast(BaseModel):
    # Name of the character whose eyes the story is told through (first-person books).
    pov_character: str | None = None
    # In first-person books the POV character's dialogue uses the narrator voice unless split.
    split_pov_voice: bool = False
    narrator_voice: str | None = None
    unknown_voice: str | None = None  # for lines the director couldn't attribute
    characters: list[Character] = Field(default_factory=list)

    def find(self, name: str) -> Character | None:
        key = name.strip().lower()
        for c in self.characters:
            if c.name.lower() == key or key in (a.lower() for a in c.aliases):
                return c
        return None

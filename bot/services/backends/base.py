"""The contract every LLM backend implements.

Two calls is all the product needs: free-form text for the conversation, and
schema-validated JSON for the assessment. Keeping the surface this small is what
makes swapping a paid provider for a free one a config change rather than a
rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


class LLMBackend(Protocol):
    name: str

    async def complete(
        self, *, system: str, messages: list[dict], max_tokens: int
    ) -> tuple[str, Usage]:
        """Free-form reply. `messages` are {"role": "user"|"assistant", "content": str}."""
        ...

    async def complete_json(
        self, *, system: str, prompt: str, schema: type[BaseModel], max_tokens: int
    ) -> tuple[BaseModel | None, Usage]:
        """Schema-validated JSON. Returns None rather than raising — feedback is a
        nicety, and a failed assessment must never cost the learner their reply."""
        ...

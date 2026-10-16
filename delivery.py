"""Short-delivery detection for prompts the worker receives truncated.

The Antigravity worker shortens long prompts from the tail, silently and
variably (soyelmismo/hermes-antigravity-subscription#29, measured 2026-10-12:
a 252,156-character prompt was delivered as 96,658 input tokens on one turn
and 114,794 on the next, with the tail -- usually the instruction -- lost
first). Nothing in the request path notices: the model answers the shortened
prompt, the usage chunk reports healthy token counts, and the turn looks
ordinary.

This module detects the signature that survives every material-dependent
guesswork: the *assembled* prompt keeps growing while the *delivered* input
tokens stop growing. No tokenizer and no chars-per-token constant are needed,
which matters because the ratio on this route varies about tenfold with the
material (dense numeric tables tokenise far heavier than prose).

It is a detector, not a guard: it reports the first over-the-line turn in a
session, so a caller can warn, retry with a chunked prompt, or fall back to a
provider that delivers whole prompts. Predicting the cut before sending is a
separate problem (see the same issue's preflight note).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = ["DeliverySample", "DeliveryWatch", "ShortDelivery", "DISABLE_ENV"]

# Below this, prompts are trivially deliverable and the ratio maths is noise.
MIN_PROMPT_CHARS = 20_000
# A jump smaller than this is ordinary turn-to-turn churn, not a rewrite.
MIN_CHARS_GROWTH = 8_000
# The prompt must have grown by at least this fraction ...
CHARS_GROWTH_RATIO = 0.25
# ... while delivered input tokens grew by no more than this fraction.
TOKEN_GROWTH_RATIO = 0.05

DISABLE_ENV = "ANTIGRAVITY_DISABLE_DELIVERY_WATCH"


@dataclass(frozen=True)
class DeliverySample:
    """One completed turn: what we assembled, and what the worker billed for."""

    prompt_chars: int
    input_tokens: int


@dataclass(frozen=True)
class ShortDelivery:
    """A prompt that grew materially while its delivered tokens did not."""

    sample: DeliverySample
    previous: DeliverySample

    @property
    def chars_growth(self) -> float:
        return (self.sample.prompt_chars - self.previous.prompt_chars) / max(
            self.previous.prompt_chars, 1
        )

    @property
    def token_growth(self) -> float:
        return (self.sample.input_tokens - self.previous.input_tokens) / max(
            self.previous.input_tokens, 1
        )

    def describe(self) -> str:
        """One line for the log: both sides of the comparison, in full."""
        return (
            "prompt sent to agy grew "
            f"{self.previous.prompt_chars:,} -> {self.sample.prompt_chars:,} chars "
            f"(+{self.chars_growth:.0%}) while the worker reported input tokens "
            f"{self.previous.input_tokens:,} -> {self.sample.input_tokens:,} "
            f"({self.token_growth:+.0%}); the prompt is probably being delivered "
            "shortened from the tail. Route long prompts through a chunked send "
            "or a provider that delivers whole prompts "
            "(soyelmismo/hermes-antigravity-subscription#29)."
        )


class DeliveryWatch:
    """Per-client record of the last turn's (prompt size, delivered tokens).

    The comparison is deliberately between *consecutive turns*, not against a
    predicted size: within one session the material usually stays similar, so
    a flat token count under a growing prompt is decisive, whereas an absolute
    chars-per-token constant would either miss dense payloads or cry wolf on
    prose. One warning per session is enough -- the condition persists once it
    starts -- so the latch suppresses repeats until the prompt shrinks back.
    """

    def __init__(self) -> None:
        self._last: DeliverySample | None = None
        self._latched = False

    @property
    def last_sample(self) -> DeliverySample | None:
        return self._last

    def observe(self, prompt_chars: int, input_tokens: int) -> ShortDelivery | None:
        """Feed one completed turn; return the finding when delivery fell short."""
        if os.environ.get(DISABLE_ENV):
            return None

        current = DeliverySample(prompt_chars=max(int(prompt_chars), 0), input_tokens=int(input_tokens))
        previous, self._last = self._last, current

        # A shrunken prompt is a new conversation, a cleared context, or a
        # fresh chunked send: whatever it is, the previous sample no longer
        # describes this turn, and the latch should be free to fire again.
        if previous is None or current.prompt_chars < previous.prompt_chars:
            self._latched = False
            return None
        if current.prompt_chars < MIN_PROMPT_CHARS or current.input_tokens <= 0:
            return None
        if previous.input_tokens <= 0:
            return None
        if current.prompt_chars - previous.prompt_chars < MIN_CHARS_GROWTH:
            return None
        if self._latched:
            return None
        finding = ShortDelivery(sample=current, previous=previous)
        if finding.chars_growth < CHARS_GROWTH_RATIO:
            return None
        if finding.token_growth > TOKEN_GROWTH_RATIO:
            return None
        self._latched = True
        logger.warning("Antigravity prompt delivery looks short: %s", finding.describe())
        return finding

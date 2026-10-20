"""Evaluation protocol errors (Phase 9)."""


class RandomSplitProhibitedError(ValueError):
    """SPEC §15.1 / §18 Phase 9: random row-level time-series splits are forbidden."""

    def __init__(self, split_mode: str):
        super().__init__(
            f"split_mode={split_mode!r} is prohibited. Walk-forward evaluation allows only "
            f"split_mode='chronological' (RANDOM_SPLIT_PROHIBITED / SPEC §15.1)."
        )
        self.split_mode = split_mode

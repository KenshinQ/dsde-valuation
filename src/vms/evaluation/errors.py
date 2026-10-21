"""Evaluation protocol errors (SPEC §17.1, Phase 11)."""


class RandomSplitProhibitedError(ValueError):
    """SPEC §17.1 / §20 Phase 11: random row-level time-series splits are forbidden."""

    def __init__(self, split_mode: str):
        super().__init__(
            f"split_mode={split_mode!r} is prohibited. Walk-forward evaluation allows only "
            f"split_mode='chronological' (RANDOM_SPLIT_PROHIBITED / SPEC §17.1)."
        )
        self.split_mode = split_mode

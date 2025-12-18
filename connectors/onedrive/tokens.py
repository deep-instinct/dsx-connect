from typing import Optional


class DeltaState:
    """Container for storing delta cursor state."""

    def __init__(self):
        self.cursor: Optional[str] = None

    def update(self, cursor: Optional[str]):
        if cursor:
            self.cursor = cursor

    def get(self) -> Optional[str]:
        return self.cursor

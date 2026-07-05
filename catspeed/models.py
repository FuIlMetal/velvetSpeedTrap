"""Shared data types."""

from dataclasses import dataclass


@dataclass
class RunRecord:
    """One bout of running, bracketed by inactivity."""

    started_at: float   # unix epoch seconds
    ended_at: float     # unix epoch seconds
    peak_mph: float
    avg_mph: float
    duration_s: float
    revolutions: int
    treat_given: bool = False

    def as_row(self) -> tuple:
        """Tuple in the column order used by db.save_run()."""
        return (
            self.started_at,
            self.ended_at,
            self.peak_mph,
            self.avg_mph,
            self.duration_s,
            self.revolutions,
            1 if self.treat_given else 0,
        )

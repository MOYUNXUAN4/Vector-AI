"""Segment-aware Unity-time to wall-clock alignment (v2).

Fixes over v1:

1. A data gap is an explicit unsupported interval, even when the offset is
   stable; mapping into it is ambiguous.
2. Within-segment drift is measured (p05/p95 and max-min).  A drift-only
   session is `DRIFTED`, never `CLEAN`; drifting segments make mappings
   ambiguous.
3. Samples keep their physical CSV line and run id; mixing runs raises.
4. Mapping interpolates the offset inside a segment, but never across a gap,
   and `map_interval` rejects intervals that cross a gap, a step or a
   transient segment.

Pure library: no file access, no globals, no side effects.
"""
from __future__ import annotations

import bisect
import math
import statistics
from dataclasses import dataclass, field

DEFAULT_MAX_GAP_SECONDS = 0.1
DEFAULT_JUMP_SECONDS = 0.05
DEFAULT_DRIFT_SECONDS = 0.02
DEFAULT_GUARD_SECONDS = 0.05
DEFAULT_MIN_SEGMENT_ROWS = 5


@dataclass(frozen=True)
class Sample:
    csv_line: int
    run_id: str
    epoch: float
    unity: float

    @property
    def offset(self):
        return self.epoch - self.unity


@dataclass
class Segment:
    index: int
    first_csv_line: int
    last_csv_line: int
    rows: int
    offset_median: float
    offset_min: float
    offset_max: float
    offset_p05: float
    offset_p95: float
    start_epoch: float
    end_epoch: float
    start_unity: float
    end_unity: float
    transient: bool = False
    drifting: bool = False
    samples: list[Sample] = field(default_factory=list)

    @property
    def drift_seconds(self):
        return self.offset_max - self.offset_min


@dataclass
class Step:
    after_csv_line: int
    epoch: float
    unity: float
    delta_seconds: float


@dataclass
class Gap:
    after_csv_line: int
    start_unity: float
    end_unity: float
    start_epoch: float
    end_epoch: float
    seconds: float


@dataclass
class Mapping:
    value: float
    segment_index: int
    ambiguous: bool
    reasons: tuple[str, ...] = ()

    @property
    def reason(self):
        return ",".join(self.reasons) if self.reasons else "ok"


@dataclass
class IntervalMapping:
    start: float
    end: float
    segment_index: int
    ambiguous: bool
    reasons: tuple[str, ...] = ()

    @property
    def reason(self):
        return ",".join(self.reasons) if self.reasons else "ok"


class RunAlignment:
    def __init__(self, *, run_id, samples, segments, steps, gaps,
                 max_gap, guard, drift):
        self.run_id = run_id
        self.samples = samples
        self.segments = segments
        self.steps = steps
        self.gaps = gaps
        self.max_gap = max_gap
        self.guard = guard
        self.drift = drift

    @property
    def offset_range_seconds(self):
        if not self.samples:
            return 0.0
        values = [sample.offset for sample in self.samples]
        return max(values) - min(values)

    @property
    def max_segment_drift_seconds(self):
        return max((segment.drift_seconds for segment in self.segments), default=0.0)

    @property
    def components(self):
        return {
            "steps": len(self.steps),
            "gaps": len(self.gaps),
            "drifting_segments": sum(1 for segment in self.segments if segment.drifting),
            "transient_segments": sum(1 for segment in self.segments if segment.transient),
        }

    @property
    def verdict(self):
        if not self.samples:
            return "NO_GEOMETRY"
        if self.steps:
            return "STEPPED"
        if any(segment.drifting for segment in self.segments):
            return "DRIFTED"
        if self.gaps:
            return "GAPPED"
        return "CLEAN"

    def _segment_for(self, value, clock):
        for segment in self.segments:
            low = segment.start_unity if clock == "unity" else segment.start_epoch
            high = segment.end_unity if clock == "unity" else segment.end_epoch
            if low - 1e-9 <= value <= high + 1e-9:
                return segment, False
        nearest = min(self.segments,
                      key=lambda s: abs(((s.start_unity + s.end_unity) / 2 if clock == "unity"
                                         else (s.start_epoch + s.end_epoch) / 2) - value))
        return nearest, True

    def _map(self, value, clock):
        if not self.segments:
            return Mapping(float("nan"), -1, True, ("no_segments",))
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return Mapping(float("nan"), -1, True, ("nonfinite_input",))
        for gap in self.gaps:
            low, high = ((gap.start_unity, gap.end_unity) if clock == "unity"
                         else (gap.start_epoch, gap.end_epoch))
            if low - 1e-9 <= value <= high + 1e-9:
                return Mapping(float("nan"), -1, True, ("in_gap",))
        segment, extrapolated = self._segment_for(value, clock)
        key = "unity" if clock == "unity" else "epoch"
        ordered = sorted(segment.samples, key=lambda sample: getattr(sample, key))
        keys = [getattr(sample, key) for sample in ordered]
        reasons = []
        if extrapolated:
            reasons.append("extrapolated")
        index = bisect.bisect_left(keys, value)
        if index <= 0 or index >= len(ordered):
            nearest = ordered[0] if index <= 0 else ordered[-1]
            offset = nearest.offset
            reasons.append("extrapolated")
        else:
            left, right = ordered[index - 1], ordered[index]
            span = getattr(right, key) - getattr(left, key)
            if span <= 0:
                offset = left.offset
                reasons.append("nonmonotonic_segment")
            elif right.epoch - left.epoch > self.max_gap:
                # Never interpolate across a missing interval; use the nearer side.
                offset = left.offset if (value - getattr(left, key)) <= span / 2 else right.offset
                reasons.append("bridges_gap")
            else:
                fraction = (value - getattr(left, key)) / span
                offset = left.offset + (right.offset - left.offset) * fraction
        if segment.transient:
            reasons.append("transient_segment")
        if segment.drifting:
            reasons.append("drifting_segment")
        low = segment.start_unity if clock == "unity" else segment.start_epoch
        high = segment.end_unity if clock == "unity" else segment.end_epoch
        if min(abs(value - low), abs(high - value)) < self.guard:
            reasons.append("near_segment_boundary")
        mapped = value + offset if clock == "unity" else value - offset
        return Mapping(float(mapped), segment.index, bool(reasons), tuple(dict.fromkeys(reasons)))

    def to_epoch(self, unity_time):
        return self._map(unity_time, "unity")

    def to_unity(self, epoch_time):
        return self._map(epoch_time, "epoch")

    def map_interval(self, start_unity, end_unity):
        if not all(isinstance(x, (int, float)) and math.isfinite(x)
                   for x in (start_unity, end_unity)):
            return IntervalMapping(float("nan"), float("nan"), -1, True, ("nonfinite_input",))
        low, high = sorted((start_unity, end_unity))
        start = self.to_epoch(low)
        end = self.to_epoch(high)
        reasons = list(start.reasons) + list(end.reasons)
        for step in self.steps:
            if low < step.unity < high:
                reasons.append("interval_crosses_step")
        for gap in self.gaps:
            if gap.start_unity < high and gap.end_unity > low:
                reasons.append("interval_crosses_gap")
        for segment in self.segments:
            if segment.transient and segment.start_unity < high and segment.end_unity > low:
                reasons.append("interval_crosses_transient_segment")
        if self.offset_range_seconds > self.drift:
            reasons.append("session_offset_range_exceeds_tolerance")
        unique = tuple(dict.fromkeys(reasons))
        return IntervalMapping(start.value, end.value,
                               start.segment_index if start.segment_index == end.segment_index else -1,
                               bool(unique), unique)


def _percentile(values, fraction):
    values = sorted(values)
    if len(values) == 1:
        return values[0]
    location = (len(values) - 1) * fraction
    low, high = math.floor(location), math.ceil(location)
    return values[low] + (values[high] - values[low]) * (location - low)


def analyze(samples, *, run_id=None, max_gap=DEFAULT_MAX_GAP_SECONDS,
            jump=DEFAULT_JUMP_SECONDS, drift=DEFAULT_DRIFT_SECONDS,
            guard=DEFAULT_GUARD_SECONDS, min_rows=DEFAULT_MIN_SEGMENT_ROWS):
    """Analyze one run; raises if samples contain more than one run id."""
    finite = [s for s in samples
              if isinstance(s.epoch, (int, float)) and isinstance(s.unity, (int, float))
              and math.isfinite(s.epoch) and math.isfinite(s.unity)]
    if run_id is None:
        run_ids = {s.run_id for s in finite}
        if len(run_ids) > 1:
            raise ValueError("samples contain multiple run ids: " + ", ".join(sorted(run_ids)))
        run_id = next(iter(run_ids), "")
    clean = [s for s in finite if s.run_id == run_id]
    clean.sort(key=lambda s: s.epoch)
    if not clean:
        return RunAlignment(run_id=run_id, samples=[], segments=[], steps=[], gaps=[],
                            max_gap=max_gap, guard=guard, drift=drift)

    offsets = [sample.offset for sample in clean]
    starts = [0]
    gaps, steps = [], []
    for index in range(1, len(clean)):
        seconds = clean[index].epoch - clean[index - 1].epoch
        if seconds > max_gap:
            gaps.append(Gap(clean[index - 1].csv_line,
                            clean[index - 1].unity, clean[index].unity,
                            clean[index - 1].epoch, clean[index].epoch, seconds))
        delta = offsets[index] - offsets[index - 1]
        if abs(delta) > jump:
            starts.append(index)
            steps.append(Step(clean[index].csv_line, clean[index].epoch,
                              clean[index].unity, delta))

    boundaries = starts + [len(clean)]
    segments = []
    for number in range(len(starts)):
        first, last = boundaries[number], boundaries[number + 1] - 1
        values = offsets[first:last + 1]
        segment = Segment(
            index=number,
            first_csv_line=clean[first].csv_line,
            last_csv_line=clean[last].csv_line,
            rows=last - first + 1,
            offset_median=float(statistics.median(values)),
            offset_min=float(min(values)),
            offset_max=float(max(values)),
            offset_p05=float(_percentile(values, 0.05)),
            offset_p95=float(_percentile(values, 0.95)),
            start_epoch=clean[first].epoch,
            end_epoch=clean[last].epoch,
            start_unity=clean[first].unity,
            end_unity=clean[last].unity,
            transient=(last - first + 1) < min_rows,
            samples=clean[first:last + 1],
        )
        segment.drifting = segment.drift_seconds > drift
        segments.append(segment)
    return RunAlignment(run_id=run_id, samples=clean, segments=segments,
                        steps=steps, gaps=gaps, max_gap=max_gap, guard=guard, drift=drift)


def group_by_run(samples):
    """Return {run_id: [Sample, ...]} preserving input order."""
    groups = {}
    for sample in samples:
        groups.setdefault(sample.run_id, []).append(sample)
    return groups


def samples_from_rows(rows, *, default_run_id="unknown"):
    """Build samples from CSV dict rows.

    Uses ``__csv_line__`` when present (physical line) and ``run_id`` for
    identity; falls back to index+2 / default_run_id for synthetic tests.
    """
    samples = []
    for index, row in enumerate(rows, start=2):
        try:
            epoch = float(row.get("source_timestamp"))
            unity = float(row.get("geometry_source_timestamp"))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(epoch) and math.isfinite(unity)):
            continue
        line = row.get("__csv_line__", index)
        try:
            line = int(line)
        except (TypeError, ValueError):
            line = index
        run_id = row.get("run_id") or default_run_id
        samples.append(Sample(line, str(run_id), epoch, unity))
    return samples

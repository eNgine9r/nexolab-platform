"""Explicit section-addressed XJP profile; never infer it from one response."""
PREFIX = "dixell-xjp60d-sections-v1-"
SOURCE = "dixell-xjp60d-sections"


def connected_count(version: str) -> int | None:
    if not version.startswith(PREFIX):
        return None
    value = version.removeprefix(PREFIX)
    if value not in {str(i) for i in range(1, 7)}:
        raise ValueError("Section profile must specify 1..6 attached probes")
    return int(value)


def section_units(base: int) -> range:
    if isinstance(base, bool) or not isinstance(base, int) or not 1 <= base <= 242:
        raise ValueError("Six section addresses must fit within 1..247")
    return range(base, base + 6)


def section_equipment_id(bus: str, base: int) -> str:
    return f"XJP60D-S:{bus}:{base}"


def read_section(reader, base: int, channel: int):
    section_units(base)
    if isinstance(channel, bool) or channel not in range(1, 7):
        raise ValueError("Section channel must be 1..6")
    return reader.read_channel(base + channel - 1, 1)

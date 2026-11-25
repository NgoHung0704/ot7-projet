"""Raw values arrive as text or numbers, sometimes missing: convert without ever turning "missing" into 0."""


def to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value) -> int | None:
    number = to_float(value)
    return None if number is None else round(number)

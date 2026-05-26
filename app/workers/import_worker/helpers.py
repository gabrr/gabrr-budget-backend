from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation


def _required_enum(value: object, *, path: str, allowed_values: set[str]) -> str:
    text = _required_string(value, path=path, max_length=80)
    if text not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise ValueError(f"Invalid {path}: {text!r} is not one of {allowed}")

    return text


def _required_string(value: object, *, path: str, max_length: int) -> str:
    if value is None:
        raise ValueError(f"Invalid {path}: value is required")
    stripped = str(value).strip()
    if not stripped:
        raise ValueError(f"Invalid {path}: value is required")
    if len(stripped) > max_length:
        raise ValueError(f"Invalid {path}: value is longer than {max_length} characters")

    return stripped


def _optional_string(value: object, *, path: str, max_length: int) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    if not stripped:
        return None
    if len(stripped) > max_length:
        raise ValueError(f"Invalid {path}: value is longer than {max_length} characters")

    return stripped


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(str(value))


def _required_decimal(value: object, *, path: str) -> Decimal:
    if value is None or isinstance(value, bool):
        raise ValueError(f"Invalid {path}: value is required")
    parsed = _parse_decimal(value, path=path)
    if parsed is None:
        raise ValueError(f"Invalid {path}: value is required")

    return parsed


def _optional_decimal(value: object, *, path: str) -> Decimal | None:
    if value is None or value == "":
        return None

    return _parse_decimal(value, path=path)


def _parse_decimal(value: object, *, path: str) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Invalid {path}: invalid decimal") from error


def _required_confidence(value: object, *, path: str) -> Decimal:
    confidence = _required_decimal(value, path=path)
    if confidence < Decimal("0") or confidence > Decimal("1"):
        raise ValueError(f"Invalid {path}: confidence must be between 0 and 1")

    return confidence


def _optional_date(value: object, *, path: str) -> date | None:
    if value is None or value == "":
        return None

    return _parse_date(value, path=path)


def _required_date(value: object, *, path: str) -> date:
    if value is None:
        raise ValueError(f"Invalid {path}: value is required")

    return _parse_date(value, path=path)


def _parse_date(value: object, *, path: str) -> date:
    raw_value = str(value).strip()
    if not raw_value:
        raise ValueError(f"Invalid {path}: value is required")

    for date_format in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
        try:
            return datetime.strptime(raw_value, date_format).date()
        except ValueError:
            pass

    for date_format in ("%d/%m", "%d-%m"):
        try:
            parsed = datetime.strptime(raw_value, date_format)
            return date(date.today().year, parsed.month, parsed.day)
        except ValueError:
            pass

    raise ValueError(f"Invalid {path}: invalid date")


def _normalize_currency(value: object, *, path: str) -> str:
    if value is None or value == "":
        return "BRL"
    currency = str(value).strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError(f"Invalid {path}: currency must be a three-letter ISO code")

    return currency

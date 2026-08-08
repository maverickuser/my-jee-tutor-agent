from __future__ import annotations

import argparse
from datetime import date


FLASH_LITE_MODEL = "gemini/gemini-2.5-flash-lite"
WARNING_START = date(2026, 9, 16)
RETIREMENT_DATE = date(2026, 10, 16)


def lifecycle_warning(model: str, *, today: date | None = None) -> str | None:
    if model != FLASH_LITE_MODEL or (today or date.today()) < WARNING_START:
        return None
    return (
        f"{FLASH_LITE_MODEL} is scheduled to retire on {RETIREMENT_DATE.isoformat()}; "
        "update the CD_GENERATION_MODEL GitHub variable before that date."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    warning = lifecycle_warning(args.model)
    if warning:
        print(f"::warning::{warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

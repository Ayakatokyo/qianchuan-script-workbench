"""Validate the live Qianchuan date boundary for this Skill and its derivatives."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
from zoneinfo import ZoneInfo

from errors import ContractError


def validate_period(start_date: str, end_date: str, *, today: date | None = None) -> dict[str, str]:
    """Accept a closed YYYY-MM-DD period ending by the day before yesterday in Beijing."""
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
        if start.isoformat() != start_date or end.isoformat() != end_date:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ContractError("period dates must use YYYY-MM-DD") from exc
    if start > end:
        raise ContractError("period.startDate must not be after endDate")
    current_day = today if today is not None else datetime.now(ZoneInfo("Asia/Shanghai")).date()
    latest_day = current_day - timedelta(days=2)
    if end > latest_day:
        raise ContractError(
            f"period.endDate must be no later than {latest_day.isoformat()} "
            "(Asia/Shanghai, T+2；北京时间前天及以前)；请修改日期后重试"
        )
    return {"startDate": start_date, "endDate": end_date}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Qianchuan T+2 before live acquisition")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()
    try:
        period = validate_period(args.start_date, args.end_date)
    except ContractError as exc:
        parser.error(str(exc))
    print(json.dumps(period, ensure_ascii=False))


if __name__ == "__main__":
    main()

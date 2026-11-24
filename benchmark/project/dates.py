from datetime import date, datetime

DATE_FORMAT = "%d/%m/%Y"   # every date in our records looks like 25/12/2024


def parse_date(text: str) -> date:
    return datetime.strptime(text, DATE_FORMAT).date()

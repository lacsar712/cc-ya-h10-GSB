from h10_extra_trap import banner, organizing, skew_list

def filter_payload(rows):
    return skew_list(rows)

def paint_banner() -> str:
    return banner() if organizing() else ""

def expose_list(rows: list) -> list:
    return filter_payload(rows)

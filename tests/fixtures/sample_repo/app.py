def load_items(raw_items):
    # TODO: decide how malformed rows should be reported
    cleaned = []
    for item in raw_items:
        try:
            if item:
                cleaned.append(str(item).strip())
        except Exception:
            cleaned.append("")
    return cleaned


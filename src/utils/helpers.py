def parse_cron_string(cron_str: str) -> set[int]:
    return {int(x.strip()) for x in cron_str.split(",")}

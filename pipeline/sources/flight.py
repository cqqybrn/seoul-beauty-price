"""Read embedded public Next Flight string records as JSON, never execute JavaScript."""

import json
import re

from parsel import Selector


def embedded_json_values(html: str, key: str) -> list:
    decoder = json.JSONDecoder()
    chunks = []
    for script in Selector(text=html).css("script::text").getall():
        match = re.fullmatch(r"\s*self\.__next_f\.push\((.*)\);?\s*", script, re.S)
        if not match:
            continue
        try:
            payload = json.loads(match[1])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list) and len(payload) == 2 and payload[0] == 1:
            if isinstance(payload[1], str):
                chunks.append(payload[1])
    text = "".join(chunks)
    values = []
    for match in re.finditer(r'"' + re.escape(key) + r'"\s*:', text):
        try:
            value, _ = decoder.raw_decode(text[match.end() :].lstrip())
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)) and value not in values:
            values.append(value)
    return values

"""Fixed service launch destinations; never accept a URL or profile from IPC."""
import json
from pathlib import Path

SERVICES = {item['id']: item for item in json.loads(Path(__file__).with_name('services.json').read_text())}


def service(identifier):
    if not isinstance(identifier, str) or identifier not in SERVICES:
        raise ValueError('Unknown viewing service')
    return SERVICES[identifier]

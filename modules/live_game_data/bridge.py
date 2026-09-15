"""Compose the passive reader into the guarded host bridge before attachment.

Example (paths relative to the project root):
    from modules.live_game_data import compose_bridge
    source = compose_bridge("headless/headless_host.js")
    script = frida_session.create_script(source)

HostController.attach() already does this. A missing/duplicate marker raises
ValueError; never inject the uncomposed host file directly.
"""
from pathlib import Path

MARKER='// @include modules/live_game_data/bridge.js'


def compose_bridge(host_path):
    source=Path(host_path).read_text(encoding='utf-8')
    if source.count(MARKER)!=1:
        raise ValueError('Host bridge must include the live-data module exactly once')
    reader=Path(__file__).with_suffix('.js').read_text(encoding='utf-8')
    return source.replace(MARKER,reader)

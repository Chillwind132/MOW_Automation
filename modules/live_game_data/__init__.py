"""Public live-observation API; snapshots never publish final results.

Example with an attached HostController and its reconciled active_match:
    from modules.live_game_data import observe_controller
    roster = controller.command("probe", target="roster")["probe"]
    live = controller.command("probe", target="live")["probe"]
    observe_controller(controller, roster, live)

This records snapshots and participation evidence without issuing game actions.
"""
from .statistics import normalize_live_statistics
from .telemetry import MatchTelemetry, record_controller
from .participation import Participation, observe_controller, history, native_reason
from .bridge import compose_bridge
from .association import associate_loaded
from .identity import participants, controlled_ai

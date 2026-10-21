"""EnergyPlus Python Plugin: lock-step bridge to an external controller over TCP.

Runs inside EnergyPlus (bundled Python 3.12). The controller can be any process (any Python version).
Each zone timestep: send state, block until the controller replies, apply actuator commands.
"""
import json
import os
import socket

from pyenergyplus.plugin import EnergyPlusPlugin


class RTBridge(EnergyPlusPlugin):
    def __init__(self):
        super().__init__()
        self.h = None
        self.sock = None
        self.reader = None
        self.cmd = {}

    def _handles(self, state):
        ex = self.api.exchange
        self.h = {
            "zone_t": ex.get_variable_handle(state, "Zone Mean Air Temperature", "GREENHOUSE ZONE"),
            "out_t": ex.get_variable_handle(state, "Site Outdoor Air Drybulb Temperature", "Environment"),
            "vent": ex.get_actuator_handle(state, "Schedule:Constant", "Schedule Value", "VENT OPENING"),
            "heat_sp": ex.get_actuator_handle(state, "Zone Temperature Control", "Heating Setpoint", "GREENHOUSE ZONE"),
            "wx_tdb": ex.get_actuator_handle(state, "Weather Data", "Outdoor Dry Bulb", "Environment"),
        }
        missing = [k for k, v in self.h.items() if v == -1]
        if missing:
            self.api.runtime.issue_severe(state, f"RTBridge: handles not found: {missing}")
            return False
        self.sock = socket.create_connection(("127.0.0.1", int(os.environ["RT_PORT"])), timeout=30)
        self.reader = self.sock.makefile("r", encoding="utf-8")
        return True

    # Earliest calling point of the zone timestep: exchange state/commands, apply weather override.
    def on_begin_zone_timestep_before_set_current_weather(self, state) -> int:
        ex = self.api.exchange
        if self.api.exchange.warmup_flag(state) or not ex.api_data_fully_ready(state):
            return 0
        if self.h is None and not self._handles(state):
            return 1
        msg = {
            "month": ex.month(state), "day": ex.day_of_month(state), "hour": ex.hour(state), "minute": ex.minutes(state),
            # values are those of the previous timestep (zone state is solved after this point)
            "zone_t_prev": ex.get_variable_value(state, self.h["zone_t"]),
            "out_t_prev": ex.get_variable_value(state, self.h["out_t"]),
        }
        self.sock.sendall((json.dumps(msg) + "\n").encode())
        line = self.reader.readline()
        if not line:
            self.api.runtime.issue_severe(state, "RTBridge: controller closed the connection")
            return 1
        self.cmd = json.loads(line)
        wx = self.cmd.get("outdoor_dry_bulb_c")
        if wx is None:
            ex.reset_actuator(state, self.h["wx_tdb"])
        else:
            ex.set_actuator_value(state, self.h["wx_tdb"], float(wx))
        return 0

    # Documented point for schedule / setpoint overrides: after weather, before the predictor computes loads.
    def on_begin_timestep_before_predictor(self, state) -> int:
        if self.h is None:
            return 0
        ex = self.api.exchange
        if "vent_opening" in self.cmd:
            ex.set_actuator_value(state, self.h["vent"], float(self.cmd["vent_opening"]))
        if "heating_setpoint_c" in self.cmd:
            ex.set_actuator_value(state, self.h["heat_sp"], float(self.cmd["heating_setpoint_c"]))
        return 0

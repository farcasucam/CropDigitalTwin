"""External controller (any Python): TCP server driving EnergyPlus in lock-step. Stdlib only."""
import json, socket, subprocess, sys, time

EPLUS = r"C:\EnergyPlusV26-1-0\energyplus.exe"

def main(heat_wave=True):
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    import os
    env = dict(os.environ, RT_PORT=str(port))
    proc = subprocess.Popen([EPLUS, "-w", "w.epw", "-d", "out_rt", "rt.idf"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    conn, _ = srv.accept(); rd = conn.makefile("r", encoding="utf-8")
    log = []; t0 = time.perf_counter()
    base_out = {}
    def lines():
        try:
            yield from rd
        except ConnectionResetError:   # EnergyPlus exits without a clean close
            return
    for line in lines():
        m = json.loads(line)
        key = (m["month"], m["day"], m["hour"], m["minute"])
        cmd = {"heating_setpoint_c": 12.0, "vent_opening": 1.0 if m["zone_t_prev"] > 26.0 else 0.0}
        if heat_wave and (m["month"], m["day"]) in {(7, 4), (7, 5)}:
            cmd["outdoor_dry_bulb_c"] = 38.0                   # fixed heat-wave air temperature
        conn.sendall((json.dumps(cmd) + "\n").encode())
        log.append((key, m["zone_t_prev"], m["out_t_prev"], cmd))
    out = proc.communicate()[0]
    dt = time.perf_counter() - t0
    print(f"steps exchanged: {len(log)}  wall time: {dt:.2f}s  ({1000*dt/max(1,len(log)):.2f} ms/step)  exit={proc.returncode}")
    for k, zt, ot, c in log[::24]:
        print(k, f"zone_t_prev={zt:.1f} out_t_prev={ot:.1f}", c)
    print(out.strip().splitlines()[-1] if out.strip() else "")

if __name__ == "__main__":
    main(heat_wave="--no-heat-wave" not in sys.argv)

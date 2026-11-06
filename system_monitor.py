"""
system_monitor.py
Generates a full system diagnostics report: CPU, RAM, disk, battery,
network, and top resource-hungry processes. Works on Windows (and
gracefully degrades elsewhere).
"""

import psutil
import platform
import datetime


def _bytes_to_gb(n):
    return round(n / (1024 ** 3), 2)


def get_report(top_n=5) -> dict:
    cpu_percent = psutil.cpu_percent(interval=0.8)
    cpu_freq = psutil.cpu_freq()
    mem = psutil.virtual_memory()
    disks = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "total_gb": _bytes_to_gb(usage.total),
                "used_gb": _bytes_to_gb(usage.used),
                "percent": usage.percent
            })
        except PermissionError:
            continue

    battery = psutil.sensors_battery()
    battery_info = None
    if battery:
        battery_info = {
            "percent": battery.percent,
            "plugged_in": battery.power_plugged
        }

    net = psutil.net_io_counters()

    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    top_cpu = sorted(procs, key=lambda x: x.get("cpu_percent") or 0, reverse=True)[:top_n]
    top_mem = sorted(procs, key=lambda x: x.get("memory_percent") or 0, reverse=True)[:top_n]

    report = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": {
            "percent": cpu_percent,
            "cores_logical": psutil.cpu_count(logical=True),
            "cores_physical": psutil.cpu_count(logical=False),
            "freq_mhz": round(cpu_freq.current) if cpu_freq else None
        },
        "memory": {
            "total_gb": _bytes_to_gb(mem.total),
            "used_gb": _bytes_to_gb(mem.used),
            "percent": mem.percent
        },
        "disks": disks,
        "battery": battery_info,
        "network": {
            "sent_gb": _bytes_to_gb(net.bytes_sent),
            "recv_gb": _bytes_to_gb(net.bytes_recv)
        },
        "top_cpu_processes": top_cpu,
        "top_memory_processes": top_mem
    }
    return report


def report_to_speech(report: dict) -> str:
    """Condense the report into a short sentence suitable for TTS."""
    cpu = report["cpu"]["percent"]
    mem = report["memory"]["percent"]
    top_proc = report["top_cpu_processes"][0]["name"] if report["top_cpu_processes"] else "none"
    lines = [
        f"System report. CPU load at {cpu} percent. Memory usage at {mem} percent.",
        f"Heaviest process right now is {top_proc}."
    ]
    if report["battery"]:
        b = report["battery"]
        state = "charging" if b["plugged_in"] else "on battery"
        lines.append(f"Battery at {b['percent']} percent, {state}.")
    for d in report["disks"]:
        if d["percent"] > 90:
            lines.append(f"Warning: drive {d['device']} is at {d['percent']} percent capacity.")
    return " ".join(lines)


def report_to_text(report: dict) -> str:
    """Full human-readable text report."""
    out = []
    out.append(f"=== ULTRON SYSTEM DIAGNOSTICS — {report['timestamp']} ===")
    out.append(f"OS: {report['os']}")
    out.append("")
    out.append(f"CPU: {report['cpu']['percent']}% load | "
               f"{report['cpu']['cores_physical']} physical / {report['cpu']['cores_logical']} logical cores | "
               f"{report['cpu']['freq_mhz']} MHz")
    out.append(f"Memory: {report['memory']['used_gb']} / {report['memory']['total_gb']} GB "
               f"({report['memory']['percent']}%)")
    out.append("")
    out.append("Disks:")
    for d in report["disks"]:
        out.append(f"  {d['device']} ({d['mountpoint']}): {d['used_gb']}/{d['total_gb']} GB "
                   f"({d['percent']}%)")
    if report["battery"]:
        b = report["battery"]
        out.append("")
        out.append(f"Battery: {b['percent']}% ({'plugged in' if b['plugged_in'] else 'on battery'})")
    out.append("")
    out.append(f"Network: sent {report['network']['sent_gb']} GB / received {report['network']['recv_gb']} GB "
               "(since boot)")
    out.append("")
    out.append("Top CPU consumers:")
    for p in report["top_cpu_processes"]:
        out.append(f"  {p['name']} (pid {p['pid']}): {p.get('cpu_percent', 0)}% CPU")
    out.append("")
    out.append("Top Memory consumers:")
    for p in report["top_memory_processes"]:
        out.append(f"  {p['name']} (pid {p['pid']}): {round(p.get('memory_percent') or 0, 1)}% RAM")
    return "\n".join(out)


if __name__ == "__main__":
    r = get_report()
    print(report_to_text(r))

"""Static device-capability detection for JARVIS graphics Auto mode."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from dataclasses import asdict, dataclass

import psutil


@dataclass(frozen=True)
class GraphicsCapability:
    platform: str
    cpu_name: str
    physical_cores: int
    logical_cores: int
    ram_gb: float
    gpu_name: str
    vram_mb: int | None
    gpu_class: str
    quality: str
    reason: str
    fingerprint: str

    def to_dict(self) -> dict:
        return asdict(self)


def _run(command: list[str], timeout: float = 3.0) -> str:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _classify_gpu(name: str) -> str:
    lowered = str(name or "").lower()
    if not lowered or lowered == "gpu unavailable":
        return "unknown"
    if any(marker in lowered for marker in (
        "software", "llvmpipe", "swiftshader", "microsoft basic", "virtualbox",
    )):
        return "software"
    if re.search(r"\bapple\s+m\d", lowered):
        return "apple_silicon"
    if any(marker in lowered for marker in (
        "nvidia", "geforce", "quadro", "tesla", "radeon pro", "radeon rx",
        "radeon vii", "arc a", "arc b",
    )):
        return "discrete"
    if any(marker in lowered for marker in (
        "intel", "iris", "uhd", "hd graphics", "vega", "integrated",
    )):
        return "integrated"
    return "unknown"


def score_graphics_capability(
    *,
    system: str,
    physical_cores: int,
    logical_cores: int,
    ram_gb: float,
    gpu_name: str,
    vram_mb: int | None,
    cpu_name: str = "",
) -> GraphicsCapability:
    """Resolve one of seven rendering tiers from stable hardware."""
    physical_cores = max(1, int(physical_cores or 1))
    logical_cores = max(physical_cores, int(logical_cores or physical_cores))
    ram_gb = max(0.0, float(ram_gb or 0.0))
    gpu_name = str(gpu_name or "GPU unavailable").strip() or "GPU unavailable"
    vram_mb = int(vram_mb) if vram_mb is not None and int(vram_mb) > 0 else None
    gpu_class = _classify_gpu(gpu_name)
    cpu_name = str(cpu_name or platform.processor() or "CPU unavailable").strip()

    score = 0
    if ram_gb < 4:
        score -= 4
    elif ram_gb < 8:
        score -= 2
    elif ram_gb < 12:
        score -= 1
    elif ram_gb >= 32:
        score += 3
    elif ram_gb >= 24:
        score += 2
    elif ram_gb >= 16:
        score += 1

    if physical_cores <= 2:
        score -= 3
    elif physical_cores <= 4:
        score -= 1
    elif physical_cores >= 13:
        score += 3
    elif physical_cores >= 9:
        score += 2
    elif physical_cores >= 7:
        score += 1

    if gpu_class == "software":
        score -= 4
    elif gpu_class == "integrated":
        score -= 1 if ram_gb < 16 else 0
    elif gpu_class == "apple_silicon":
        score += 3
    elif gpu_class == "discrete":
        if (vram_mb or 0) >= 12288:
            score += 4
        elif (vram_mb or 0) >= 6144:
            score += 3
        elif (vram_mb or 0) >= 3072:
            score += 2
        else:
            score += 1
    else:
        score -= 1

    if score <= -5:
        quality = "very_low"
    elif score <= -2:
        quality = "low"
    elif score <= 0:
        quality = "medium_low"
    elif score <= 2:
        quality = "medium"
    elif score <= 4:
        quality = "high_low"
    elif score <= 6:
        quality = "high"
    else:
        quality = "ultra"

    # Missing or software-only GPU data must never opt a device into an
    # expensive tier. This is conservative, not fabricated capability.
    if gpu_class == "unknown" and quality in {"high_low", "high", "ultra"}:
        quality = "medium"
    if gpu_class == "software" and quality not in {"very_low", "low"}:
        quality = "low"
    # Auto mode on a Mac is tuned for sustained laptop thermals. High and
    # Ultra remain available manually, but an automatic scan must not select a
    # continuous 40-60 FPS HUD merely because Apple Silicon can render it.
    if system == "Darwin" and quality in {"high", "ultra"}:
        quality = "high_low"

    gpu_summary = gpu_name
    if vram_mb:
        gpu_summary += f" · {vram_mb / 1024:.1f} GB VRAM"
    reason = (
        f"{cpu_name} · {physical_cores} physical / {logical_cores} logical cores · "
        f"{ram_gb:.1f} GB RAM · {gpu_summary}"
    )
    signature = json.dumps(
        {
            "system": system,
            "physical_cores": physical_cores,
            "logical_cores": logical_cores,
            "cpu_name": cpu_name.lower(),
            "ram_gb": round(ram_gb, 1),
            "gpu_name": gpu_name.lower(),
            "vram_mb": vram_mb,
            "gpu_class": gpu_class,
        },
        sort_keys=True,
    )
    fingerprint = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    return GraphicsCapability(
        platform=system,
        cpu_name=cpu_name,
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_gb=round(ram_gb, 1),
        gpu_name=gpu_name,
        vram_mb=vram_mb,
        gpu_class=gpu_class,
        quality=quality,
        reason=reason,
        fingerprint=fingerprint,
    )


def _mac_gpu() -> tuple[str, int | None]:
    output = _run(["system_profiler", "SPDisplaysDataType"], timeout=4.0)
    name_match = re.search(r"Chipset Model:\s*(.+)", output)
    vram_match = re.search(
        r"VRAM(?: \([^)]*\))?:\s*([\d.]+)\s*(GB|MB)", output, re.IGNORECASE
    )
    name = name_match.group(1).strip() if name_match else "GPU unavailable"
    vram = None
    if vram_match:
        value = float(vram_match.group(1))
        vram = int(value * 1024 if vram_match.group(2).upper() == "GB" else value)
    return name, vram


def _windows_gpu() -> tuple[str, int | None]:
    script = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
    )
    output = _run(["powershell", "-NoProfile", "-Command", script], timeout=4.0)
    try:
        payload = json.loads(output)
        adapters = payload if isinstance(payload, list) else [payload]
        adapters = [adapter for adapter in adapters if isinstance(adapter, dict)]
        best = max(adapters, key=lambda item: int(item.get("AdapterRAM") or 0), default={})
        name = str(best.get("Name") or "GPU unavailable")
        raw_ram = int(best.get("AdapterRAM") or 0)
        return name, raw_ram // (1024 * 1024) if raw_ram else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return "GPU unavailable", None


def _linux_gpu() -> tuple[str, int | None]:
    nvidia = _run([
        "nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"
    ])
    if nvidia.strip():
        first = nvidia.splitlines()[0]
        name, _, memory = first.partition(",")
        try:
            return name.strip(), int(float(memory.strip()))
        except ValueError:
            return name.strip(), None
    output = _run(["lspci"], timeout=2.0)
    for line in output.splitlines():
        if re.search(r"VGA|3D controller|Display controller", line, re.IGNORECASE):
            return line.split(":", 2)[-1].strip(), None
    return "GPU unavailable", None


def _cpu_name(system: str) -> str:
    if system == "Darwin":
        brand = _run(["sysctl", "-n", "machdep.cpu.brand_string"], timeout=2.0).strip()
        if brand:
            return brand
        hardware = _run(["system_profiler", "SPHardwareDataType"], timeout=3.0)
        match = re.search(r"(?:Chip|Processor Name):\s*(.+)", hardware)
        if match:
            name = match.group(1).strip()
            speed = re.search(r"Processor Speed:\s*(.+)", hardware)
            return f"{name} @ {speed.group(1).strip()}" if speed else name
    elif system == "Windows":
        name = _run([
            "powershell", "-NoProfile", "-Command",
            "(Get-CimInstance Win32_Processor | Select-Object -First 1).Name",
        ], timeout=3.0).strip()
        if name:
            return name
    elif system == "Linux":
        try:
            cpuinfo = open("/proc/cpuinfo", encoding="utf-8").read()
            match = re.search(r"model name\s*:\s*(.+)", cpuinfo)
            if match:
                return match.group(1).strip()
        except OSError:
            pass
    return platform.processor() or platform.machine() or "CPU unavailable"


def detect_graphics_capability() -> GraphicsCapability:
    system = platform.system() or "Unknown"
    physical = psutil.cpu_count(logical=False) or 1
    logical = psutil.cpu_count(logical=True) or physical
    ram_gb = psutil.virtual_memory().total / (1024 ** 3)
    if system == "Darwin":
        gpu_name, vram_mb = _mac_gpu()
    elif system == "Windows":
        gpu_name, vram_mb = _windows_gpu()
    elif system == "Linux":
        gpu_name, vram_mb = _linux_gpu()
    else:
        gpu_name, vram_mb = "GPU unavailable", None
    return score_graphics_capability(
        system=system,
        cpu_name=_cpu_name(system),
        physical_cores=physical,
        logical_cores=logical,
        ram_gb=ram_gb,
        gpu_name=gpu_name,
        vram_mb=vram_mb,
    )

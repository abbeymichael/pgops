"""
hotspot.py
Controls Windows Mobile Hotspot using the modern WinRT API via PowerShell.
Works on Windows 10/11 with any WiFi adapter — no legacy hostednetwork needed.
"""

import subprocess
import platform
import os


def _run_hidden(cmd: list, shell=False) -> tuple[bool, str]:
    """Run a command with no visible window."""
    kwargs = {}
    if platform.system() == "Windows":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, shell=shell, **kwargs
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:
        return False, str(e)


def _powershell(script: str) -> tuple[bool, str]:
    """Run a PowerShell script and return (success, output)."""
    ok, out = _run_hidden([
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass",
        "-Command", script
    ])
    return ok, out


# ─── Mobile Hotspot via WinRT ─────────────────────────────────────────────────

_PS_SET_AND_START = r"""
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime

    $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
    $tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)

    $config = $tetheringManager.GetCurrentAccessPointConfiguration()
    $config.Ssid = "%(ssid)s"
    $config.Passphrase = "%(password)s"

    $asyncOp = $tetheringManager.ConfigureAccessPointAsync($config)
    $task = [System.WindowsRuntimeSystemExtensions]::AsTask($asyncOp)
    $task.Wait(5000) | Out-Null

    $asyncOp2 = $tetheringManager.StartTetheringAsync()
    $task2 = [System.WindowsRuntimeSystemExtensions]::AsTask($asyncOp2)
    $task2.Wait(10000) | Out-Null

    Write-Output "OK"
} catch {
    Write-Output "ERR: $_"
}
"""

_PS_STOP = r"""
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
    $tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)
    $asyncOp = $tetheringManager.StopTetheringAsync()
    $task = [System.WindowsRuntimeSystemExtensions]::AsTask($asyncOp)
    $task.Wait(5000) | Out-Null
    Write-Output "OK"
} catch {
    Write-Output "ERR: $_"
}
"""

_PS_STATUS = r"""
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $connectionProfile = [Windows.Networking.Connectivity.NetworkInformation,Windows.Networking.Connectivity,ContentType=WindowsRuntime]::GetInternetConnectionProfile()
    $tetheringManager = [Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager,Windows.Networking.NetworkOperators,ContentType=WindowsRuntime]::CreateFromConnectionProfile($connectionProfile)
    Write-Output $tetheringManager.TetheringOperationalState
} catch {
    Write-Output "ERR: $_"
}
"""

_PS_OPEN_SETTINGS = (
    "Start-Process ms-settings:network-mobilehotspot"
)


def start_hotspot(ssid: str = "PGOps-Net", password: str = "postgres123") -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, (
            "macOS hotspot: System Settings → General → Sharing → Internet Sharing."
        )

    if len(password) < 8:
        return False, "Password must be at least 8 characters."

    script = _PS_SET_AND_START % {"ssid": ssid, "password": password}
    ok, out = _powershell(script)

    if "OK" in out and "ERR" not in out:
        return True, (
            f"Mobile Hotspot started\n"
            f"SSID:     {ssid}\n"
            f"Password: {password}\n\n"
            f"Connect other devices to '{ssid}'\n"
            f"then use your LAN IP as the database host."
        )

    # WinRT failed — fall back to opening the Settings page
    _powershell(_PS_OPEN_SETTINGS)
    return False, (
        f"Could not start hotspot automatically.\n\n"
        f"The Mobile Hotspot settings page has been opened for you.\n\n"
        f"Steps:\n"
        f"1. Turn on Mobile Hotspot in the Settings window that just opened\n"
        f"2. Click Edit to set the name to: {ssid}\n"
        f"3. Set password to: {password}\n"
        f"4. Other devices connect to '{ssid}'\n"
        f"5. Use your LAN IP (shown on Server tab) as the host\n\n"
        f"Technical detail: {out[:200] if out else 'WinRT API unavailable'}"
    )


def stop_hotspot() -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, "Not applicable on this OS."

    ok, out = _powershell(_PS_STOP)
    if "OK" in out and "ERR" not in out:
        return True, "Mobile Hotspot stopped."

    # Try to open settings as fallback
    _powershell(_PS_OPEN_SETTINGS)
    return False, "Could not stop hotspot automatically. Settings page opened."


def open_hotspot_settings() -> tuple[bool, str]:
    """Open Windows Mobile Hotspot settings page directly."""
    if platform.system() != "Windows":
        return False, "Windows only."
    ok, out = _powershell(_PS_OPEN_SETTINGS)
    return True, "Mobile Hotspot settings opened."


def get_hotspot_status() -> str:
    """Returns 'On', 'Off', or 'Unknown'."""
    if platform.system() != "Windows":
        return "Unknown"
    ok, out = _powershell(_PS_STATUS)
    if "On" in out:
        return "On"
    if "Off" in out:
        return "Off"
    return "Unknown"


def get_hotspot_ip() -> str:
    return "192.168.137.1"

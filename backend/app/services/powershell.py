"""PowerShell runner for Exchange Online operations.

Adapted from api-scripts/services/powershell.py — as-is.
"""

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)
PWSH_PATH = "pwsh"


def escape_ps_string(value: str) -> str:
    """Escape a string for safe use inside PowerShell single quotes.

    PowerShell single-quoted strings only need single quotes escaped
    (by doubling them). No other escape sequences are interpreted.
    """
    return value.replace("'", "''")


def check_pwsh_available() -> bool:
    return shutil.which(PWSH_PATH) is not None


def ensure_exchange_module() -> None:
    result = subprocess.run(
        [PWSH_PATH, "-Command",
         "if (-not (Get-Module -ListAvailable ExchangeOnlineManagement)) { "
         "Install-Module ExchangeOnlineManagement -Force -Scope CurrentUser -AllowClobber }"],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to ensure Exchange module: {result.stderr}")


class PowerShellRunner:
    """Run PowerShell commands via subprocess for Exchange Online operations."""

    def __init__(self, tenant: dict):
        self.tenant = tenant
        self.app_id = tenant["client_id"]
        self.cert_path = tenant.get("cert_pfx_path")
        self.cert_password = tenant["cert_password"]
        self.org = tenant["org_domain"]

    def _connect_script(self) -> str:
        safe_cert_pwd = escape_ps_string(self.cert_password)
        safe_app_id = escape_ps_string(self.app_id)
        safe_cert_path = escape_ps_string(self.cert_path) if self.cert_path else ""
        safe_org = escape_ps_string(self.org)
        lines = [
            "$ErrorActionPreference = 'Stop'",
            f"$secPwd = ConvertTo-SecureString '{safe_cert_pwd}' -AsPlainText -Force",
            f"Connect-ExchangeOnline -AppId '{safe_app_id}' "
            f"-CertificateFilePath '{safe_cert_path}' "
            f"-CertificatePassword $secPwd "
            f"-Organization '{safe_org}' -ShowBanner:$false",
        ]
        return "\n".join(lines)

    def _disconnect_script(self) -> str:
        return "Disconnect-ExchangeOnline -Confirm:$false"

    def run(self, commands: list[str], timeout: int = 600) -> tuple[str, str]:
        full_script = "\n".join([self._connect_script(), *commands, self._disconnect_script()])
        result = subprocess.run(
            [PWSH_PATH, "-Command", full_script],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"PowerShell error (exit {result.returncode}):\n"
                f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
        return result.stdout, result.stderr

    def run_batched(self, commands: list[str], batch_size: int = 10, timeout: int = 600) -> tuple[str, str]:
        all_stdout, all_stderr = [], []
        for i in range(0, len(commands), batch_size):
            batch = commands[i:i + batch_size]
            stdout, stderr = self.run(batch, timeout=timeout)
            all_stdout.append(stdout)
            all_stderr.append(stderr)
        return "\n".join(all_stdout), "\n".join(all_stderr)

    def run_raw(self, script: str, timeout: int = 600) -> tuple[str, str]:
        result = subprocess.run(
            [PWSH_PATH, "-Command", script],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr

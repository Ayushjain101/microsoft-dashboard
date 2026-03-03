import subprocess
import shutil
from config import PWSH_PATH


def check_pwsh_available() -> bool:
    """Check if pwsh is available on PATH."""
    return shutil.which(PWSH_PATH) is not None


def ensure_exchange_module() -> None:
    """Install ExchangeOnlineManagement module if not present."""
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
        """Generate Connect-ExchangeOnline command."""
        lines = [
            "$ErrorActionPreference = 'Stop'",
            f"$secPwd = ConvertTo-SecureString '{self.cert_password}' -AsPlainText -Force",
            f"Connect-ExchangeOnline -AppId '{self.app_id}' "
            f"-CertificateFilePath '{self.cert_path}' "
            f"-CertificatePassword $secPwd "
            f"-Organization '{self.org}' -ShowBanner:$false",
        ]
        return "\n".join(lines)

    def _disconnect_script(self) -> str:
        return "Disconnect-ExchangeOnline -Confirm:$false"

    def run(self, commands: list[str], timeout: int = 600) -> tuple[str, str]:
        """Run PowerShell commands wrapped in connect/disconnect.

        Args:
            commands: list of PS command strings to execute between connect/disconnect
            timeout: max seconds to wait

        Returns:
            (stdout, stderr) tuple
        """
        full_script = "\n".join([
            self._connect_script(),
            *commands,
            self._disconnect_script(),
        ])
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
        """Run commands in batches, each with its own connect/disconnect cycle.

        Splits commands into groups of batch_size and runs each group
        with a fresh Exchange Online connection. This avoids session
        throttling/timeouts on large command sets.

        Args:
            commands: list of PS command strings
            batch_size: commands per batch (default 10)
            timeout: max seconds per batch

        Returns:
            (combined_stdout, combined_stderr) tuple
        """
        all_stdout, all_stderr = [], []
        for i in range(0, len(commands), batch_size):
            batch = commands[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(commands) + batch_size - 1) // batch_size
            stdout, stderr = self.run(batch, timeout=timeout)
            all_stdout.append(stdout)
            all_stderr.append(stderr)
        return "\n".join(all_stdout), "\n".join(all_stderr)

    def run_raw(self, script: str, timeout: int = 600) -> tuple[str, str]:
        """Run a raw PowerShell script without connect/disconnect wrapper."""
        result = subprocess.run(
            [PWSH_PATH, "-Command", script],
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout, result.stderr

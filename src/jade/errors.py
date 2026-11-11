"""Every error the toolkit raises is a JadeError with a stable code. str(error) says what to do about it.
Messages never contain secrets: tokens are redacted before they reach an error."""

from __future__ import annotations

# code → (meaning, remediation). Codes are stable: agents and scripts may match on them.
CODES: dict[str, tuple[str, str]] = {
    "JADE100": ("not configured", "Run `jade init`, or set JADE_CONFIG to a jade.config.yaml."),
    "JADE101": ("bad token", "The server refused the token. Make a new one and store it: `jade secret set <name>`."),
    "JADE102": ("legacy query-string authentication refused", "This Vault accepts ?token= in URLs. Update Jade Vault to 2.18.3 or later. Only for diagnosis: --accept-legacy."),
    "JADE103": ("credential refused", "Base refused the task credential (revoked or expired). The task stops; it is not retried. Start the task again."),
    "JADE104": ("secret store unavailable", "Install keyring (`pip install keyring`), or allow a 0600 file with --accept-file-secrets."),
    "JADE105": ("missing secret", "Store it with `jade secret set <name>`, or set the environment variable JADE_SECRET_<NAME>."),
    "JADE200": ("cannot reach the target", "Check the URL in jade.config.yaml and that the server is running (`jade doctor`)."),
    "JADE201": ("MCP protocol mismatch", "The server speaks another MCP protocol version. Update the server or the toolkit."),
    "JADE202": ("remote error", "The target answered with an error; the message says which."),
    "JADE203": ("incompatible version", "The target's version is outside what STACK.md allows. Upgrade the target or the toolkit (`jade doctor`)."),
    "JADE204": ("timed out", "The call took longer than its timeout. Pass timeout= / --timeout, or check the target."),
    "JADE205": ("idempotency conflict", "The same idempotency key was used with other arguments. Use a new key for a new call."),
    "JADE300": ("approval required", "Allow it in jade.config.yaml under approvals, or confirm interactively."),
    "JADE301": ("denied by approvals", "A deny rule in jade.config.yaml matches. Deny wins; change the rule to allow it."),
    "JADE302": ("unsafe without confirmation", "Destructive or unknown operations need a person to confirm, or --yolo (logged)."),
    "JADE303": ("playbook not approved", "Review it, then `jade playbook approve <name>`. Any edit needs a new approval."),
    "JADE400": ("invalid configuration", "Fix jade.config.yaml at the place the message names (`jade config show`)."),
    "JADE401": ("invalid playbook", "Fix the playbook at the place the message names (`jade playbook check <name>`)."),
    "JADE402": ("invalid site spec", "Fix the site spec at the place the message names (`jade site check`)."),
    "JADE403": ("unknown tool", "The target has no such tool. List them: `jade base tools`."),
    "JADE404": ("ambiguous tool", "More than one target has this tool. Name the target."),
    "JADE405": ("not found", "Check the name; list what exists with the matching `list` command."),
    "JADE406": ("generated files are stale", "Run `python build/build.py` and commit the result."),
    "JADE500": ("doctor failed", "Run `jade doctor` and fix what it reports, or pass --force to go on anyway."),
}

# exit codes: 0 ok, 1 user error, 2 remote error, 3 refused for safety
EXIT = {"1": 1, "4": 1, "5": 1, "2": 2, "3": 3}


class JadeError(Exception):
    code = "JADE400"

    def __init__(self, message: str = "", code: str | None = None, *, data: dict | None = None):
        self.code = code or type(self).code
        self.message = message or CODES.get(self.code, ("error", ""))[0]
        self.data = data or {}
        super().__init__(self.message)

    @property
    def remediation(self) -> str:
        return CODES.get(self.code, ("", ""))[1]

    @property
    def exit_code(self) -> int:
        if self.code == "JADE500":
            return 1
        if self.code in ("JADE102", "JADE103"):
            return 3
        return EXIT.get(self.code[4], 1)

    def __str__(self) -> str:
        r = self.remediation
        return f"{self.code}: {self.message}" + (f"\n  → {r}" if r else "")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "remediation": self.remediation, **({"data": self.data} if self.data else {})}


class ConfigError(JadeError):
    code = "JADE400"


class AuthError(JadeError):
    code = "JADE101"


class RemoteError(JadeError):
    code = "JADE202"

    def __init__(self, message: str = "", code: str | None = None, *, status: int = 0, data: dict | None = None):
        super().__init__(message, code, data=data)
        self.status = status


class SafetyError(JadeError):
    code = "JADE300"


class PlaybookError(JadeError):
    code = "JADE401"


class SiteError(JadeError):
    code = "JADE402"

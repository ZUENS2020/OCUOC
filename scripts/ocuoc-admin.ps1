# Launch OCUOC elevated. MCP stdio still inherits the host process integrity;
# for Cursor, start Cursor itself as Administrator instead of this wrapper.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python not found: $python"
}
Start-Process -FilePath $python -ArgumentList @("-m", "ocuoc") -WorkingDirectory $root -Verb RunAs

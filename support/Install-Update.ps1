param(
    [Parameter(Mandatory = $true)][string]$InstallerPath,
    [Parameter(Mandatory = $true)][int]$ProcessId,
    [Parameter(Mandatory = $true)][string]$AppExePath
)

$ErrorActionPreference = 'Stop'
$logDir = Join-Path $env:LOCALAPPDATA 'MediaFlow\Logs'
$logFile = Join-Path $logDir 'updater.log'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-Log([string]$Message) {
    Add-Content -LiteralPath $logFile -Value ("[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message) -Encoding UTF8
}

try {
    if (-not (Test-Path -LiteralPath $InstallerPath -PathType Leaf)) {
        throw "No se encontró el instalador descargado: $InstallerPath"
    }
    Write-Log "Esperando a que MediaFlow cierre (PID $ProcessId)..."
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 400
    }
    if (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        throw 'MediaFlow no se cerró dentro del tiempo esperado. No se inició la actualización.'
    }

    Write-Log "Iniciando instalador: $InstallerPath"
    $setup = Start-Process -FilePath $InstallerPath -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
    Write-Log "El instalador terminó con código $($setup.ExitCode)."
    if ($setup.ExitCode -ne 0) {
        throw "El instalador devolvió el código $($setup.ExitCode). Revisa el registro de Inno Setup."
    }

    if (Test-Path -LiteralPath $AppExePath -PathType Leaf) {
        Write-Log 'Reiniciando MediaFlow actualizado.'
        Start-Process -FilePath $AppExePath -WorkingDirectory (Split-Path -Parent $AppExePath)
    } else {
        Write-Log "No se encontró el ejecutable para reiniciar: $AppExePath"
    }
} catch {
    Write-Log ("ERROR: " + $_.Exception.Message)
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show(
            "MediaFlow no pudo completar la actualización.`r`n`r`n$($_.Exception.Message)`r`n`r`nRegistro: $logFile",
            'MediaFlow - Actualizador',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error
        ) | Out-Null
    } catch { }
    exit 1
}

exit 0

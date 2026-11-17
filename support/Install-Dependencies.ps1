$ErrorActionPreference = 'Stop'
$logDir = Join-Path $env:LOCALAPPDATA 'MediaFlow\Logs'
$logFile = Join-Path $logDir 'dependency-install.log'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
}

function Find-WinGetExecutable([string]$PackageId, [string]$Executable) {
    $root = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
    if (Test-Path -LiteralPath $root) {
        $dirs = Get-ChildItem -LiteralPath $root -Directory -Filter ($PackageId + '_*') -ErrorAction SilentlyContinue
        foreach ($dir in $dirs) {
            $found = Get-ChildItem -LiteralPath $dir.FullName -File -Filter $Executable -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
    }
    return $null
}

function Find-Executable([string]$Name, [string]$PackageId) {
    $command = Get-Command ($Name + '.exe') -ErrorAction SilentlyContinue
    if ($command -and $command.Source) { return $command.Source }
    $link = Join-Path (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links') ($Name + '.exe')
    if (Test-Path -LiteralPath $link) { return $link }
    return Find-WinGetExecutable $PackageId ($Name + '.exe')
}

function Show-DependencyWarning([string]$Message) {
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [System.Windows.Forms.MessageBox]::Show(
            $Message,
            'MediaFlow - componentes necesarios',
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
    } catch {
        Write-Log ("No se pudo mostrar el aviso: " + $_.Exception.Message)
    }
}

try {
    Write-Log 'Inicio de comprobacion de dependencias.'
    $wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
    $missing = [System.Collections.Generic.List[string]]::new()
    $packages = @(
        @{ Name = 'FFmpeg'; Id = 'Gyan.FFmpeg.Essentials'; Executable = 'ffmpeg' },
        @{ Name = 'Deno'; Id = 'DenoLand.Deno'; Executable = 'deno' }
    )

    foreach ($package in $packages) {
        $found = Find-Executable $package.Executable $package.Id
        if ($found) {
            Write-Log ($package.Name + ' ya esta disponible: ' + $found)
            continue
        }

        if (-not $wingetCommand) {
            $missing.Add($package.Name + ': WinGet no esta instalado')
            Write-Log ('No se pudo instalar ' + $package.Name + ': no se encontro winget.exe.')
            continue
        }

        Write-Log ('Instalando ' + $package.Name + ' desde WinGet...')
        $installOutput = & $wingetCommand.Source install --id $package.Id --exact --source winget --silent --accept-package-agreements --accept-source-agreements 2>&1
        $exitCode = $LASTEXITCODE
        foreach ($line in $installOutput) { Write-Log ([string]$line) }
        if ($exitCode -ne 0) {
            $missing.Add($package.Name + ': WinGet devolvio codigo ' + $exitCode)
            Write-Log ('WinGet devolvio codigo ' + $exitCode + ' al instalar ' + $package.Name + '.')
            continue
        }

        Start-Sleep -Seconds 3
        $found = Find-Executable $package.Executable $package.Id
        if ($found) {
            Write-Log ($package.Name + ' quedo instalado: ' + $found)
        } else {
            $missing.Add($package.Name + ': no se localizo el ejecutable despues de instalar')
            Write-Log ('No se encontro el ejecutable de ' + $package.Name + ' despues de la instalacion.')
        }
    }

    if ($missing.Count -gt 0) {
        $details = $missing -join "`r`n- "
        $message = "MediaFlow se instalo, pero faltan algunos componentes:`r`n`r`n- $details`r`n`r`nComprueba tu conexion a Internet y que WinGet (App Installer) este disponible. Despues vuelve a abrir MediaFlow.`r`n`r`nRegistro:`r`n$logFile"
        Show-DependencyWarning $message
    } else {
        Write-Log 'FFmpeg y Deno estan listos.'
    }
} catch {
    Write-Log ("ERROR: " + $_.Exception.Message)
    $message = "MediaFlow se instalo, pero hubo un problema al preparar sus componentes.`r`n`r`n" + $_.Exception.Message + "`r`n`r`nComprueba tu conexion a Internet y que WinGet este instalado.`r`n`r`nRegistro:`r`n$logFile"
    Show-DependencyWarning $message
}

Write-Log 'Comprobacion finalizada.'
exit 0

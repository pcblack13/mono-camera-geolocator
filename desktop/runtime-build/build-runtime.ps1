# Build the self-contained WINDOWS runtime: python + postgresql/postgis + backend deps,
# plus a pinned Redis port (conda-forge ships no win-64 redis).
#
# Run ON A WINDOWS MACHINE (PowerShell):
#   powershell -ExecutionPolicy Bypass -File runtime-build\build-runtime.ps1
#
# Mirrors build-runtime.sh decision-for-decision:
#   - STRICT ISOLATION from the machine's user site-packages (the Linux build once
#     shipped a runtime with no numpy because pip saw it in ~/.local - never again).
#   - In-repo mamba root + package cache (no shared-lock stalls).
#   - A completeness gate on the packed tarball.
#   - gis/ai_engine are NOT installed here: they ride the app as SOURCE and shadow
#     any baked copy via PYTHONPATH (see boot.js).

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$SOFT = Resolve-Path "..\.."

$env:PYTHONNOUSERSITE = "1"
$env:MAMBA_ROOT_PREFIX = "$PWD\mamba-root"
$env:CONDA_PKGS_DIRS = "$PWD\mamba-root\pkgs"

Write-Host "== micromamba =="
if (!(Test-Path "bin\micromamba.exe")) {
  New-Item -ItemType Directory -Force -Path bin | Out-Null
  Invoke-WebRequest -Uri "https://github.com/mamba-org/micromamba-releases/releases/latest/download/micromamba-win-64" -OutFile "bin\micromamba.exe"
}

Write-Host "== conda env (python only - see the postgres note below) =="
if (!(Test-Path "env\python.exe")) {
  & .\bin\micromamba.exe create -y -r mamba-root -p "$PWD\env" -c conda-forge python=3.12 pip
  if ($LASTEXITCODE -ne 0) { throw "micromamba create failed" }
}

Write-Host "== postgresql + postgis (pinned official Windows builds) =="
# * conda-forge ships NO win-64 postgis (same gap as redis). So on Windows the
#   database comes from the two upstream projects themselves, merged into the
#   env's OWN subtree Library\pgsql (runtime.js pgBin points there on win).
#   NOT merged into Library\bin: EDB ships its own OpenSSL DLLs, and merging
#   once replaced conda python's libssl - pip lost ssl on the build machine.
#   Contents:
#     - EDB's PostgreSQL 16 binaries zip (pgsql\{bin,lib,share})
#     - the PostGIS project's bundle, BUILT AGAINST those EDB binaries, which
#       overlays the same three dirs (plus gdal-data for raster support).
#   Both PINNED; the bundle's pg16 build must match the postgres major.
if (!(Test-Path "env\Library\pgsql\bin\postgres.exe")) {
  $pgZip = "$env:TEMP\pg-win64.zip"
  Invoke-WebRequest -Uri "https://get.enterprisedb.com/postgresql/postgresql-16.9-1-windows-x64-binaries.zip" -OutFile $pgZip
  Expand-Archive -Path $pgZip -DestinationPath "$env:TEMP\pg-extract" -Force
  New-Item -ItemType Directory -Force -Path "env\Library\pgsql" | Out-Null
  # robocopy, not Copy-Item: Copy-Item nests a directory INSIDE an existing
  # directory of the same name instead of merging. robocopy merges. Exit codes
  # 0-7 are success (8+ is failure), hence the explicit check.
  foreach ($dir in @("bin", "lib", "share")) {
    robocopy "$env:TEMP\pg-extract\pgsql\$dir" "env\Library\pgsql\$dir" /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy pgsql\$dir failed ($LASTEXITCODE)" }
  }
  Remove-Item $pgZip
  Remove-Item -Recurse -Force "$env:TEMP\pg-extract"
}
if (!(Test-Path "env\Library\pgsql\share\extension\postgis.control")) {
  $gisZip = "$env:TEMP\postgis-win64.zip"
  Invoke-WebRequest -Uri "https://download.osgeo.org/postgis/windows/pg16/postgis-bundle-pg16-3.6.2x64.zip" -OutFile $gisZip
  Expand-Archive -Path $gisZip -DestinationPath "$env:TEMP\postgis-extract" -Force
  $bundle = Get-ChildItem "$env:TEMP\postgis-extract\postgis-bundle-*" | Select-Object -First 1
  foreach ($dir in @("bin", "lib", "share", "gdal-data")) {
    if (Test-Path "$($bundle.FullName)\$dir") {
      robocopy "$($bundle.FullName)\$dir" "env\Library\pgsql\$dir" /E /NFL /NDL /NJH /NJS /NP | Out-Null
      if ($LASTEXITCODE -ge 8) { throw "robocopy postgis $dir failed ($LASTEXITCODE)" }
    }
  }
  Remove-Item $gisZip
  Remove-Item -Recurse -Force "$env:TEMP\postgis-extract"
}
if (!(Test-Path "env\Library\pgsql\share\extension\postgis.control")) { throw "postgis.control missing after overlay" }

Write-Host "== backend python deps (isolated) =="
& .\env\python.exe -s -m pip install --no-input -r "$SOFT\backend\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "pip install requirements failed" }
& .\env\python.exe -s -m pip install --no-input conda-pack
if ($LASTEXITCODE -ne 0) { throw "pip install conda-pack failed" }

Write-Host "== sanity (isolated imports) =="
& .\env\python.exe -s -c "import cv2, rasterio, pyproj, fastapi, celery, numpy, dateutil, uvicorn, ezdxf, reportlab, shapely, geopandas; print('py deps OK (isolated)')"
if ($LASTEXITCODE -ne 0) { throw "sanity imports failed" }
& .\env\Library\pgsql\bin\postgres.exe --version

Write-Host "== redis (pinned community Windows port) =="
# No official Windows Redis exists. tporadowski/redis is the maintained port the
# ecosystem uses; PINNED, not 'latest'. It ships as extraResources/redis-win -
# runtime.js starts it from there on win32.
if (!(Test-Path "redis-win\redis-server.exe")) {
  New-Item -ItemType Directory -Force -Path redis-win | Out-Null
  $redisZip = "$env:TEMP\redis-win64.zip"
  Invoke-WebRequest -Uri "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip" -OutFile $redisZip
  Expand-Archive -Path $redisZip -DestinationPath redis-win -Force
  Remove-Item $redisZip
}
& .\redis-win\redis-server.exe --version

Write-Host "== conda-pack =="
if (Test-Path "runtime.tar.gz") { Remove-Item "runtime.tar.gz" }
# conda_pack has no __main__ (python -m fails); use its console entry point.
& .\env\Scripts\conda-pack.exe -p "$PWD\env" -o runtime.tar.gz --compress-level 1
if ($LASTEXITCODE -ne 0) { throw "conda-pack failed" }
Get-Item runtime.tar.gz | Format-List Name, Length

Write-Host "== verify the tarball is complete =="
# Same gate as Linux: the ARTIFACT must contain the critical packages.
$listing = tar -tzf runtime.tar.gz
foreach ($pkg in @("numpy", "dateutil", "cv2", "rasterio", "fastapi", "celery", "ezdxf", "reportlab", "shapely", "geopandas")) {
  if (-not ($listing | Select-String -SimpleMatch "site-packages/$pkg/" -Quiet)) {
    throw "FATAL: runtime.tar.gz is missing '$pkg' - the env was not built in isolation."
  }
}
Write-Host "RUNTIME BUILD: OK (windows)"

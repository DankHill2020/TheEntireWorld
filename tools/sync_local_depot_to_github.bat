@echo off
setlocal enabledelayedexpansion

set "REPO=C:\depot"
set "REMOTE=origin"
set "BRANCH=main"

echo.
echo Sync local depot to GitHub
echo Repo:   %REPO%
echo Remote: %REMOTE%
echo Branch: %BRANCH%
echo.

cd /d "%REPO%" || (
    echo [ERROR] Could not cd to "%REPO%".
    pause
    exit /b 1
)

if not exist ".git" (
    echo [ERROR] "%REPO%" is not a Git repo.
    pause
    exit /b 1
)

echo Checking remote...
git remote -v
if errorlevel 1 (
    echo [ERROR] Could not read Git remotes.
    pause
    exit /b 1
)

echo.
echo Fetching the latest remote branch...
git fetch %REMOTE% %BRANCH%
if errorlevel 1 goto git_error

echo.
echo Make sure .gitignore excludes Perforce/server/cache files before continuing:
echo   db.*
echo   **/db.*
echo   journal
echo   server.id
echo   server.locks/
echo   **/__pycache__/
echo   *.pyc
echo   *.gz
echo   .idea/
echo   .mayaSwatches/
echo   Time_Fighters/
echo   ArtSource/
echo   Time_Fighters 5.8/
echo   proj1/
echo   depot/
echo   **/.p4root/
echo   **/Saved/
echo   **/Intermediate/
echo   **/DerivedDataCache/
echo   **/Binaries/
echo   *.uproject
echo.

if exist "tools\.git" (
    echo [WARNING] Found nested repo: %REPO%\tools\.git
    echo Git may treat tools as an embedded repository for untracked files.
    echo If you want all tools files in this repo, consider moving/removing tools\.git first.
    echo.
)

choice /c YN /m "Stage local depot content now"
if errorlevel 2 (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo Running Tech Connector publication gates...
pushd "%REPO%\tools"
py -3.14 tech_connector\packaging\release_gate.py --source-root .
if errorlevel 1 (
    popd
    echo [ERROR] Publication safety checks failed. Nothing was staged.
    pause
    exit /b 1
)
py -3.14 -m pytest -q tech_connector\tests\test_stage_package_security.py tech_connector\tests\test_release_hardening.py tech_connector\tests\test_secure_settings.py tech_connector\tests\test_application_entitlement_gate.py tech_connector\tests\test_licensing_configuration.py tech_connector\tests\test_licensing_foundation.py tech_connector\tests\test_licensing_activation_client.py tech_connector\tests\test_licensing_http_adapters.py tech_connector\tests\test_host_bridge_entitlement.py tech_connector\tests\test_license_activation_dialog.py tech_connector\tests\test_release_python_contract.py
if errorlevel 1 (
    popd
    echo [ERROR] Required Tech Connector release tests failed. Nothing was staged.
    pause
    exit /b 1
)
py -3.14 tech_connector\packaging\stage_package.py reasoning-runtime --out .release_public_audit
if errorlevel 1 (
    popd
    echo [ERROR] Tech Connector package staging failed. Nothing was staged.
    pause
    exit /b 1
)
py -3.14 tech_connector\packaging\smoke_test_package.py .release_public_audit\reasoning-runtime
if errorlevel 1 (
    popd
    echo [ERROR] Tech Connector staged-package smoke test failed. Nothing was staged.
    pause
    exit /b 1
)
popd

echo.
echo Clearing anything already staged from previous runs...
git reset
if errorlevel 1 goto git_error

echo.
echo Cleaning staged Unreal/Perforce project paths from previous runs...
git restore --staged -- Time_Fighters "Time_Fighters 5.8" proj1 depot 2>nul
git restore --staged -- "*.uproject" "*.uasset" "*.umap" "*.ubulk" "*.uexp" "*.gz" 2>nul

echo.
echo Staging tracked changes and selected Git-managed folders...
git add -u
if errorlevel 1 goto git_error

if exist ".gitignore" (
    git add -- .gitignore
    if errorlevel 1 goto git_error
)
if exist "tools" (
    git add -- tools
    if errorlevel 1 goto git_error
)

echo.
echo Removing ignored/unwanted paths from the staged set...
git restore --staged -- Time_Fighters "Time_Fighters 5.8" proj1 depot 2>nul
git restore --staged -- "*.uproject" "*.uasset" "*.umap" "*.ubulk" "*.uexp" "*.gz" 2>nul

echo.
echo Current staged/unstaged status:
git status
if errorlevel 1 goto git_error

git diff --cached --quiet
if errorlevel 2 goto git_error
if not errorlevel 1 (
    echo.
    echo No staged changes to commit.
    goto push_check
)

set "LARGE_FILE="
for /f "delims=" %%F in ('git diff --cached --name-only --diff-filter=ACMR') do (
    if exist "%%F" if %%~zF GTR 94371840 (
        echo [ERROR] Staged file exceeds 90 MiB: %%F
        set "LARGE_FILE=1"
    )
)
if defined LARGE_FILE (
    echo Remove large generated/source-art files from Git before pushing.
    pause
    exit /b 1
)

echo.
choice /c YN /m "Commit these staged changes"
if errorlevel 2 (
    echo Leaving changes staged. Review with: git status
    pause
    exit /b 0
)

set "MSG="
set /p MSG="Enter a commit message or press Enter for [Sync local depot]: "
if "%MSG%"=="" set "MSG=Sync local depot"

git commit -m "%MSG%"
if errorlevel 1 goto git_error

:push_check
echo.
echo Verifying that local history includes the current GitHub branch...
git fetch %REMOTE% %BRANCH%
if errorlevel 1 goto git_error
git merge-base --is-ancestor %REMOTE%/%BRANCH% HEAD
if errorlevel 1 (
    echo [ERROR] Local and GitHub history have diverged.
    echo Reconcile them before pushing; no force push will be attempted.
    pause
    exit /b 1
)

echo.
choice /c YN /m "Push to GitHub"
if errorlevel 2 (
    echo Commit created locally, push skipped.
    pause
    exit /b 0
)

git push %REMOTE% %BRANCH%
if errorlevel 1 goto git_error

echo.
echo Done.
pause
exit /b 0

:git_error
echo.
echo [ERROR] A Git command failed. Review the message above.
echo You can inspect the repo with:
echo   cd /d %REPO%
echo   git status
pause
exit /b 1

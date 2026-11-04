# The production environment: dot-source it in the shell that runs the checkout this file sits in
# (the scheduled tasks do, via register_morning_tasks.ps1; for a manual production run:
#     . ..\ctd-prod\scripts\prod_env.ps1
# ). It sets variables for the current process only, never machine- or user-wide, so a development shell is
# unaffected. Paths come from this file's location, so none are hard-coded (data.md section 4).
#
#   PYTHONPATH        <repo>\src       import ctd from this checkout, not the editable install's (the development one)
#   CTD_RESULTS_ROOT  <repo>\prod      saved model results, <root>\results\light\...; apart from the development
#                                      checkout's, though the raw store and derived tables are shared by junction
#   CTD_OUTPUT_DIR    <repo>\..\ctd-pages   where `ctd report` writes: the gh-pages worktree that gets published
$repo = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = "$repo\src"
$env:CTD_RESULTS_ROOT = "$repo\prod"
$env:CTD_OUTPUT_DIR = Join-Path (Split-Path -Parent $repo) "ctd-pages"

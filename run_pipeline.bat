@echo off
cd /d "%~dp0"
"C:\Python314\python.exe" run_pipeline.py >> "data\pipeline_stdout.log" 2>&1

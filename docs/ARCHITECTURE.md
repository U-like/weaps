# Architecture direction

Current milestone is a verified portable Android build environment.

Planned layers:

1. Android UI / project workflow.
2. Media import and local project database.
3. Audio event detection and pitch estimation.
4. Sample matching engine.
5. Timeline representation.
6. Native media/DSP layer (FFmpeg and pitch/time processing) when needed.
7. Preview and export.

The first scaffold deliberately has no external UI dependencies. This keeps the bootstrap proof small and makes environment failures easy to diagnose. Compose can be added after the base build is verified.

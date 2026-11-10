# Inkplate-Board-Definitions-for-Arduino-IDE
Board definitions for the Soldered Inkplate E-Ink displays

## Instructions
1. Add URL: https://github.com/SolderedElectronics/Inkplate-Board-Definitions-for-Arduino-IDE/raw/refs/heads/main/package_Inkplate_Boards_index.json to "Additional Boards Manager" in your Arduino IDE Preferences
2. Install new boards via Tools -> Board -> Boards Manager. Search for "Soldered Inkplate Boards" (ESP32 Inkplates) or "Inkplate MOTION Boards" (Inkplate 6MOTION) and press install
3. Wait a bit.
4. Pick the new board from Tools -> Board menu.

For board-specific setup (drivers, upload, libraries) see the quick start guide in the [Inkplate docs](https://docs.soldered.com/inkplate/), e.g. [Inkplate 6MOTION](https://docs.soldered.com/inkplate/6motion/quick-start-guide/).

## For maintainers

### Releasing a new package version
1. Prepare the core folder named `<prefix>-<version>`, e.g. `Inkplate_Motion_core-2.1.0`, with `version=` in its `platform.txt` matching. Optionally add `upstream.version=` (the STM32/ESP32 Arduino core version it is based on).
2. Run (macOS/Linux):
   ```sh
   python3 .github/scripts/release.py path/to/Inkplate_Motion_core-2.1.0
   # ESP32 cores without upstream.version= in platform.txt:
   python3 .github/scripts/release.py path/to/Inkplate_core-5.0.0 --upstream-version 3.3.12
   ```
   It builds the zip next to the folder, adds the platform entry and any missing tools (copied from the ST/Espressif index) to `package_Inkplate_Boards_index.json`, and prints the `gh release create` command.
3. Create the GitHub release as a pre-release with that command, attaching the zip.
4. Commit and push the index to `dev`, wait for CI, then test with the `dev` index URL (`.../raw/refs/heads/dev/package_Inkplate_Boards_index.json`).
5. When it works: switch the release to a full release and fast-forward `main` to `dev`.

### CI
Every push and PR to `dev`/`main` runs `.github/workflows/ci.yml`:
- `validate-index`: every zip downloads and matches its checksum/size, all tools exist and have macOS/Windows/Linux builds (warns on missing native ARM64 builds), all tool URLs are reachable.
- `compile`: installs the newest ESP32 and MOTION packages from the branch's index and builds one example for each.

Only merge `dev` into `main` when CI on `dev` is green, `main` is what users install from.

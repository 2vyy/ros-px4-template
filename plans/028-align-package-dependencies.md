# Plan 028: Align Package Dependencies across Configuration Formats (DEP-01)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/setup.py src/core/package.xml`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW
- **Depends on**: plans/027-relocatable-package-resources.md
- **Category**: tech-debt
- **Planned at**: commit `ead4cc6`, 2026-06-29

## Why this matters

Currently, dependency declarations for the python workspace and ROS package are fragmented:
1. `pyproject.toml` lists required dependencies for dev tools (`numpy`, `pyyaml`, `opencv-python-headless`, etc.).
2. `src/core/setup.py` lists only `opencv-python-headless>=4.7.0` and `setuptools` under `install_requires`.
3. `src/core/package.xml` lists standard ROS dependencies but lacks declarations for `numpy`, `pyyaml`, `opencv`, and `ament_index_python` (which is imported in the nodes after standardizing resource resolution).
This misalignment can cause build and runtime failures when the package is built in clean/isolated environments (like CI/CD pipelines or new developer setups) because `rosdep` or package managers cannot detect the missing packages. Aligning these files ensures dependency completeness and correct build-ordering under `colcon`.

## Current state

- `pyproject.toml` (lines 7-18):
  ```toml
  dependencies = [
      "pyyaml>=6.0",
      # Tracks ROS Jazzy's apt NumPy (1.26.4); the cap is the cv_bridge/rclpy 1.x ABI,
      # not a preference. Revisit at ROS distro migration.
      "numpy>=1.26,<2.0",
      "rich>=13.7",
      "typer>=0.12",
      "tomli-w>=1.0",
      "pymavlink>=2.4",
      "websocket-client>=1.6",
      "opencv-python-headless>=4.7.0",
  ]
  ```
- `src/core/setup.py` (line 18):
  ```python
      install_requires=["setuptools", "opencv-python-headless>=4.7.0"],
  ```
- `src/core/package.xml` (lines 9-20):
  ```xml
    <buildtool_depend>ament_python</buildtool_depend>
    <depend>rclpy</depend>
    <depend>geometry_msgs</depend>
    <depend>std_msgs</depend>
    <depend>std_srvs</depend>
    <depend>px4_msgs</depend>
    <depend>px4_ros_msgs</depend>
    <exec_depend>ros2launch</exec_depend>
  ```

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Build     | `just build`             | exit 0              |
| Check     | `just check`             | exit 0, no errors   |
| Rosdep    | `rosdep install --from-paths src --ignore-src -r -y --simulate` | exit 0, outputs apt packages install simulation |

## Scope

**In scope**:
- `src/core/setup.py`
- `src/core/package.xml`

**Out of scope**:
- `pyproject.toml` (serves as the reference source of truth for runtime dependencies).

## Git workflow

- Branch: `advisor/028-align-dependencies`
- Commit per step; message style: conventional commits (e.g. `chore(core): align package dependencies across setup.py and package.xml`)

## Steps

### Step 1: Align Python PyPI Dependencies in `setup.py`

Open `src/core/setup.py`. Update the `install_requires` list to include `numpy` and `pyyaml`, matching the version specifiers in `pyproject.toml`.

```python
    install_requires=[
        "setuptools",
        "numpy>=1.26,<2.0",
        "pyyaml>=6.0",
        "opencv-python-headless>=4.7.0",
    ],
```

**Verify**: Run `just check` to ensure formatting/syntax is clean.

---

### Step 2: Add missing system and ROS dependencies to `package.xml`

Open `src/core/package.xml`. Add dependencies for `ament_index_python` (used for resource resolution), `python3-numpy` (used in coordinates/math), `python3-yaml` (used for mission parsing), and `python3-opencv` (used for marker tracking).

Insert these tags inside `<package>`:
```xml
  <depend>ament_index_python</depend>
  <depend>python3-numpy</depend>
  <depend>python3-yaml</depend>
  <depend>python3-opencv</depend>
```

**Verify**: Run the following `rosdep` simulation command to verify that all dependencies resolve to valid OS packages:
```bash
rosdep install --from-paths src --ignore-src -r -y --simulate
```
Expected output: A clean print showing the simulated installation of the dependencies (e.g. `apt-get install python3-numpy python3-yaml python3-opencv`).

---

### Step 3: Run the full verification suite

Perform a clean build and run the test suite to ensure no dependency-induced regressions exist.

```bash
just clean
just check
```

**Verify**: The command exits with `0` and all unit tests pass.

## Test plan

- Run `just check` (linting + tests must pass).
- Verify `rosdep` installation resolves all dependencies successfully by running `uv run tasks.py setup` (which runs `rosdep install`).

## Done criteria

- [ ] `setup.py`'s PyPI dependencies match version ranges in `pyproject.toml`.
- [ ] `package.xml` declares `python3-numpy`, `python3-yaml`, `python3-opencv`, and `ament_index_python`.
- [ ] `just check` exits 0.
- [ ] `plans/README.md` status row is updated.

## STOP conditions

- `rosdep` fails to resolve `python3-numpy`, `python3-yaml`, or `python3-opencv` (names vary across OS/ROS distributions, though these are the standard Jazzy/Ubuntu keys).

## Maintenance notes

- When adding future Python dependencies to the core package:
  1. Add to `pyproject.toml` `dependencies`.
  2. Add to `src/core/setup.py` `install_requires`.
  3. Add the corresponding `python3-<library>` rosdep key to `src/core/package.xml`.

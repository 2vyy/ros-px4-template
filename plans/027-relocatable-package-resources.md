# Plan 027: Standardize Resource Resolution for Configuration Files (ARCH-01)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: `git diff --stat ead4cc6..HEAD -- src/core/ros_px4_template_core/nodes/marker_localizer.py src/core/ros_px4_template_core/nodes/mission_manager.py src/core/setup.py`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: tech-debt
- **Planned at**: commit `ead4cc6`, 2026-06-29

## Why this matters

Currently, the `marker_localizer` and `mission_manager` nodes resolve their local configuration file paths (like `config/markers.yaml` and `config/missions/hover.yaml`) using hardcoded directory traversal via `Path(__file__).resolve().parents[4]`. This assumes that the node is running directly inside a standard development workspace structure where the root directory is exactly 4 levels above the source file. If the package is deployed to a staging/production system, or installed using standard ROS 2 debian packages, or run from Python site-packages, this directory traversal will fail to locate the files, breaking the system. Switching to standard ROS 2 resource resolution (`ament_index_python.packages.get_package_share_directory`) and installing the config files via `setup.py` makes the package fully relocatable and deployable.

## Current state

- `src/core/ros_px4_template_core/nodes/marker_localizer.py` (lines 38-40, 57-60):
  ```python
  def _project_root() -> Path:
      return Path(__file__).resolve().parents[4]
  ```
  ```python
          p = Path(str(self.get_parameter("marker_map_file").value))
          if not p.is_absolute():
              p = _project_root() / p
  ```
- `src/core/ros_px4_template_core/nodes/mission_manager.py` (lines 46-48, 63-66):
  ```python
  def _project_root() -> Path:
      return Path(__file__).resolve().parents[4]
  ```
  ```python
          mission_file = str(self.get_parameter("mission_file").value).strip() or _DEFAULT_MISSION
          p = Path(mission_file)
          if not p.is_absolute():
              p = _project_root() / p
  ```
- `src/core/setup.py` (lines 14-17):
  ```python
      data_files=[
          ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
          (f"share/{package_name}", ["package.xml"]),
      ],
  ```

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Build     | `just build`             | exit 0              |
| Check     | `just check`             | exit 0, no errors   |
| Tests     | `just test`              | all pass            |
| Scenario  | `just scenario 01_arm_takeoff` | PASS            |

## Scope

**In scope**:
- `src/core/ros_px4_template_core/nodes/marker_localizer.py`
- `src/core/ros_px4_template_core/nodes/mission_manager.py`
- `src/core/setup.py`

**Out of scope**:
- Path resolution in dev-only testing utilities (e.g., `tests/unit/test_hardware_config.py`).
- Any changes to `sim/` or `hardware/` launch files.

## Git workflow

- Branch: `advisor/027-resource-resolution`
- Commit per step; message style: conventional commits (e.g. `refactor(core): use standard ament resource resolution for configs`)

## Steps

### Step 1: Update `setup.py` to copy the `config/` files to the package share directory

Open `src/core/setup.py`. Add imports for `os` and `glob`. Update the `data_files` list to copy files from the workspace root `config/` directory to `share/ros_px4_template_core/config/` under the install prefix.

Modify `data_files` to look like this:
```python
import os
from glob import glob
from setuptools import setup

package_name = "ros_px4_template_core"

setup(
    name=package_name,
    version="0.1.0",
    ...
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", ["../../config/markers.yaml"]),
        (f"share/{package_name}/config/missions", glob("../../config/missions/*.yaml")),
        (f"share/{package_name}/config/params", glob("../../config/params/*.yaml")),
        (f"share/{package_name}/config/params/overlays", glob("../../config/params/overlays/*.yaml")),
        (f"share/{package_name}/config/paths", glob("../../config/paths/*.yaml")),
        (f"share/{package_name}/config/rviz", glob("../../config/rviz/*.rviz")),
    ],
    ...
```

**Verify**: Run `just build` to verify the workspace compiles. Check that the files are copied correctly to the install space by running:
```bash
ls install/ros_px4_template_core/share/ros_px4_template_core/config/missions
```
Expected output: `demo.yaml  hover.yaml  marker_hover.yaml  search_relocalize.yaml`

---

### Step 2: Refactor `marker_localizer.py` to use `get_package_share_directory`

Open `src/core/ros_px4_template_core/nodes/marker_localizer.py`.
1. Add the import for `get_package_share_directory` from `ament_index_python.packages`.
2. Remove the `_project_root()` function.
3. Replace `_project_root() / p` with `Path(get_package_share_directory("ros_px4_template_core")) / p`.

```python
from ament_index_python.packages import get_package_share_directory
# ...
        marker_map_file = str(self.get_parameter("marker_map_file").value)
        p = Path(marker_map_file)
        if not p.is_absolute():
            p = Path(get_package_share_directory("ros_px4_template_core")) / p
```

**Verify**: Run `just check` to ensure syntax, linting, and type checking pass.

---

### Step 3: Refactor `mission_manager.py` to use `get_package_share_directory`

Open `src/core/ros_px4_template_core/nodes/mission_manager.py`.
1. Add the import for `get_package_share_directory` from `ament_index_python.packages`.
2. Remove the `_project_root()` function.
3. Replace `_project_root() / p` with `Path(get_package_share_directory("ros_px4_template_core")) / p`.

```python
from ament_index_python.packages import get_package_share_directory
# ...
        mission_file = str(self.get_parameter("mission_file").value).strip() or _DEFAULT_MISSION
        p = Path(mission_file)
        if not p.is_absolute():
            p = Path(get_package_share_directory("ros_px4_template_core")) / p
```

**Verify**: Run `just check` to ensure syntax, linting, and type checking pass.

---

### Step 4: Run clean build and verify scenario

Perform a clean build to guarantee the workspace compiles from scratch without caching issues, and execute the takeoff scenario in the simulator to verify config resolution at runtime.

```bash
just clean
just build
just scenario 01_arm_takeoff
```

**Verify**: The scenario should complete and print a `PASS` verdict.

## Test plan

- Build & lint checks: Run `just check` to ensure no formatting, type, or build failures are introduced.
- E2E Flight Verification: Run `just scenario 01_arm_takeoff`. Since the scenario requires the mission manager to load `config/missions/hover.yaml`, it will crash if it fails to resolve the config path. Successful takeoff verifies config loading.

## Done criteria

- [ ] `just check` exits 0.
- [ ] `just scenario 01_arm_takeoff` exits 0 and reports `PASS`.
- [ ] `grep -rn "parents\[4\]" src/` returns no matches.
- [ ] No files outside the in-scope list are modified.
- [ ] `plans/README.md` status row is updated.

## STOP conditions

- `import ament_index_python` raises `ModuleNotFoundError` during linting or build phase (confirm ROS 2 environment is sourced).
- The file structures in `Current state` differ from the live code.

## Maintenance notes

- Sourcing setup file: The package share directory resolution relies on the built package being on the ROS package path (`AMENT_PREFIX_PATH`). Sourcing `install/setup.bash` after building is necessary for this standard lookup to succeed.

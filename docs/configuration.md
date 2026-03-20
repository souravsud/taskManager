# Configuration Guide

This document explains advanced configuration options for taskManager.

---

## Input format

```yaml
input_format:
  metadata_filename: pipeline_metadata.json
  folder_levels:
    - name: terrain_index
      prefix: terrain_
    - name: rotation_degree
      prefix: rotatedTerrain_
      suffix: _deg
  case_name_template: "case_{case_num:03d}_{terrain_index}_{rotation_degree:03d}deg"
```

---

## Folder structure

`folder_levels` defines how parameters are extracted from directory names.

| key | required | description |
|-----|----------|-------------|
| name | yes | Parameter name used in templates |
| prefix | no | Removed from folder name |
| suffix | no | Removed from folder name |

Values resembling integers are automatically converted.

---

## Example

```yaml
input_format:
  metadata_filename: case_metadata.json
  folder_levels:
    - name: terrain
      prefix: terrain_
    - name: velocity
      prefix: vel_
      suffix: ms
    - name: rotation
      prefix: rot_
      suffix: deg
  case_name_template: "{case_num:03d}_{terrain}_{velocity}ms_{rotation}deg"
```

---

## Case numbering

Each generated case receives a sequential `case_num` starting from 1.

Example:

```
case_001_...
case_002_...
```

Use `{case_num:03d}` in templates for zero-padded numbering.
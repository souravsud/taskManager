# Status Tracking

Each case folder contains a `case_status.json` file.

---

## Example

```json
{
  "mesh_status": "DONE",
  "mesh_ok": true,
  "copied_to_hpc": true,
  "submitted": true,
  "job_id": "123456",
  "job_status": "RUNNING"
}
```

---

## Mesh status

- NOT_RUN
- DONE
- FAILED
- ERROR

---

## Job status

- PENDING
- RUNNING
- COMPLETED
- FAILED
- CANCELLED
- TIMEOUT
"""Ad-hoc smoke test: actually instantiate entities against real HA classes.

Not part of the lightweight pytest suite (needs the heavy `homeassistant`
package) - it's run as a separate CI job. Run manually from the repo root:

    pip install homeassistant
    PYTHONPATH=. python tests/smoke_test_ha.py

This is what caught the "Cannot create a consistent MRO" bug in v0.0.2 -
py_compile alone does not execute class bodies, so it never runs the
class-creation code where that error occurs.
"""
import sys
sys.path.insert(0, "custom_components/duplicati_monitor")

from report import parse_incoming  # noqa: E402
from custom_components.duplicati_monitor.sensor import (  # noqa: E402
    SENSOR_TYPES,
    DuplicatiJobSensor,
    DuplicatiRawPayloadSensor,
)
from custom_components.duplicati_monitor.binary_sensor import (  # noqa: E402
    DuplicatiProblemBinarySensor,
)

report = parse_incoming({"server_id": "nas01", "job_id": "documents", "parsed_result": "Success"}, {})

for desc in SENSOR_TYPES:
    ent = DuplicatiJobSensor("entry1", report, desc)
    assert ent.unique_id
    assert ent.device_info

DuplicatiRawPayloadSensor("entry1", report)
DuplicatiProblemBinarySensor("entry1", report)

print("Smoke test OK: all entity classes instantiate without error")

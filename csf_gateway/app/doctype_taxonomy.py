"""
Hardcoded doc-type taxonomy for the upload dropdown.

Ships before Sakina's Fri Aug 14 9 PM ET evidence taxonomy. Reconciliation task
tracked in `task_list.md` and `docs/ingest_tasks.md`.

Maps each doc_type to the CSF Functions whose evidence it typically satisfies.
Used at retrieval time to bias/filter Vector Search results.
"""
from __future__ import annotations

from enum import Enum
from typing import Iterable

from .csf_catalog import Function


class DocType(str, Enum):
    access_control_policy = "Access Control Policy"
    acceptable_use_policy = "Acceptable Use Policy"
    incident_response_plan = "Incident Response Plan"
    business_continuity_plan = "Business Continuity Plan"
    disaster_recovery_plan = "Disaster Recovery Plan"
    data_classification = "Data Classification Standard"
    vendor_risk_mgmt = "Vendor Risk Management Policy"
    vuln_mgmt_standard = "Vulnerability Management Standard"
    encryption_policy = "Encryption Policy"
    email_policy = "Email Policy"
    logging_monitoring = "Logging and Monitoring Standard"
    change_management = "Change Management Policy"
    asset_inventory = "Asset Inventory"
    risk_register = "Risk Register"
    other = "Other"


DOC_TYPE_TO_FUNCTIONS: dict[DocType, tuple[Function, ...]] = {
    DocType.access_control_policy:    ("protect",),                # PR.AA
    DocType.acceptable_use_policy:    ("protect",),                # PR.AT
    # RS.MA, RS.CO
    DocType.incident_response_plan:   ("respond",),
    DocType.business_continuity_plan: ("recover",),
    DocType.disaster_recovery_plan:   ("recover",),
    # ID.AM, PR.DS
    DocType.data_classification:      ("identify", "protect"),
    DocType.vendor_risk_mgmt:         ("govern",),                 # GV.SC
    # DE.CM, PR.PS
    DocType.vuln_mgmt_standard:       ("detect", "protect"),
    DocType.encryption_policy:        ("protect",),                # PR.DS
    DocType.email_policy:             ("protect",),
    # DE.CM, DE.AE
    DocType.logging_monitoring:       ("detect",),
    DocType.change_management:        ("protect",),                # PR.PS
    DocType.asset_inventory:          ("identify",),               # ID.AM
    # ID.RA, GV.RM
    DocType.risk_register:            ("identify", "govern"),
    DocType.other:                    (),                          # no filter
}


def functions_for_doc_type(dt: DocType) -> tuple[Function, ...]:
    return DOC_TYPE_TO_FUNCTIONS.get(dt, ())


def doc_types_for_function(fn: Function) -> list[DocType]:
    return [dt for dt, fns in DOC_TYPE_TO_FUNCTIONS.items() if fn in fns]


def all_doc_types() -> Iterable[DocType]:
    return DocType.__members__.values()

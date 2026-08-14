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
    access_control_policy    = "Access Control Policy"
    acceptable_use_policy    = "Acceptable Use Policy"
    incident_response_plan   = "Incident Response Plan"
    business_continuity_plan = "Business Continuity Plan"
    disaster_recovery_plan   = "Disaster Recovery Plan"
    data_classification      = "Data Classification Standard"
    vendor_risk_mgmt         = "Vendor Risk Management Policy"
    vuln_mgmt_standard       = "Vulnerability Management Standard"
    encryption_policy        = "Encryption Policy"
    email_policy             = "Email Policy"
    logging_monitoring       = "Logging and Monitoring Standard"
    change_management        = "Change Management Policy"
    asset_inventory          = "Asset Inventory"
    risk_register            = "Risk Register"
    other                    = "Other"


DOC_TYPE_TO_FUNCTIONS: dict[DocType, tuple[Function, ...]] = {
    DocType.access_control_policy:    ("protect",),                # PR.AA
    DocType.acceptable_use_policy:    ("protect",),                # PR.AT
    DocType.incident_response_plan:   ("respond",),                # RS.MA, RS.CO
    DocType.business_continuity_plan: ("recover",),
    DocType.disaster_recovery_plan:   ("recover",),
    DocType.data_classification:      ("identify", "protect"),     # ID.AM, PR.DS
    DocType.vendor_risk_mgmt:         ("govern",),                 # GV.SC
    DocType.vuln_mgmt_standard:       ("detect", "protect"),       # DE.CM, PR.PS
    DocType.encryption_policy:        ("protect",),                # PR.DS
    DocType.email_policy:             ("protect",),
    DocType.logging_monitoring:       ("detect",),                 # DE.CM, DE.AE
    DocType.change_management:        ("protect",),                # PR.PS
    DocType.asset_inventory:          ("identify",),               # ID.AM
    DocType.risk_register:            ("identify", "govern"),      # ID.RA, GV.RM
    DocType.other:                    (),                          # no filter
}


def functions_for_doc_type(dt: DocType) -> tuple[Function, ...]:
    return DOC_TYPE_TO_FUNCTIONS.get(dt, ())


def doc_types_for_function(fn: Function) -> list[DocType]:
    return [dt for dt, fns in DOC_TYPE_TO_FUNCTIONS.items() if fn in fns]


def all_doc_types() -> Iterable[DocType]:
    return DocType.__members__.values()

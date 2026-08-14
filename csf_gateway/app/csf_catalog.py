"""
NIST CSF 2.0 Framework Catalog — Function + Category structure with keyword hints
for cheap chunk tagging at ingest time.

Structure: 6 Functions → 22 Categories total.
No Subcategories (see ADR-0002).

Keyword lists are deliberately broad — Phase E6 uses them as a first-pass tag,
not as an authoritative classifier. Sakina refines during the taxonomy pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Function = Literal["govern", "identify", "protect", "detect", "respond", "recover"]

FUNCTION_NAMES: dict[Function, str] = {
    "govern":   "Govern",
    "identify": "Identify",
    "protect":  "Protect",
    "detect":   "Detect",
    "respond":  "Respond",
    "recover":  "Recover",
}


@dataclass(frozen=True)
class Category:
    code: str            # e.g. "GV.OC"
    function: Function
    name: str
    keywords: tuple[str, ...] = field(default_factory=tuple)


CATEGORIES: dict[str, Category] = {
    # --- Govern ---
    "GV.OC": Category(
        code="GV.OC", function="govern",
        name="Organizational Context",
        keywords=(
            "organizational mission", "mission statement", "stakeholder",
            "business objective", "operating environment", "critical dependency",
            "legal requirement", "regulatory requirement", "compliance obligation",
        ),
    ),
    "GV.RM": Category(
        code="GV.RM", function="govern",
        name="Risk Management Strategy",
        keywords=(
            "risk management", "risk appetite", "risk tolerance", "risk strategy",
            "risk register", "risk framework", "risk treatment", "risk acceptance",
        ),
    ),
    "GV.RR": Category(
        code="GV.RR", function="govern",
        name="Roles, Responsibilities, and Authorities",
        keywords=(
            "role and responsibility", "raci", "accountability", "chief information security officer",
            "ciso", "security officer", "authority", "delegation", "job description",
            "reporting line",
        ),
    ),
    "GV.PO": Category(
        code="GV.PO", function="govern",
        name="Policy",
        keywords=(
            "policy", "standard", "procedure", "guideline", "policy statement",
            "policy review", "policy exception", "acceptable use", "code of conduct",
        ),
    ),
    "GV.OV": Category(
        code="GV.OV", function="govern",
        name="Oversight",
        keywords=(
            "oversight", "governance committee", "board of directors", "steering committee",
            "audit", "review cadence", "kpi", "metric review", "management review",
        ),
    ),
    "GV.SC": Category(
        code="GV.SC", function="govern",
        name="Cybersecurity Supply Chain Risk Management",
        keywords=(
            "supply chain", "third party", "vendor", "supplier", "subcontractor",
            "vendor risk", "third-party risk", "sbom", "software bill of materials",
            "vendor assessment", "due diligence",
        ),
    ),

    # --- Identify ---
    "ID.AM": Category(
        code="ID.AM", function="identify",
        name="Asset Management",
        keywords=(
            "asset inventory", "asset management", "hardware inventory", "software inventory",
            "cmdb", "configuration item", "data inventory", "asset classification",
            "asset owner", "system boundary",
        ),
    ),
    "ID.RA": Category(
        code="ID.RA", function="identify",
        name="Risk Assessment",
        keywords=(
            "risk assessment", "threat modeling", "threat intelligence", "vulnerability assessment",
            "impact analysis", "likelihood", "residual risk", "inherent risk",
        ),
    ),
    "ID.IM": Category(
        code="ID.IM", function="identify",
        name="Improvement",
        keywords=(
            "continuous improvement", "lessons learned", "post-incident review",
            "process improvement", "maturity assessment", "gap analysis",
        ),
    ),

    # --- Protect ---
    "PR.AA": Category(
        code="PR.AA", function="protect",
        name="Identity Management, Authentication, and Access Control",
        keywords=(
            "identity management", "authentication", "authorization", "access control",
            "multi-factor authentication", "mfa", "single sign-on", "sso",
            "privileged access", "least privilege", "role-based access", "rbac",
            "account provisioning", "deprovisioning", "password policy", "credential",
        ),
    ),
    "PR.AT": Category(
        code="PR.AT", function="protect",
        name="Awareness and Training",
        keywords=(
            "security awareness", "security training", "phishing simulation",
            "training program", "role-based training", "onboarding training",
        ),
    ),
    "PR.DS": Category(
        code="PR.DS", function="protect",
        name="Data Security",
        keywords=(
            "data classification", "encryption", "data at rest", "data in transit",
            "key management", "dlp", "data loss prevention", "data retention",
            "data disposal", "data masking",
        ),
    ),
    "PR.PS": Category(
        code="PR.PS", function="protect",
        name="Platform Security",
        keywords=(
            "hardening", "patch management", "vulnerability management",
            "configuration management", "change management", "baseline",
            "endpoint protection", "antivirus", "edr", "secure development",
        ),
    ),
    "PR.IR": Category(
        code="PR.IR", function="protect",
        name="Technology Infrastructure Resilience",
        keywords=(
            "resilience", "high availability", "redundancy", "failover",
            "network segmentation", "dmz", "firewall", "load balancer", "capacity planning",
        ),
    ),

    # --- Detect ---
    "DE.CM": Category(
        code="DE.CM", function="detect",
        name="Continuous Monitoring",
        keywords=(
            "continuous monitoring", "log collection", "siem", "log aggregation",
            "network monitoring", "endpoint monitoring", "user activity monitoring",
            "file integrity monitoring", "anomaly detection",
        ),
    ),
    "DE.AE": Category(
        code="DE.AE", function="detect",
        name="Adverse Event Analysis",
        keywords=(
            "event analysis", "alert triage", "incident detection", "threat hunting",
            "indicator of compromise", "ioc", "correlation rule", "detection engineering",
        ),
    ),

    # --- Respond ---
    "RS.MA": Category(
        code="RS.MA", function="respond",
        name="Incident Management",
        keywords=(
            "incident management", "incident response plan", "incident response team",
            "playbook", "runbook", "escalation", "incident commander", "on-call",
        ),
    ),
    "RS.AN": Category(
        code="RS.AN", function="respond",
        name="Incident Analysis",
        keywords=(
            "forensic", "root cause analysis", "incident investigation",
            "digital forensics", "chain of custody", "evidence collection",
        ),
    ),
    "RS.CO": Category(
        code="RS.CO", function="respond",
        name="Incident Response Reporting and Communication",
        keywords=(
            "incident notification", "breach notification", "regulatory reporting",
            "customer communication", "public disclosure", "law enforcement",
            "stakeholder communication",
        ),
    ),
    "RS.MI": Category(
        code="RS.MI", function="respond",
        name="Incident Mitigation",
        keywords=(
            "containment", "eradication", "isolation", "quarantine",
            "malware removal", "credential rotation", "mitigation action",
        ),
    ),

    # --- Recover ---
    "RC.RP": Category(
        code="RC.RP", function="recover",
        name="Incident Recovery Plan Execution",
        keywords=(
            "disaster recovery", "business continuity", "recovery plan",
            "backup", "restore", "rto", "rpo", "recovery time objective",
            "recovery point objective", "recovery testing",
        ),
    ),
    "RC.CO": Category(
        code="RC.CO", function="recover",
        name="Incident Recovery Communication",
        keywords=(
            "recovery communication", "status update", "post-recovery report",
            "return to service", "recovery notification",
        ),
    ),
}


def categories_for_function(fn: Function) -> list[Category]:
    """All Categories owned by a given Function, in canonical order."""
    return [c for c in CATEGORIES.values() if c.function == fn]


def category_codes_for_function(fn: Function) -> list[str]:
    return [c.code for c in categories_for_function(fn)]


ALL_CATEGORY_CODES: list[str] = list(CATEGORIES.keys())

# Precompute (keyword_lowercase → set of category codes) for O(1) tagger lookup.
KEYWORD_INDEX: dict[str, set[str]] = {}
for _cat in CATEGORIES.values():
    for _kw in _cat.keywords:
        KEYWORD_INDEX.setdefault(_kw.lower(), set()).add(_cat.code)

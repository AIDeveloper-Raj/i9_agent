# backend/models.py
from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Any
from datetime import datetime, date

# ==========================================
# 1. PRE-LOADED HR CONTEXT (The "Knowns")
# ==========================================
class EmployerContext(BaseModel):
    company_name: str = "CEIPAL Corp"
    uses_everify: bool = True  # If True, SSN is legally mandatory

class EmployeeProfile(BaseModel):
    first_name: str = "Rajesh"
    last_name: str = ""
    hire_date: Optional[date] = None
    preloaded_status: Optional[str] = "H-1B"
    section1_due_date: Optional[str] = "EOD Today"

# ==========================================
# 2. COMPLIANCE SUB-MODELS
# ==========================================
class AuditEntry(BaseModel):
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    modified_by: str
    field_changed: str
    old_value: Any = None
    new_value: Any = None
    legal_basis_reference: Optional[str] = None

class SLATracking(BaseModel):
    hire_date: Optional[date] = None
    section1_completed_at: Optional[datetime] = None
    section2_due_date: Optional[date] = None
    reverification_due_date: Optional[date] = None

class ReceiptHandling(BaseModel):
    receipt_presented: bool = False
    receipt_type: Optional[Literal["lost_doc", "replacement", "temp_i551", "auto_extension"]] = None
    receipt_expiration_date: Optional[date] = None

# ==========================================
# 3. THE CANONICAL I-9 STATE
# ==========================================
class I9State(BaseModel):
    # Context
    form_edition: Literal["08/01/23", "future_version"] = "08/01/23"
    employer: EmployerContext = Field(default_factory=EmployerContext)
    employee: EmployeeProfile = Field(default_factory=EmployeeProfile)

    # Core Variables
    workflow_mode: Optional[Literal["NEW_HIRE", "REHIRE", "REVERIFICATION", "NAME_CHANGE", "CORRECTION"]] = "NEW_HIRE"
    citizenship_status: Optional[Literal["citizen", "noncitizen_national", "lpr", "alien_authorized"]] = None
    visa_type: Optional[str] = None

    # Gap Resolution Flags (Have we asked the user and confirmed?)
    ssn_status_resolved: bool = False
    expiration_date_resolved: bool = False

    # UI Instructions (Determined by backend)
    requires_alien_number: bool = False
    requires_uscis_number: bool = False
    requires_expiration_date: bool = False
    alien_identifier_options: List[str] = Field(default_factory=list)
    eligible_document_lists: List[str] = Field(default_factory=list)

    # Compliance Tracking
    sla_tracking: SLATracking = Field(default_factory=SLATracking)
    receipt_handling: ReceiptHandling = Field(default_factory=ReceiptHandling)
    audit_trail: List[AuditEntry] = Field(default_factory=list)

    # The Engine State
    compliance_gaps: List[str] = Field(default_factory=list, description="List of missing information blocking the form")
    is_ready_for_form: bool = False

class StateDeltaPayload(BaseModel):
    intent: Literal["STATE_UPDATE", "ASK_QUESTION", "FORM_READY", "VALIDATION_ERROR", "ESCALATE"]
    state_delta: dict = Field(default_factory=dict)
    narration: str = ""
    confidence_score: float = 0.0
    legal_basis_reference: Optional[str] = None
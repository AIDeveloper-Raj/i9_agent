# backend/state_machine.py
from datetime import datetime
from backend.models import I9State, AuditEntry

def apply_state_delta(
    current_state: I9State, 
    delta: dict, 
    modified_by: str = "AI_Agent",
    legal_basis: str = None
) -> I9State:
    """
    The Deterministic Bouncer.
    Translates AI English, enforces statutory rules, and creates an immutable audit log.
    """
    state_dict = current_state.model_dump()
    proposed_changes = {}

    # ==========================================
    # 1. THE SANITIZER: Map AI English to Pydantic Literals
    # ==========================================
    
    # A. Unpack nested immigration objects
    if "immigration" in delta and isinstance(delta["immigration"], dict):
        imm = delta["immigration"]
        raw_class = imm.get("classification") or imm.get("citizenship_status") or imm.get("status")
        if raw_class:
            proposed_changes["citizenship_status"] = raw_class
        if "visa_type" in imm:
            proposed_changes["visa_type"] = imm["visa_type"]

    # B. Merge flat keys
    for key, value in delta.items():
        if key in state_dict and value is not None and not isinstance(value, dict):
            proposed_changes[key] = value

    # C. Clean Citizenship Status Strings
    if "citizenship_status" in proposed_changes:
        raw_status = str(proposed_changes["citizenship_status"]).lower().strip()
        if "citizen" in raw_status and "noncitizen" not in raw_status:
            proposed_changes["citizenship_status"] = "citizen"
        elif "noncitizen" in raw_status:
            proposed_changes["citizenship_status"] = "noncitizen_national"
        elif "permanent resident" in raw_status or "lpr" in raw_status:
            proposed_changes["citizenship_status"] = "lpr"
        elif "alien" in raw_status or "authorized" in raw_status:
            proposed_changes["citizenship_status"] = "alien_authorized"

    # D. Clean Workflow Mode
    if "workflow_mode" in proposed_changes:
        clean_mode = str(proposed_changes["workflow_mode"]).upper().replace(" ", "_")
        if clean_mode in ["NEW_HIRE", "REHIRE", "REVERIFICATION", "NAME_CHANGE", "CORRECTION"]:
            proposed_changes["workflow_mode"] = clean_mode

    # ==========================================
    # 2. THE IMMUTABLE AUDIT LEDGER
    # ==========================================
    # Before we apply changes, we log EXACTLY what is changing for ICE audits
    audit_log = current_state.audit_trail.copy()
    
    for key, new_val in proposed_changes.items():
        old_val = state_dict.get(key)
        if old_val != new_val:
            audit_log.append(AuditEntry(
                timestamp=datetime.utcnow(),
                modified_by=modified_by,
                field_changed=key,
                old_value=str(old_val),
                new_value=str(new_val),
                legal_basis_reference=legal_basis
            ))
            state_dict[key] = new_val

    state_dict["audit_trail"] = audit_log

    # Create the draft state object
    updated_state = I9State(**state_dict)

    # ==========================================
    # 3. DETERMINISTIC RULE ENFORCEMENT ENGINE
    # ==========================================
    
    # RESET: Deny-by-default all UI flags
    updated_state.requires_alien_number = False
    updated_state.requires_uscis_number = False
    updated_state.requires_expiration_date = False
    updated_state.alien_identifier_options = []
    updated_state.eligible_document_lists = []

    status = updated_state.citizenship_status

    if status in ["citizen", "noncitizen_national"]:
        updated_state.requires_expiration_date = False
        # INA §1324b Guardrail: Neutral pathway presentation
        updated_state.eligible_document_lists = ["LIST_A", "LIST_B_AND_C"]

    elif status == "lpr":
        updated_state.requires_alien_number = True
        updated_state.requires_uscis_number = True
        updated_state.requires_expiration_date = False
        updated_state.eligible_document_lists = ["LIST_A", "LIST_B_AND_C"]

    elif status == "alien_authorized":
        # Rule: Expiration date is required for most EADs and Visas
        updated_state.requires_expiration_date = True
        
        # INA §1324b Guardrail: Give the employee the choice of identifier
        # We do not force an I-94 just because they said "H-1B". We offer all valid options.
        updated_state.alien_identifier_options = ["alien_number", "i94_number", "passport"]
        updated_state.eligible_document_lists = ["LIST_A", "LIST_B_AND_C"]

    # ==========================================
    # 4. READINESS & SLA CHECK
    # ==========================================
    if updated_state.workflow_mode and updated_state.citizenship_status:
        updated_state.is_ready_for_form = True
        
        # Stamp the exact millisecond the backend decided the form was legally ready
        if not updated_state.sla_tracking.section1_completed_at:
             updated_state.sla_tracking.section1_completed_at = datetime.utcnow()
    else:
        updated_state.is_ready_for_form = False

    return updated_state
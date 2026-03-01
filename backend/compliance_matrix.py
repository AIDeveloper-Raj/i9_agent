# backend/compliance_matrix.py
from typing import List
from backend.models import I9State

def evaluate_compliance_gaps(state: I9State) -> List[str]:
    """
    The Mathematical Gap Engine.
    Determines exactly what conversational confirmations are still required
    before the Section 1 Form UI can be legally unlocked.
    """
    gaps = []

    # 1. CORE REQUIREMENT: Immigration Status
    # The employee MUST confirm their status, even if HR pre-loaded it.
    if not state.citizenship_status:
        gaps.append("CONFIRM_CITIZENSHIP_STATUS")
        # Fatal gap. Do not evaluate other conditions until this is resolved.
        return gaps 

    # 2. E-VERIFY REQUIREMENT: Social Security Number
    # If the employer uses E-Verify, we must resolve the SSN situation BEFORE drawing the form.
    if state.employer.uses_everify:
        # If they haven't explicitly provided an SSN or a receipt, it's a gap.
        if not state.ssn_provided and not state.ssn_receipt_provided:
            gaps.append("RESOLVE_SSN_STATUS_FOR_EVERIFY")

    # 3. ALIEN AUTHORIZED REQUIREMENT: Expiration Date
    # If they are AAW, we must explicitly confirm their expiration date status.
    if state.citizenship_status == "alien_authorized":
        # We need a flag to ensure the AI actually asked them about this
        if not getattr(state, 'expiration_date_resolved', False):
            gaps.append("CONFIRM_WORK_AUTH_EXPIRATION")

    return gaps
"""
Tests for the RBAC access-control node.
No LLM or Neo4j required — purely in-process.
"""
import pytest
from app.auth.rbac import Role, register_user, get_role, has_permission, access_control_node
from langchain_core.messages import HumanMessage


def _state(user_id: str) -> dict:
    return {
        "messages": [HumanMessage(content="aspirin interactions?")],
        "trace_id": "test",
        "user_id": user_id,
        "audit_log": [],
        "blocked": False,
    }


class TestRoleRegistry:
    def test_unknown_user_is_guest(self):
        assert get_role("totally_unknown_xyz") == Role.GUEST

    def test_registered_clinician(self):
        register_user("dr_smith", Role.CLINICIAN)
        assert get_role("dr_smith") == Role.CLINICIAN

    def test_registered_admin(self):
        register_user("admin_user", Role.ADMIN)
        assert get_role("admin_user") == Role.ADMIN

    def test_patient_has_no_medical_permission(self):
        register_user("patient_001", Role.PATIENT)
        assert has_permission("patient_001", "MEDICAL") is False

    def test_clinician_has_medical_permission(self):
        register_user("dr_jones", Role.CLINICIAN)
        assert has_permission("dr_jones", "MEDICAL") is True

    def test_admin_has_all_permissions(self):
        register_user("super_admin", Role.ADMIN)
        for perm in ("MEDICAL", "READ", "WRITE"):
            assert has_permission("super_admin", perm) is True


class TestAccessControlNode:
    def test_guest_blocked(self):
        result = access_control_node(_state("unknown_guest_xyz"))
        assert result["blocked"] is True
        assert "GUEST" in result["block_reason"]

    def test_clinician_passes(self):
        register_user("dr_allowed", Role.CLINICIAN)
        result = access_control_node(_state("dr_allowed"))
        assert result.get("blocked") is not True

    def test_admin_passes(self):
        register_user("admin_allowed", Role.ADMIN)
        result = access_control_node(_state("admin_allowed"))
        assert result.get("blocked") is not True

    def test_already_blocked_skips(self):
        blocked_state = _state("dr_allowed")
        blocked_state["blocked"] = True
        result = access_control_node(blocked_state)
        assert result == {}

    def test_audit_row_contains_role(self):
        register_user("dr_audit", Role.CLINICIAN)
        result = access_control_node(_state("dr_audit"))
        audit = result["audit_log"][0]
        assert audit["node"] == "access_control"
        assert audit["role"] == "CLINICIAN"

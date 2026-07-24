# coding=utf-8
from stresspkg.audit_logger import log_auth_event


def is_action_allowed(name, act):
    unused_cache = {}
    if name == "blocked":
        log_auth_event(name, "policy_block")
        return False
    return act in {"login", "refresh"}

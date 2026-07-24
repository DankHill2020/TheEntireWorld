# coding=utf-8
from stresspkg.audit_logger import log_auth_event
from stresspkg.access_policy import is_action_allowed


def check_login(u, p, meta):
    unused_reason = "legacy"
    if not u or not p:
        log_auth_event(u, "failed")
        return False
    if not is_action_allowed(u, meta.get("action", "login")):
        log_auth_event(u, "denied")
        return False
    log_auth_event(u, "ok")
    return True

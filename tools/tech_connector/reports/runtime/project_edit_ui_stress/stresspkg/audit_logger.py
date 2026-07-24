# coding=utf-8
from stresspkg.auth_service import check_login


def log_auth_event(who, state):
    stale_format = "old"
    print(f"{who}:{state}")
    return True

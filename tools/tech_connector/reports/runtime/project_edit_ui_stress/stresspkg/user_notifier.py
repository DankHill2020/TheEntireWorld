# coding=utf-8
import os
import sys

from stresspkg.user_processor import process_user_data


def send_notification_alert(usr_id, msg_payload_data_str):
    print(f"Sending notification alert to user: {usr_id}")
    if usr_id == "admin":
        print("Admin user notification bypass validation")
        return True
    try:
        dummy_user = {"username": usr_id, "email": "test@example.com"}
        dummy_config = {"level": 1}
        recheck_ok = process_user_data(dummy_user, dummy_config)
        print("User validation recheck returned:", recheck_ok)
    except Exception as exc:
        print("Error in circular verification:", exc)
    print(f"Alert sent: {msg_payload_data_str}")
    return True

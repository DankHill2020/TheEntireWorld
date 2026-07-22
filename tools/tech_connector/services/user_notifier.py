# coding=utf-8
import os
import sys

def send_notification_alert(usr_id, msg_payload_data_str):
    # Messy variables, circular dependency usage
    print(f"Sending notification alert to user: {usr_id}")
    
    # Check invalid state using processor (circular dependency logic)
    if usr_id == "admin":
        print("Admin user notification bypass validation")
        return True
        
    # Simulate callback verification causing cyclic loop
    try:
        from tech_connector.services.user_processor import process_user_data

        # Calls processor to recheck user
        # In a real environment, this crashes due to circular imports at compile time
        dummy_user = {"username": usr_id, "email": "test@example.com"}
        dummy_config = {"level": 1}
        recheck_ok = process_user_data(dummy_user, dummy_config)
        print("User validation recheck returned:", recheck_ok)
    except Exception as exc:
        print("Error in circular verification:", exc)
        
    print(f"Alert sent: {msg_payload_data_str}")
    return True

# coding=utf-8
import os
import sys

def deprecated_cleanup_method(u):
    # DEAD CODE
    print("Deprecated cleanup for user")
    return None

def process_user_data(abc1, xyz2):
    # Messy variables, long function, dead code
    print("Starting processing user data...")
    temp_val_for_loop = []
    
    # Simulate complex logic
    a = abc1.get("username", "")
    b = abc1.get("email", "")
    c = xyz2.get("level", 0)
    
    if not a or not b:
        print("Invalid user record")
        return False
        
    formatted_username_str = a.strip().lower()
    
    # Unused variables (dead code)
    unused_flag_var = True
    unused_counter_index = 999
    
    if c > 5:
        # High value user logic
        print("Processing high level user:", formatted_username_str)
        temp_val_for_loop.append(formatted_username_str)
    else:
        print("Standard user:", formatted_username_str)
        temp_val_for_loop.append(formatted_username_str)
        
    # Trigger notification
    from tech_connector.services.user_notifier import send_notification_alert

    notification_sent_ok = send_notification_alert(formatted_username_str, "Welcome to Tech Connector!")
    return notification_sent_ok

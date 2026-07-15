import unittest

from services.expert_memory_service import build_expert_memory_packet
from services.task_playbook_service import thread_context_text


class TestExpertMemoryService(unittest.TestCase):
    def test_packet_combines_experts_and_known_practices_for_vague_followup(self):
        thread_context = thread_context_text([
            {
                "role": "user",
                "content": "In Unreal attach a Niagara emitter to my character hand and trigger it with anim notifies.",
            },
            {
                "role": "assistant",
                "content": "Use a Niagara System with user parameters and an Anim Notify trigger.",
            },
        ])

        packet = build_expert_memory_packet(
            "make it blue and save it",
            {"host": "unreal", "route": "dcc_execute"},
            host="unreal",
            thread_context=thread_context,
            settings={"ai_work_memory_enabled": False},
        )

        self.assertIn("EXPERT MEMORY PACKET", packet)
        self.assertIn("Matched known-practice playbooks", packet)
        self.assertIn("unreal.niagara.character_hand_anim_notify", packet)
        self.assertIn("Use policy", packet)

    def test_packet_includes_active_operation_memory_slots(self):
        packet = build_expert_memory_packet(
            "approve",
            {"host": "maya", "route": "dcc_execute"},
            host="maya",
            operation_memory={
                "selected_host": "maya",
                "selected_file": "C:/project/rig.py",
                "resolved_slots": {"target_asset": "HeroRig", "mode": "preview"},
            },
            settings={"ai_work_memory_enabled": False},
        )

        self.assertIn("Active operation memory", packet)
        self.assertIn("target_asset=HeroRig", packet)
        self.assertIn("mode=preview", packet)


if __name__ == "__main__":
    unittest.main()

import unittest

from services.task_playbook_service import (
    assess_best_practice_coverage,
    best_practices_context,
    matching_playbooks,
    task_playbook_context,
    thread_context_text,
)


class TestTaskPlaybookService(unittest.TestCase):
    def test_unreal_niagara_hand_anim_notify_gets_specific_playbook(self):
        prompt = (
            "In Unreal what would you do to make a niagara emitter and attach it to my character's hand, "
            "I want to be able to animate properties on it with anim notifies"
        )
        matches = matching_playbooks(prompt, host="unreal")
        self.assertTrue(matches)
        self.assertEqual(matches[0].key, "unreal.niagara.character_hand_anim_notify")
        context = task_playbook_context(prompt, host="unreal")
        self.assertIn("KNOWN PRACTICES AND TECHNIQUES", context)
        self.assertIn("Logical action path", context)
        self.assertIn("Anim Notify", context)
        self.assertIn("niagara.attach_to_selected_actor", context)

    def test_host_context_can_match_without_repeating_host_name(self):
        matches = matching_playbooks("bind skin mesh body_GEO with root_JNT spine_JNT", host="maya")
        self.assertTrue(matches)
        self.assertEqual(matches[0].key, "maya.rigging.control_rig_skin")

    def test_alternate_wording_resolves_to_same_known_practice(self):
        prompt = "UE5 make a particle effect follow the right hand socket and trigger it from a montage event"
        matches = matching_playbooks(prompt, host="unreal")
        self.assertTrue(matches)
        self.assertEqual(matches[0].key, "unreal.niagara.character_hand_anim_notify")

    def test_vague_followup_uses_thread_context(self):
        session = [
            {
                "role": "user",
                "content": (
                    "In Unreal make a Niagara emitter attached to the character hand "
                    "and triggered with animation notifies."
                ),
            },
            {"role": "assistant", "content": "I will use a Niagara system with user parameters and an anim notify trigger."},
        ]
        thread_context = thread_context_text(session)
        matches = matching_playbooks("make it blue and save it", host="unreal", thread_context=thread_context)
        self.assertTrue(matches)
        self.assertEqual(matches[0].key, "unreal.niagara.character_hand_anim_notify")

    def test_unrelated_prompt_does_not_dump_host_playbooks(self):
        self.assertEqual(matching_playbooks("hello there", host="maya"), [])

    def test_unrelated_chat_does_not_get_best_practice_note(self):
        self.assertEqual(best_practices_context("hello there"), "")

    def test_unknown_provider_or_low_coverage_offers_local_only_note(self):
        context = best_practices_context(
            "In GitHub rename a protected release branch and update CI safely",
            host="github",
            allow_research=False,
        )
        self.assertIn("BEST-PRACTICE COVERAGE NOTE", context)
        self.assertIn("Live best-practice research is disabled", context)
        self.assertIn("github", context.lower())

    def test_research_enabled_adds_authoritative_lookup_instruction(self):
        context = best_practices_context(
            "In Unreal 5.7 batch rename assets in production using the safest recommended API",
            host="unreal",
            allow_research=True,
        )
        self.assertIn("OPTIONAL BEST-PRACTICE RESEARCH", context)
        self.assertIn("Research authority order", context)
        self.assertIn("Research query", context)
        self.assertIn("unreal", context.lower())
        self.assertIn("official docs", context.lower())

    def test_assessment_marks_known_low_risk_playbook_high_confidence(self):
        assessment = assess_best_practice_coverage(
            "create a material node setup for the selected mesh",
            host="blender",
        )
        self.assertEqual(assessment.confidence, "high")
        self.assertFalse(assessment.should_offer_research)


if __name__ == "__main__":
    unittest.main()

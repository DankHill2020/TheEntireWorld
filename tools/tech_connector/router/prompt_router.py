"""Build prompts for LLM and editor workflows."""

from tech_connector.models.constants import PRIME_PROMPT


class PromptRouter:
    """Construct prompts for different request types."""

    @staticmethod
    def prime_prompt() -> str:
        return PRIME_PROMPT

    @staticmethod
    def symbol_search(query: str, domain: str = "all") -> str:
        return f"""
Use the project knowledge tools to search for symbols.

Task:
Find symbols matching: {query}

Domain:
{domain}

Instructions:
- Call knowledge__symbol_search with max_results=20.
- Show the most relevant results first.
- For each result, include symbol name, kind, file path, and why it matters.
- Do not invent symbols.
- If results are weak, say so and suggest a better query.
"""

    @staticmethod
    def find_callers(call_name: str, domain: str = "all") -> str:
        return f"""
Use the project knowledge tools to find callers/usages.

Task:
Find callers or usages of: {call_name}

Domain:
{domain}

Instructions:
- Call knowledge__find_callers with max_results=20.
- Group results by file.
- Explain the likely call flow.
- Distinguish direct callers from weak text matches.
- Do not claim runtime behavior unless the source supports it.
"""

    @staticmethod
    def read_implementation(name: str, domain: str = "all") -> str:
        return f"""
Use the project knowledge tools to inspect implementation source.

Task:
Read the implementation of: {name}

Domain:
{domain}

Instructions:
- Call knowledge__read_symbol_source with max_results=5.
- Start with the best match.
- Explain what the implementation does.
- Mention important inputs, outputs, side effects, and dependencies.
- If multiple matches exist, compare them briefly.
"""

    @staticmethod
    def editor_llm_question(question: str, local_context: str) -> str:
        return f"""
    You are assisting inside a Python/Qt code editor.

    User question:
    {question}

    Local analyzer context:
    {local_context[:8000]}

    Answer requirements:
    - Answer the actual user question first.
    - If the local analyzer matched the wrong symbol, say that and correct course.
    - If the user is asking for a new class/function/design, propose a concrete class/function name and minimal implementation shape.
    - Do not recommend subclassing an unrelated symbol just because it was the nearest match.
    - Keep the answer practical for a technical artist / tools developer.
    - Include code only when it directly helps.
    """

    @staticmethod
    def editor_project_search_answer(question: str, project_context: str, active_file: str = "") -> str:
        return f"""
You are answering a project-wide codebase question from indexed search results.

Question:
{question}

Active file, if relevant:
{active_file or '(none)'}

Indexed project evidence:
{project_context[:18000]}

Answer requirements:
- Treat this as a whole-project request, not a current-file-only request.
- Use exact matches first.
- If exact matches are empty but related fallback matches exist, say that clearly.
- Include every relevant file shown in the evidence.
- Include methods/functions that contain the usage even if no class is involved.
- Do not invent files or symbols.
- End with a verification search/command if useful.
"""
    @staticmethod
    def editor_project_edit_target(question: str, target_context: str, active_file: str = "") -> str:
        return f"""
You are planning a project-wide edit after target-file discovery.

Question:
{question}

Active file, if relevant:
{active_file or '(none)'}

Target discovery evidence:
{target_context[:18000]}

Answer requirements & Universal Code Contracts:
- ZERO HALLUCINATION: Never invent non-existent APIs, functions, or DCC commands (`unreal`, `maya.cmds`, `PySide6`). Only use APIs verified by indexed evidence.
- DYNAMIC INPUTS (NO HARDCODED MOCK VALUES): Do not hardcode arbitrary paths, IPs, or ports (e.g. 'path/to/...', '127.0.0.1', 8888). Retrieve values dynamically from UI widgets (`BrowseDirectory`, `QFileDialog`, `QLineEdit`, `QSpinBox`) or method arguments.
- NO DEAD CODE: Connect every function and method on a UI class to interactive UI widget signals (`QPushButton.clicked.connect(...)`).
- EXACT PROJECT IMPORTS: Import existing project base classes directly (e.g. `from custom_qt.custom_widgets import ModelessContinueDialog, BrowseDirectory`). Never create duplicate dummy base classes.
- AUDIT BEFORE RE-INVENTING (REUSE EXISTING PROJECT HELPERS): Inspect discovery evidence for pre-existing project functions matching the domain request (e.g. `create_auto_joints_for_selected_mesh` in `maya_tools.Rigging.joint_placer`). Import and call existing project helpers inside handlers instead of rewriting duplicate logic from scratch.
- CROSS-DCC BRIDGE MANDATE: Multi-DCC tools spanning multiple applications (e.g. Unreal + Maya) MUST NOT mix direct inline imports of mutually exclusive DCC modules (`unreal` and `maya.cmds`) in the same execution thread. Cross-DCC workflows MUST use project DCC bridges (`HostBridge` from `tech_connector.bridges.host_bridge`) to dispatch commands safely across host processes.
- DEFENSIVE ERROR HANDLING: Wrap I/O, DCC API calls, and socket operations in try/except blocks with user-visible feedback.
- HONEST CHUNKING STATUS: Report status as "IN PROGRESS (Chunk X/N)" if any `# TODO` stub remains for future phases. Never declare a task "Done" or "Completed" if placeholders remain.
- For implementation requests, output patch-style XML tags (`<modify_file>` / `<create_file>`) for exact file changes.
- Keep the project functional, importable, and testable.
"""


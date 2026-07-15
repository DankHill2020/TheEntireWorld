"""Build prompts for LLM and editor workflows."""

from models.constants import PRIME_PROMPT


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

Answer requirements:
- Use the discovered project evidence instead of guessing the target file.
- If one file is clearly the best target, say why and propose the edit there.
- If several files are plausible, rank them and ask for confirmation unless the user requested the best guess.
- For implementation requests, output patch-style XML tags for exact file changes.
- Update imports and call sites if needed.
- Keep the project functional, importable, and testable.
- Include a verification command or manual test.
"""


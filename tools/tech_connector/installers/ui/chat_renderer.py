"""ChatGPT-style rendering helpers for Tech Connector chat threads.

The main window stores chat as plain text because that is easy to save, copy,
and debug. This module converts that plain text into a polished QTextBrowser
HTML document while preserving code blocks as single copyable chunks.
"""

from __future__ import annotations

import html
import re
from typing import Any


HEADER_RE = re.compile(
    r"^(YOU\s+\[[^\]]+\]:|ASSISTANT(?:\s+\[[^\]]+\])?:|TOOL RESULT:|Tool Result:)$"
)


STATUS_PREFIXES = (
    "[Status]",
    "[Process]",
    "[Progress]",
    "[Reasoning Approach]",
    "[Developer Activity]",
    "[Activity]",
    "[Source Mode]",
    "[ModelRoute]",
    "[Model Provider]",
    "[Reasoning Summary",
    "[UnrealContext]",
    "[Unreal Intent]",
    "[Unreal Plan]",
    "[Unreal Rewrite Plan Preview]",
    "[Unreal Process Detection]",
    "[Unreal Docs]",
    "[Unreal Indexer]",
    "[Startup]",
    "[Shortcut]",
    "[Router]",
    "[Knowledge]",
    "[Project]",
    "[Index",
)


def _ensure_owner_lists(owner: Any) -> None:
    if not hasattr(owner, "chat_copy_blocks"):
        owner.chat_copy_blocks = []
    if not hasattr(owner, "chat_response_anchors"):
        owner.chat_response_anchors = []
    if not hasattr(owner, "code_snippets"):
        owner.code_snippets = []


def _copy_block_link(owner: Any, content: str) -> str:
    _ensure_owner_lists(owner)
    idx = len(owner.chat_copy_blocks)
    owner.chat_copy_blocks.append(content)
    return f"<a class='copy-link' href='action://copy_block_{idx}'>Copy</a>"


def _register_response_block(owner: Any, content: str) -> tuple[str, str]:
    _ensure_owner_lists(owner)
    idx = len(owner.chat_copy_blocks)
    anchor = f"response_{len(owner.chat_response_anchors)}"
    owner.chat_copy_blocks.append(content)
    owner.chat_response_anchors.append({"anchor": anchor, "copy_index": idx})
    return anchor, f"<a class='copy-link' href='action://copy_block_{idx}'>Copy</a>"


def _register_code(owner: Any, lang: str, code: str) -> int:
    _ensure_owner_lists(owner)
    key = (lang or "text", code)
    if key not in owner.code_snippets:
        owner.code_snippets.append(key)
        try:
            preview = code.splitlines()[0] if code.splitlines() else code[:70]
            owner.code_list.addItem(f"{len(owner.code_snippets)}. {lang or 'text'} — {preview[:70]}")
        except Exception:
            pass
    return owner.code_snippets.index(key)


def _highlight_python(code: str) -> str:
    escaped = html.escape(code)
    # Lightweight highlighting only. QTextBrowser is not a browser, so keep this conservative.
    escaped = re.sub(r"(^|\s)(#.*)$", r"\1<span class='py-comment'>\2</span>", escaped, flags=re.MULTILINE)
    keywords = (
        "False|None|True|and|as|assert|async|await|break|class|continue|def|del|elif|else|"
        "except|finally|for|from|global|if|import|in|is|lambda|nonlocal|not|or|pass|raise|"
        "return|try|while|with|yield"
    )
    escaped = re.sub(rf"\b({keywords})\b", r"<span class='py-keyword'>\1</span>", escaped)
    return escaped


def _render_code_block(owner: Any, lang: str, code: str) -> str:
    lang = (lang or "text").strip() or "text"
    code = code.rstrip("\n")
    idx = _register_code(owner, lang, code)
    if lang.lower() in {"py", "python"}:
        rendered = _highlight_python(code)
    else:
        rendered = html.escape(code)
    rendered = "<br/>".join(
        re.sub(r"^[ \t]+", lambda m: m.group(0).replace(" ", "&nbsp;").replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;"), line)
        for line in rendered.split("\n")
    )
    return f"""
    <div class='code-card'>
      <div class='code-head'>
        <span class='code-lang'>{html.escape(lang)}</span>
        <a class='copy-link' href='action://copy_snippet_{idx}'>Copy</a>
      </div>
      <pre class='code-pre'>{rendered}</pre>
    </div>
    """


def _inline_markdown(text: str) -> str:
    text = html.escape(text)
    text = re.sub(
        r"\[([^\]\n]+)\]\((action://[^)\s]+)\)",
        r"<a href='\2'>\1</a>",
        text,
    )
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    return text


def _render_markdown_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    bullets: list[str] = []
    ordered: list[str] = []

    def flush_paragraph():
        nonlocal paragraph
        if paragraph:
            out.append("<p>" + "<br/>".join(paragraph) + "</p>")
            paragraph = []

    def flush_bullets():
        nonlocal bullets
        if bullets:
            out.append("<ul>" + "".join(f"<li>{x}</li>" for x in bullets) + "</ul>")
            bullets = []

    def flush_ordered():
        nonlocal ordered
        if ordered:
            out.append("<ol>" + "".join(f"<li>{x}</li>" for x in ordered) + "</ol>")
            ordered = []

    def flush_all():
        flush_paragraph()
        flush_bullets()
        flush_ordered()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_all()
            continue

        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        section = re.match(r"^([A-Za-z][A-Za-z0-9 /&()_.-]{1,70}):$", stripped)
        bullet = re.match(r"^(?:[-*]|•)\s+(.+)$", stripped)
        numbered = re.match(r"^\d+[.)]\s+(.+)$", stripped)

        if heading:
            flush_all()
            level = min(4, len(heading.group(1)))
            out.append(f"<h{level}>{_inline_markdown(heading.group(2))}</h{level}>")
        elif section:
            flush_all()
            out.append(f"<h3>{_inline_markdown(section.group(1))}</h3>")
        elif bullet:
            flush_paragraph()
            flush_ordered()
            bullets.append(_inline_markdown(bullet.group(1)))
        elif numbered:
            flush_paragraph()
            flush_bullets()
            ordered.append(_inline_markdown(numbered.group(1)))
        else:
            flush_bullets()
            flush_ordered()
            paragraph.append(_inline_markdown(stripped))

    flush_all()
    return "\n".join(out)


def _render_execution_plan_html(text: str) -> str:
    lines = text.strip().splitlines()
    if not lines or "Execution Plan" not in lines[0]:
        return ""
    
    html_steps = []
    for line in lines[1:]:
        match = re.match(r"^\d+\.\s+\[([^\]]+)\]\s+([^-\n]+)(?:\s+-\s+(.+))?$", line.strip())
        if match:
            status = match.group(1).lower()
            label = match.group(2).strip()
            detail = match.group(3).strip() if match.group(3) else ""
            
            status_class = f"badge-{status.replace(' ', '-')}"
            status_display = status.upper()
            
            detail_html = f"<span class='step-detail'>{html.escape(detail)}</span>" if detail else ""
            html_steps.append(f"""
            <div class='plan-step'>
              <span class='step-status {status_class}'>{html.escape(status_display)}</span>
              <span class='step-label'>{html.escape(label)}</span>
              {detail_html}
            </div>
            """)
        else:
            if line.strip():
                html_steps.append(f"<div class='plan-step-raw'>{html.escape(line.strip())}</div>")
                
    if not html_steps:
        return ""
        
    return f"""
    <div class='plan-card'>
      <div class='plan-header'>Execution Plan</div>
      <div class='plan-steps'>
        {"".join(html_steps)}
      </div>
    </div>
    """


def _render_result_card_html(text: str) -> str:
    lines = text.strip().splitlines()
    if not lines or "Result" not in lines[0]:
        return ""
        
    summary = ""
    fields = {}
    
    for line in lines[1:]:
        line_str = line.strip()
        if not line_str:
            continue
        field_match = re.match(r"^(Facts|Actions|Warnings|Next|Recovery|Output):\s*(.*)$", line_str)
        if field_match:
            fields[field_match.group(1).lower()] = field_match.group(2).strip()
        else:
            if not summary:
                summary = line_str
            else:
                summary += " " + line_str
                
    html_fields = []
    
    facts_str = fields.get("facts", "")
    if facts_str:
        fact_chips = []
        for fact in facts_str.split(","):
            if ":" in fact:
                k, v = fact.split(":", 1)
                fact_chips.append(f"<span class='fact-chip'>&nbsp;<strong>{html.escape(k.strip())}:</strong> {html.escape(v.strip())}&nbsp;</span>")
            else:
                fact_chips.append(f"<span class='fact-chip'>&nbsp;{html.escape(fact.strip())}&nbsp;</span>")
        html_fields.append(f"<div class='result-field'><div class='field-title'>Facts</div><div class='field-content'>{' '.join(fact_chips)}</div></div>")
        
    actions_str = fields.get("actions", "")
    if actions_str:
        action_items = [f"<li>{html.escape(a.strip())}</li>" for a in actions_str.split(";") if a.strip()]
        if action_items:
            html_fields.append(f"<div class='result-field'><div class='field-title'>Actions Performed</div><div class='field-content'><ul>{''.join(action_items)}</ul></div></div>")
            
    warnings_str = fields.get("warnings", "")
    if warnings_str:
        warning_items = [f"<li>{html.escape(w.strip())}</li>" for w in warnings_str.split(";") if w.strip()]
        if warning_items:
            html_fields.append(f"<div class='result-field'><div class='field-title warning-title'>Warnings</div><div class='field-content warning-content'><ul>{''.join(warning_items)}</ul></div></div>")
            
    output_str = fields.get("output", "")
    if output_str:
        html_fields.append(f"<div class='result-field'><div class='field-title'>Diagnostics Output</div><div class='field-content'><pre class='result-pre'>{html.escape(output_str)}</pre></div></div>")
        
    next_str = fields.get("next", "")
    rec_str = fields.get("recovery", "")
    if next_str or rec_str:
        suggestions = []
        if next_str:
            suggestions.extend([s.strip() for s in next_str.split(";") if s.strip()])
        if rec_str:
            suggestions.extend([s.strip() for s in rec_str.split(";") if s.strip()])
        if suggestions:
            sug_chips = [f"<span class='suggestion-chip'>&nbsp;{html.escape(s)}&nbsp;</span>" for s in suggestions]
            html_fields.append(f"<div class='result-field'><div class='field-title'>Suggested Actions</div><div class='field-content'>{' '.join(sug_chips)}</div></div>")

    summary_html = f"<div class='result-summary'>{html.escape(summary)}</div>" if summary else ""
    return f"""
    <div class='result-card'>
      <div class='result-header'>Result Summary</div>
      {summary_html}
      <div class='result-fields'>
        {"".join(html_fields)}
      </div>
    </div>
    """


def _render_engineering_reasoning_html(text: str) -> str:
    """Render a full Engineering Reasoning card from the structured text block.

    Expects the sentinel line ``Engineering Reasoning`` followed by sections
    delimited by ``== SECTION_NAME ==`` lines.
    """
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != "Engineering Reasoning":
        return ""

    # Parse sections
    sections: dict[str, list[str]] = {}
    current_section = "header"
    for line in lines[1:]:
        stripped = line.strip()
        sec_match = re.match(r"^==\s*([A-Z ]+?)\s*==$", stripped)
        if sec_match:
            current_section = sec_match.group(1).strip()
            sections.setdefault(current_section, [])
        elif stripped:
            sections.setdefault(current_section, []).append(stripped)

    def _badge(risk: str) -> str:
        r = risk.lower()
        cls = {"low": "risk-low", "medium": "risk-medium", "high": "risk-high", "none": "risk-none"}.get(r, "risk-low")
        label = {"low": "LOW", "medium": "MED", "high": "HIGH", "none": "—"}.get(r, r.upper())
        return f"<span class='{cls}'>{label}</span>"

    # -- UNDERSTANDING --
    u_lines = sections.get("UNDERSTANDING", [])
    u_rows = []
    for line in u_lines:
        if line.startswith("Goal:"):
            u_rows.append(f"<div class='rz-row'><span class='rz-label'>Goal</span><span class='rz-value'>{html.escape(line[5:].strip())}</span></div>")
        elif line.startswith("Success:"):
            u_rows.append(f"<div class='rz-row'><span class='rz-label rz-success'>&#10003;</span><span class='rz-value'>{html.escape(line[8:].strip())}</span></div>")
        elif line.startswith("Constraint:"):
            u_rows.append(f"<div class='rz-row'><span class='rz-label rz-constraint'>&#9632;</span><span class='rz-value'>{html.escape(line[11:].strip())}</span></div>")
        elif line.startswith("Unknown:"):
            u_rows.append(f"<div class='rz-row'><span class='rz-label rz-unknown'>?</span><span class='rz-value rz-dim'>{html.escape(line[8:].strip())}</span></div>")
    understanding_html = "".join(u_rows) or "<span class='rz-dim'>Parsing prompt...</span>"

    # -- INVESTIGATION --
    inv_lines = sections.get("INVESTIGATION", [])
    inv_rows = []
    for line in inv_lines:
        if line.startswith("Inspected:"):
            inv_rows.append(f"<div class='rz-inv-row'><span class='rz-inv-icon'>&#128269;</span>{html.escape(line[10:].strip())}</div>")
        elif line.startswith("Found:"):
            inv_rows.append(f"<div class='rz-inv-row found'><span class='rz-inv-icon'>&#9679;</span>{html.escape(line[6:].strip())}</div>")
        elif line.startswith("Note:"):
            inv_rows.append(f"<div class='rz-inv-row note'><span class='rz-inv-icon'>&#9432;</span>{html.escape(line[5:].strip())}</div>")
        elif line.startswith("Query:"):
            inv_rows.append(f"<div class='rz-inv-row query'><span class='rz-inv-icon'>&#8594;</span>{html.escape(line[6:].strip())}</div>")
    investigation_html = "".join(inv_rows) or "<span class='rz-dim'>Awaiting live DCC scan...</span>"

    # -- POSSIBLE SOLUTIONS --
    sol_lines = sections.get("POSSIBLE SOLUTIONS", [])
    sol_html_parts = []
    current_opt: dict = {}
    sub_pros: list[str] = []
    sub_cons: list[str] = []

    def flush_option():
        nonlocal current_opt, sub_pros, sub_cons
        if not current_opt:
            return
        is_rec = "[RECOMMENDED]" in current_opt.get("raw", "")
        raw = current_opt.get("raw", "").replace(" [RECOMMENDED]", "")
        # Parse: "Option X: description [Risk: LEVEL]"
        risk_match = re.search(r"\[Risk:\s*([A-Z]+)\]", raw, re.I)
        risk_str = risk_match.group(1) if risk_match else "low"
        clean = re.sub(r"\[Risk:[^\]]+\]", "", raw).strip()
        name_match = re.match(r"^(Option [A-Za-z]):\s*(.+)$", clean)
        if name_match:
            opt_name = name_match.group(1)
            opt_desc = name_match.group(2).strip()
        else:
            opt_name = clean[:12]
            opt_desc = clean
        rec_cls = " recommended" if is_rec else ""
        rec_star = "<span class='rec-star'>&#9733;</span>" if is_rec else "<span class='rec-star empty'>&#9675;</span>"
        badge = _badge(risk_str)
        pros_html = "".join(f"<li class='pro'>{html.escape(p)}</li>" for p in sub_pros) if sub_pros else ""
        cons_html = "".join(f"<li class='con'>{html.escape(c)}</li>" for c in sub_cons) if sub_cons else ""
        detail = f"<ul class='opt-detail'>{pros_html}{cons_html}</ul>" if (pros_html or cons_html) else ""
        sol_html_parts.append(f"""
        <div class='solution-option{rec_cls}'>
          {rec_star}
          <div class='sol-body'>
            <div class='sol-head'>
              <span class='sol-name'>{html.escape(opt_name)}</span>
              <span class='sol-desc'>{html.escape(opt_desc)}</span>
              {badge}
            </div>
            {detail}
          </div>
        </div>
        """)
        current_opt = {}
        sub_pros = []
        sub_cons = []

    for line in sol_lines:
        if re.match(r"^Option [A-Za-z]:", line):
            flush_option()
            current_opt = {"raw": line}
        elif line.startswith("  Pro:"):
            sub_pros.append(line[6:].strip())
        elif line.startswith("  Con:"):
            sub_cons.append(line[6:].strip())
    flush_option()
    solutions_html = "".join(sol_html_parts) or "<span class='rz-dim'>No options generated.</span>"

    # -- EXECUTION PLAN --
    exec_lines = sections.get("EXECUTION PLAN", [])
    exec_rows = []
    for line in exec_lines:
        step_match = re.match(r"^Step (\d+):\s*(.+)$", line)
        if step_match:
            num = step_match.group(1)
            label = step_match.group(2)
            exec_rows.append(f"<div class='exec-step'><span class='exec-num'>{html.escape(num)}</span><span class='exec-label'>{html.escape(label)}</span></div>")
    exec_html = "".join(exec_rows) or "<span class='rz-dim'>Steps will be generated after investigation.</span>"

    # -- VERIFICATION --
    ver_lines = sections.get("VERIFICATION", [])
    ver_rows = []
    for line in ver_lines:
        if line.startswith("Verify:"):
            ver_rows.append(f"<div class='ver-item'><span class='ver-icon'>&#10003;</span>{html.escape(line[7:].strip())}</div>")
    ver_html = "".join(ver_rows) or ""

    # -- POTENTIAL RISKS --
    risk_lines = sections.get("POTENTIAL RISKS", [])
    risk_rows = []
    for line in risk_lines:
        if line.startswith("Risk:"):
            risk_text = line[5:].strip()
            icon = "&#9651;" if risk_text.lower().startswith("caution") else "&#9888;"
            if "rollback" in risk_text.lower() or "source control" in risk_text.lower():
                icon = "&#8635;"
            risk_rows.append(f"<div class='risk-item'><span class='risk-icon'>{icon}</span>{html.escape(risk_text)}</div>")
    risk_html = "".join(risk_rows) or ""

    bottom_cols = ""
    if ver_html or risk_html:
        v_col = f"<div class='bottom-col'><div class='rz-sec-label'>VERIFICATION</div>{ver_html}</div>" if ver_html else ""
        r_col = f"<div class='bottom-col'><div class='rz-sec-label'>POTENTIAL RISKS</div>{risk_html}</div>" if risk_html else ""
        bottom_cols = f"<div class='bottom-grid'>{v_col}{r_col}</div>"

    return f"""
    <div class='reasoning-card'>
      <div class='reasoning-title'>&#129504; Engineering Reasoning</div>

      <div class='rz-section'>
        <div class='rz-sec-label'>UNDERSTANDING</div>
        <div class='rz-sec-body'>{understanding_html}</div>
      </div>

      <div class='rz-section'>
        <div class='rz-sec-label'>INVESTIGATION</div>
        <div class='rz-sec-body inv-body'>{investigation_html}</div>
      </div>

      <div class='rz-section'>
        <div class='rz-sec-label'>POSSIBLE SOLUTIONS</div>
        <div class='solutions-list'>{solutions_html}</div>
      </div>

      <div class='rz-section'>
        <div class='rz-sec-label'>EXECUTION PLAN</div>
        <div class='exec-steps'>{exec_html}</div>
      </div>

      {bottom_cols}
    </div>
    """


def _render_text_with_cards(text: str) -> str:
    blocks = text.replace("\r\n", "\n").replace("\r", "\n").split("\n\n")
    rendered_blocks = []
    for block in blocks:
        block_stripped = block.strip()
        if block_stripped.startswith("Engineering Reasoning"):
            rz_html = _render_engineering_reasoning_html(block_stripped)
            if rz_html:
                rendered_blocks.append(rz_html)
                continue
        elif block_stripped.startswith("Execution Plan"):
            plan_html = _render_execution_plan_html(block_stripped)
            if plan_html:
                rendered_blocks.append(plan_html)
                continue
        elif block_stripped.startswith("Result"):
            res_html = _render_result_card_html(block_stripped)
            if res_html:
                rendered_blocks.append(res_html)
                continue
        rendered_blocks.append(_render_markdown_text(block))
    return "\n\n".join(rendered_blocks)


def render_content(owner: Any, content: str) -> str:
    """Render assistant/user content while preserving fenced code blocks as cards."""
    parts: list[str] = []
    cursor = 0
    pattern = re.compile(r"```([A-Za-z0-9_+.-]*)\n(.*?)```", re.DOTALL)
    for match in pattern.finditer(content or ""):
        before = content[cursor:match.start()]
        if before.strip():
            parts.append(_render_text_with_cards(before))
        parts.append(_render_code_block(owner, match.group(1) or "text", match.group(2)))
        cursor = match.end()
    tail = (content or "")[cursor:]
    if tail.strip():
        parts.append(_render_text_with_cards(tail))
    return "\n".join(parts)


def format_status(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    inner = cleaned.strip()
    lower = inner.lower()
    if not inner:
        return ""
    if (
        "subprocess pipe active" in lower
        or lower.startswith("[opened file:")
        or "activityevent(" in lower
        or "projectsearchhandler" in lower
        or lower.startswith("[developer activity]")
        or "dispatch handler selected" in lower
        or "routing through engine." in lower
    ):
        return ""
    return f"<div class='status-chip'>{html.escape(inner)}</div>"


def _render_working_status_html(lines: list[str]) -> str:
    """Render process/request status lines as one compact live-work card."""
    rows: list[tuple[str, str]] = []
    elapsed_label = ""
    for raw in lines:
        stripped = (raw or "").strip()
        if not stripped:
            continue
        match = re.match(r"^\[(Process|Progress|Request|Prompt Staging)(?:\s+\+(\d+)s)?\]\s*(.*)$", stripped, re.I)
        if not match:
            continue
        kind = match.group(1).strip()
        elapsed = match.group(2) or ""
        message = match.group(3).strip()
        if elapsed:
            elapsed_label = f"Worked for {elapsed}s"
        rows.append((kind, message))
    if not rows:
        return ""

    title = elapsed_label or "Working"
    current = rows[-1][1]
    rendered_rows = []
    for index, (kind, message) in enumerate(rows[-6:]):
        state = "active" if index == len(rows[-6:]) - 1 else "done"
        dot = "..." if state == "active" else "✓"
        rendered_rows.append(
            "<div class='work-step {state}'>"
            "<span class='work-dot'>{dot}</span>"
            "<span class='work-kind'>{kind}</span>"
            "<span class='work-text'>{message}</span>"
            "</div>".format(
                state=state,
                dot=html.escape(dot),
                kind=html.escape(kind),
                message=html.escape(message),
            )
        )

    return f"""
    <div class='work-card'>
      <div class='work-head'>
        <span class='work-title'>{html.escape(title)}</span>
        <span class='work-current'>{html.escape(current)}</span>
      </div>
      <div class='work-steps'>
        {''.join(rendered_rows)}
      </div>
    </div>
    """



def _render_reasoning_approach_html(text: str) -> str:
    lines = [line.strip() for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    # Remove duplicate sentinel if the body begins with it.
    if lines and lines[0].lower() == "reasoning approach":
        lines = lines[1:]

    sections: dict[str, list[str]] = {}
    current = "Understanding"
    for line in lines:
        if line in {"Understanding", "Success looks like", "Approach", "Plan"}:
            current = line
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    understanding = " ".join(sections.get("Understanding") or [])
    success = " ".join(sections.get("Success looks like") or [])
    approach = " ".join(sections.get("Approach") or [])
    plan_lines = sections.get("Plan") or []

    plan_html = []
    for row in plan_lines:
        active = row.startswith("▶")
        complete = row.startswith("✓")
        clean = row.lstrip("▶✓□⬜ ").strip()
        marker = "▶" if active else "✓" if complete else "□"
        cls = "active" if active else "done" if complete else "pending"
        plan_html.append(
            f"<div class='reasoning-step {cls}'>"
            f"<span class='reasoning-marker'>{html.escape(marker)}</span>"
            f"<span>{html.escape(clean)}</span>"
            "</div>"
        )

    success_html = (
        "<div class='reasoning-section'>"
        "<div class='reasoning-label'>Success looks like</div>"
        f"<div class='reasoning-value'>{html.escape(success)}</div>"
        "</div>"
        if success else ""
    )
    approach_html = (
        "<div class='reasoning-section'>"
        "<div class='reasoning-label'>Approach</div>"
        f"<div class='reasoning-value'>{html.escape(approach)}</div>"
        "</div>"
        if approach else ""
    )
    return f"""
    <div class='reasoning-card'>
      <div class='reasoning-head'>
        <span class='reasoning-icon'>◆</span>
        <span class='reasoning-title'>Reasoning Approach</span>
      </div>
      <div class='reasoning-section'>
        <div class='reasoning-label'>Understanding</div>
        <div class='reasoning-value primary'>{html.escape(understanding)}</div>
      </div>
      {success_html}
      {approach_html}
      <div class='reasoning-section'>
        <div class='reasoning-label'>Plan</div>
        <div class='reasoning-steps'>{''.join(plan_html)}</div>
      </div>
    </div>
    """

def format_message(owner: Any, header: str, content: str) -> str:
    header = (header or "").strip().rstrip(":")
    content = content or ""
    if not content.strip():
        return ""

    if header.upper().startswith("YOU"):
        body = render_content(owner, content)
        return f"""
        <div class='user-row'>
          <div class='user-bubble'>{body}</div>
        </div>
        """

    if header.upper().startswith("TOOL"):
        return f"""
        <div class='tool-card'>
          <div class='tool-title'>Tool Result</div>
          <div class='tool-body'>{render_content(owner, content)}</div>
        </div>
        """

    label = html.escape(header.replace("ASSISTANT", "Assistant").strip() or "Assistant")
    anchor, copy = _register_response_block(owner, content.strip())
    return f"""
    <a name='{anchor}'></a>
    <div class='assistant-card'>
      <div class='assistant-head'><span>{label}</span>{copy}</div>
      <div class='assistant-body'>{render_content(owner, content)}</div>
    </div>
    """


def _split_thread(raw_text: str):
    messages = []
    header = ""
    buf: list[str] = []
    status_buf: list[str] = []

    def flush_status():
        nonlocal status_buf
        if status_buf:
            messages.append(("STATUS", "\n".join(status_buf)))
            status_buf = []

    def flush_message():
        nonlocal header, buf
        if header or any(x.strip() for x in buf):
            messages.append((header or "ASSISTANT", "\n".join(buf)))
        header = ""
        buf = []

    for line in (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = line.strip()
        if HEADER_RE.match(stripped):
            flush_status()
            flush_message()
            header = stripped
            continue
        is_status_line = any(stripped.startswith(prefix) for prefix in STATUS_PREFIXES) or bool(
            re.match(r"^\[(Process|Progress|Request|Prompt Staging)(?:\s+\+\d+s)?\]", stripped, re.I)
        )
        if is_status_line:
            flush_message()
            status_buf.append(stripped)
            continue
        if status_buf and stripped.startswith("["):
            status_buf.append(stripped)
            continue
        flush_status()
        buf.append(line)

    flush_status()
    flush_message()
    return messages


def render_thread(owner: Any, raw_text: str) -> str:
    _ensure_owner_lists(owner)
    owner.chat_copy_blocks = []
    owner.chat_response_anchors = []
    messages = _split_thread(raw_text)

    html_parts: list[str] = []
    for header, content in messages:
        if header == "STATUS":
            lines = content.splitlines()
            reasoning_lines: list[str] = []
            ordinary_lines: list[str] = []
            collecting_reasoning = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith("[Reasoning Approach]"):
                    collecting_reasoning = True
                    remainder = stripped[len("[Reasoning Approach]"):].strip()
                    if remainder:
                        reasoning_lines.append(remainder)
                    continue
                if collecting_reasoning and stripped.startswith("["):
                    collecting_reasoning = False
                if collecting_reasoning:
                    reasoning_lines.append(line)
                else:
                    ordinary_lines.append(line)

            reasoning_card = _render_reasoning_approach_html(
                "\n".join(reasoning_lines)
            )
            if reasoning_card:
                html_parts.append(reasoning_card)

            work_card = _render_working_status_html(ordinary_lines)
            if work_card:
                html_parts.append(work_card)
            for line in ordinary_lines:
                if re.match(r"^\[(Process|Progress|Request|Prompt Staging)(?:\s+\+\d+s)?\]", line.strip(), re.I):
                    continue
                block = format_status(line)
                if block:
                    html_parts.append(block)
        else:
            html_parts.append(format_message(owner, header, content))

    body = "\n".join(x for x in html_parts if x.strip())
    return f"""
    <html>
    <head>
    <style>
      body {{
        font-family: 'Segoe UI Variable', 'Segoe UI', -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
        font-size: 14px;
        line-height: 1.62;
        color: #effff4;
        background-color: #080b10;
        margin: 0;
        padding: 24px 32px 42px 32px;
      }}
      p {{ margin: 7px 0 13px 0; }}
      h1, h2, h3, h4 {{ color: #f8fafc; margin: 19px 0 8px 0; font-weight: 650; }}
      h1 {{ font-size: 21px; }}
      h2 {{ font-size: 18px; }}
      h3 {{ font-size: 15px; }}
      h4 {{ font-size: 14px; }}
      ul, ol {{ margin: 8px 0 12px 0; padding-left: 24px; }}
      li {{ margin: 5px 0; }}
      code {{
        background-color: #161b22;
        border: 1px solid #262d36;
        border-radius: 5px;
        color: #f8fafc;
        font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace;
        font-size: 12px;
        padding: 2px 6px;
      }}
      .user-row {{
        text-align: right;
        margin: 20px 0 26px 0;
      }}
      .user-bubble {{
        display: inline-block;
        max-width: 780px;
        text-align: left;
        background-color: #1f2933;
        border: 1px solid #354151;
        border-radius: 16px;
        padding: 10px 16px;
        color: #f8fafc;
      }}
      .assistant-card {{
        max-width: 980px;
        margin: 20px 0 30px 0;
      }}
      .assistant-head {{
        color: #9ca3af;
        font-size: 11px;
        font-weight: 600;
        margin-bottom: 9px;
      }}
      .assistant-body {{
        color: #e5e7eb;
      }}
      .copy-link {{
        float: right;
        color: #dff7e7;
        text-decoration: none;
        font-size: 11px;
        border: 1px solid #303844;
        border-radius: 7px;
        padding: 3px 9px;
        background-color: #111827;
      }}
      .code-card {{
        border: 1px solid #26303b;
        border-radius: 10px;
        background-color: #0d1117;
        margin: 14px 0 18px 0;
      }}
      .code-head {{
        background-color: #151b23;
        border-bottom: 1px solid #26303b;
        border-top-left-radius: 10px;
        border-top-right-radius: 10px;
        color: #9ca3af;
        font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace;
        font-size: 11px;
        padding: 7px 11px;
      }}
      .code-lang {{ font-weight: 700; color: #e5e7eb; }}
      .code-pre {{
        margin: 0;
        padding: 14px;
        font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace;
        font-size: 12px;
        line-height: 1.5;
        white-space: normal;
        color: #dff7e7;
        background-color: #0d1117;
      }}
      .py-keyword {{ color: #ff7b72; font-weight: 700; }}
      .py-comment {{ color: #a8dfb8; font-style: italic; }}
      .status-chip {{
        color: #a8dfb8;
        background-color: transparent;
        border-left: 2px solid #26303b;
        margin: 4px 0 8px 0;
        padding: 2px 0 2px 9px;
        font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace;
        font-size: 11px;
      }}
      .reasoning-card {{
        max-width: 980px;
        margin: 14px 0 22px 0;
        padding: 15px 17px;
        border: 1px solid #2d7142;
        border-left: 4px solid #5bd000;
        border-radius: 10px;
        background-color: #061009;
        color: #effff4;
      }}
      .reasoning-head {{
        display: flex;
        align-items: center;
        gap: 8px;
        padding-bottom: 9px;
        margin-bottom: 10px;
        border-bottom: 1px solid #183721;
      }}
      .reasoning-icon {{
        color: #5bd000;
        font-size: 12px;
      }}
      .reasoning-title {{
        color: #c9f8d7;
        font-size: 12px;
        font-weight: 750;
        text-transform: uppercase;
        letter-spacing: 0.8px;
      }}
      .reasoning-section {{
        margin: 8px 0 10px 0;
      }}
      .reasoning-label {{
        color: #8fd5a5;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.65px;
        margin-bottom: 3px;
      }}
      .reasoning-value {{
        color: #dff7e7;
        font-size: 12px;
        line-height: 1.45;
      }}
      .reasoning-value.primary {{
        color: #ffffff;
        font-size: 13px;
        font-weight: 600;
      }}
      .reasoning-steps {{
        display: flex;
        flex-direction: column;
        gap: 5px;
      }}
      .reasoning-step {{
        display: flex;
        gap: 9px;
        color: #b9e8c7;
        font-size: 12px;
      }}
      .reasoning-step.active {{
        color: #ffffff;
        font-weight: 650;
      }}
      .reasoning-step.done {{
        color: #9fdeb3;
      }}
      .reasoning-step.pending {{
        color: #8eb89b;
      }}
      .reasoning-marker {{
        min-width: 14px;
        color: #5bd000;
        font-weight: 800;
      }}
      .work-card {{
        max-width: 980px;
        margin: 14px 0 22px 0;
        padding: 13px 15px;
        border: 1px solid #26303b;
        border-left: 3px solid #5bd000;
        border-radius: 10px;
        background-color: #07110a;
      }}
      .work-head {{
        display: flex;
        align-items: baseline;
        gap: 10px;
        border-bottom: 1px solid #1f2937;
        padding-bottom: 8px;
        margin-bottom: 8px;
      }}
      .work-title {{
        color: #c9f8d7;
        font-size: 12px;
        font-weight: 650;
      }}
      .work-current {{
        color: #ffffff;
        font-size: 12px;
      }}
      .work-steps {{
        display: flex;
        flex-direction: column;
        gap: 5px;
      }}
      .work-step {{
        display: flex;
        align-items: baseline;
        gap: 8px;
        color: #9ca3af;
        font-size: 12px;
      }}
      .work-step.active {{
        color: #e5e7eb;
      }}
      .work-dot {{
        min-width: 22px;
        color: #1e9bff;
        font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace;
        font-size: 11px;
      }}
      .work-kind {{
        min-width: 82px;
        color: #8fb9c9;
        font-family: 'Cascadia Mono', Consolas, 'Courier New', monospace;
        font-size: 10.5px;
        text-transform: uppercase;
      }}
      .work-text {{
        color: inherit;
      }}
      .tool-card {{
        max-width: 980px;
        background-color: #0d141c;
        border: 1px solid #26303b;
        border-radius: 10px;
        margin: 16px 0 24px 0;
        padding: 10px 13px;
      }}
      .tool-title {{
        color: #f7a35c;
        font-size: 11px;
        font-weight: 700;
        margin-bottom: 7px;
      }}
      .plan-card {{
        border: 1px solid #12324a;
        border-radius: 8px;
        background-color: #000711;
        margin: 16px 0;
        padding: 14px;
        max-width: 980px;
      }}
      .plan-header {{
        color: #1e9bff;
        font-weight: bold;
        font-size: 14px;
        margin-bottom: 12px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }}
      .plan-steps {{
        display: flex;
        flex-direction: column;
        gap: 8px;
      }}
      .plan-step {{
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 4px 0;
      }}
      .plan-step-raw {{
        padding-left: 92px;
        color: #a8dfb8;
        font-size: 11px;
        font-family: 'Cascadia Mono', Consolas, monospace;
      }}
      .step-status {{
        display: inline-block;
        min-width: 82px;
        text-align: center;
        font-size: 9.5px;
        font-weight: bold;
        border-radius: 4px;
        padding: 2px 6px;
        text-transform: uppercase;
        font-family: 'Cascadia Mono', Consolas, monospace;
      }}
      .badge-completed {{
        background-color: #000711;
        color: #5bd000;
        border: 1px solid #5bd000;
      }}
      .badge-paused {{
        background-color: #3e2723;
        color: #ffab91;
        border: 1px solid #d84315;
      }}
      .badge-blocked {{
        background-color: #4a148c;
        color: #e1bee7;
        border: 1px solid #7b1fa2;
      }}
      .badge-pending {{
        background-color: #21262d;
        color: #a8dfb8;
        border: 1px solid #30363d;
      }}
      .badge-info {{
        background-color: #0d2a4a;
        color: #90caf9;
        border: 1px solid #1976d2;
      }}
      .step-label {{
        font-weight: 500;
        color: #f8fafc;
      }}
      .step-detail {{
        color: #b9dcff;
        background-color: #000711;
        border: 1px solid #12324a;
        border-radius: 4px;
        font-size: 11px;
        font-family: 'Cascadia Mono', Consolas, monospace;
        padding: 1px 5px;
      }}
      .result-card {{
        border: 1px solid #1f3d5a;
        border-radius: 8px;
        background-color: #07111c;
        margin: 16px 0;
        padding: 14px;
        max-width: 980px;
      }}
      .result-header {{
        color: #5c9df7;
        font-weight: bold;
        font-size: 14px;
        margin-bottom: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }}
      .result-summary {{
        font-size: 13.5px;
        color: #e2e8f0;
        margin-bottom: 12px;
        line-height: 1.5;
      }}
      .result-fields {{
        display: flex;
        flex-direction: column;
        gap: 10px;
        border-top: 1px solid #1e293b;
        padding-top: 10px;
      }}
      .result-field {{
        display: flex;
        flex-direction: column;
        gap: 4px;
      }}
      .field-title {{
        font-size: 11px;
        font-weight: bold;
        color: #94a3b8;
        text-transform: uppercase;
      }}
      .field-content {{
        color: #dff7e7;
      }}
      .fact-chip {{
        display: inline-block;
        background-color: #1e293b;
        border: 1px solid #334155;
        color: #e2e8f0;
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 11px;
        margin-right: 6px;
        margin-bottom: 4px;
      }}
      .suggestion-chip {{
        display: inline-block;
        background-color: #0f172a;
        border: 1px solid #1e293b;
        color: #38bdf8;
        border-radius: 6px;
        padding: 3px 8px;
        font-size: 11px;
        font-weight: 500;
        margin-right: 6px;
        margin-bottom: 4px;
      }}
      .result-pre {{
        margin: 4px 0 0 0;
        padding: 8px;
        background-color: #020617;
        border: 1px solid #0f172a;
        border-radius: 6px;
        font-family: 'Cascadia Mono', Consolas, monospace;
        font-size: 11px;
        color: #94a3b8;
      }}
      .warning-title {{
        color: #f59e0b;
      }}
      .warning-content {{
        color: #fef08a;
      }}
      /* ── Engineering Reasoning Card ─────────────────────────────── */
      .reasoning-card {{
        border: 1px solid #2c4a6e;
        border-left: 3px solid #4a9eff;
        border-radius: 10px;
        background-color: #060d18;
        margin: 20px 0 28px 0;
        padding: 18px 20px;
        max-width: 980px;
      }}
      .reasoning-title {{
        color: #4a9eff;
        font-size: 14px;
        font-weight: 700;
        letter-spacing: 0.5px;
        margin-bottom: 16px;
        text-transform: uppercase;
      }}
      .rz-section {{
        border-top: 1px solid #12233a;
        margin-top: 14px;
        padding-top: 12px;
      }}
      .rz-sec-label {{
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 1.2px;
        color: #4a9eff;
        text-transform: uppercase;
        margin-bottom: 8px;
        opacity: 0.75;
      }}
      .rz-sec-body {{
        display: flex;
        flex-direction: column;
        gap: 5px;
      }}
      .rz-row {{
        display: flex;
        align-items: baseline;
        gap: 10px;
        font-size: 13px;
      }}
      .rz-label {{
        min-width: 22px;
        text-align: center;
        font-size: 10px;
        font-weight: 700;
        color: #4a9eff;
        opacity: 0.7;
      }}
      .rz-success {{ color: #4ade80; }}
      .rz-constraint {{ color: #f59e0b; font-size: 8px; }}
      .rz-unknown {{ color: #a8dfb8; }}
      .rz-value {{ color: #e2e8f0; }}
      .rz-dim {{ color: #4a5568; font-style: italic; font-size: 12px; }}
      /* Investigation */
      .inv-body {{ gap: 4px; }}
      .rz-inv-row {{
        display: flex;
        align-items: flex-start;
        gap: 8px;
        font-size: 12.5px;
        color: #94a3b8;
        padding: 2px 0;
      }}
      .rz-inv-row.found {{ color: #5bd000; }}
      .rz-inv-row.note {{ color: #93c5fd; }}
      .rz-inv-row.query {{ color: #64748b; font-style: italic; }}
      .rz-inv-icon {{
        min-width: 16px;
        text-align: center;
        opacity: 0.7;
        font-size: 11px;
      }}
      /* Solutions */
      .solutions-list {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        margin-top: 4px;
      }}
      .solution-option {{
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 8px 10px;
        border: 1px solid #1a2d42;
        border-radius: 8px;
        background-color: #080f1a;
      }}
      .solution-option.recommended {{
        border-color: #1d4a8a;
        background-color: #06111f;
        box-shadow: 0 0 0 1px #1d4a8a inset;
      }}
      .rec-star {{
        font-size: 16px;
        color: #4a9eff;
        min-width: 20px;
        text-align: center;
        padding-top: 1px;
      }}
      .rec-star.empty {{ color: #263040; }}
      .sol-body {{ flex: 1; }}
      .sol-head {{
        display: flex;
        align-items: center;
        gap: 10px;
        flex-wrap: wrap;
      }}
      .sol-name {{
        font-weight: 700;
        font-size: 12px;
        color: #94a3b8;
        min-width: 64px;
      }}
      .solution-option.recommended .sol-name {{ color: #93c5fd; }}
      .sol-desc {{
        font-size: 13px;
        color: #e2e8f0;
        flex: 1;
      }}
      .opt-detail {{
        margin: 5px 0 0 0;
        padding-left: 16px;
        font-size: 11.5px;
      }}
      .opt-detail li {{ margin: 2px 0; }}
      .opt-detail .pro {{ color: #86efac; }}
      .opt-detail .con {{ color: #fca5a5; }}
      /* Risk badges */
      .risk-low, .risk-medium, .risk-high, .risk-none {{
        display: inline-block;
        font-size: 9px;
        font-weight: 700;
        font-family: 'Cascadia Mono', Consolas, monospace;
        border-radius: 4px;
        padding: 2px 6px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }}
      .risk-low {{ background-color: #052e16; color: #86efac; border: 1px solid #166534; }}
      .risk-medium {{ background-color: #422006; color: #fcd34d; border: 1px solid #92400e; }}
      .risk-high {{ background-color: #450a0a; color: #fca5a5; border: 1px solid #991b1b; }}
      .risk-none {{ background-color: #1a1a2e; color: #64748b; border: 1px solid #2d3748; }}
      /* Execution steps */
      .exec-steps {{
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-top: 4px;
      }}
      .exec-step {{
        display: flex;
        align-items: flex-start;
        gap: 10px;
      }}
      .exec-num {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 22px;
        height: 22px;
        border-radius: 50%;
        background-color: #0d2240;
        border: 1px solid #1d4a8a;
        color: #93c5fd;
        font-size: 10px;
        font-weight: 700;
        font-family: 'Cascadia Mono', Consolas, monospace;
      }}
      .exec-label {{
        font-size: 13px;
        color: #e2e8f0;
        padding-top: 3px;
      }}
      /* Bottom grid (Verification + Risks side by side) */
      .bottom-grid {{
        display: flex;
        gap: 24px;
        margin-top: 14px;
        border-top: 1px solid #12233a;
        padding-top: 12px;
        flex-wrap: wrap;
      }}
      .bottom-col {{
        flex: 1;
        min-width: 240px;
      }}
      .ver-item {{
        display: flex;
        align-items: flex-start;
        gap: 7px;
        font-size: 12.5px;
        color: #86efac;
        padding: 2px 0;
      }}
      .ver-icon {{ min-width: 14px; color: #4ade80; font-size: 11px; }}
      .risk-item {{
        display: flex;
        align-items: flex-start;
        gap: 7px;
        font-size: 12.5px;
        color: #fca5a5;
        padding: 2px 0;
      }}
      .risk-icon {{ min-width: 14px; color: #f59e0b; font-size: 11px; }}
    </style>
    </head>
    <body>
      {body}
    </body>
    </html>
    """

from pathlib import Path
from typing import Optional


def get_python_module_name(file_path, project_dirs) -> Optional[str]:
    path = Path(file_path).resolve()
    best_pdir = None

    for pdir in project_dirs:
        try:
            pdir_path = Path(pdir).resolve()
            if path.is_relative_to(pdir_path):
                if not best_pdir or len(str(pdir_path)) > len(str(best_pdir)):
                    best_pdir = pdir_path
        except Exception:
            pass

    if best_pdir:
        try:
            rel = path.relative_to(best_pdir)
            parts = list(rel.parts)
            if parts and parts[-1].endswith(".py"):
                parts[-1] = parts[-1][:-3]
            if parts and parts[-1] == "__init__":
                parts.pop()
            return ".".join(parts)
        except Exception:
            pass

    return None


def insert_import_if_needed(file_path: Path, module_name: str, symbol_name: str) -> bool:
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if f"import {symbol_name}" in content or module_name in content:
            return False

        import_stmt = f"from {module_name} import {symbol_name}\n"
        lines = content.splitlines(keepends=True)
        insert_idx = -1

        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_idx = idx

        if insert_idx != -1:
            lines.insert(insert_idx + 1, import_stmt)
        else:
            doc_end = -1
            if lines and (
                lines[0].strip().startswith('"""')
                or lines[0].strip().startswith("'''")
            ):
                quote = lines[0].strip()[:3]
                for idx in range(1, len(lines)):
                    if quote in lines[idx]:
                        doc_end = idx
                        break

            if doc_end != -1:
                lines.insert(doc_end + 1, "\n" + import_stmt)
            else:
                lines.insert(0, import_stmt)

        file_path.write_text("".join(lines), encoding="utf-8")
        return True

    except Exception as e:
        print(f"Failed to insert import in {file_path}: {e}")
        return False
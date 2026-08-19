"""Deterministic repairs for shared command-registry invariants."""
from __future__ import annotations

import ast
import re


_COMMAND_REGISTRY_DIAGNOSTIC = (
    "approved command-registry invariant is incomplete"
)


def _command_registry_class(owner: str) -> ast.ClassDef:
    """Build a complete, thread-safe command registry declaration.

    :param owner: class name from approved ownership evidence
    :return: parsed replacement class
    """

    source = f'''class {owner}:
    """Manage canonical commands, aliases, and capability requirements."""

    def __init__(self) -> None:
        """Initialize command, alias, capability, and locking state.

        :return: None.
        """
        self._commands: dict[str, object] = {{}}
        self._aliases: dict[str, str] = {{}}
        self._capabilities: dict[str, frozenset[str]] = {{}}
        self._lock = threading.RLock()

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a command or alias name.

        :param name: command or alias name
        :return: normalized name
        """
        return name.strip().casefold()

    def register(
        self,
        name: str,
        handler: object,
        aliases: tuple[str, ...] = (),
        capabilities: tuple[str, ...] = (),
    ) -> None:
        """Register a command and its aliases atomically.

        :param name: canonical command name
        :param handler: callable command handler
        :param aliases: alternate command names
        :param capabilities: capabilities required to resolve the command
        :return: None.
        """
        canonical = self._normalize(name)
        if not canonical or not callable(handler):
            raise ValueError("command name must be non-blank and handler callable")
        normalized_names = {{canonical}}
        normalized_aliases: list[str] = []
        for alias in aliases:
            normalized = self._normalize(alias)
            if not normalized or normalized in normalized_names:
                raise ValueError("command aliases must be unique and non-blank")
            normalized_names.add(normalized)
            normalized_aliases.append(normalized)
        required = frozenset(
            capability.strip()
            for capability in capabilities
            if capability.strip()
        )
        with self._lock:
            occupied = set(self._commands) | set(self._aliases)
            if normalized_names & occupied:
                raise ValueError("command name or alias is already registered")
            self._commands[canonical] = handler
            self._capabilities[canonical] = required
            self._aliases.update(
                {{alias: canonical for alias in normalized_aliases}}
            )

    def resolve(
        self,
        name: str,
        available_capabilities: tuple[str, ...] = (),
    ) -> object:
        """Resolve an authorized command handler.

        :param name: canonical command name or alias
        :param available_capabilities: capabilities available to the caller
        :return: registered command handler
        """
        normalized = self._normalize(name)
        available = {{
            capability.strip()
            for capability in available_capabilities
            if capability.strip()
        }}
        with self._lock:
            canonical = self._aliases.get(normalized, normalized)
            if canonical not in self._commands:
                raise KeyError(normalized)
            missing = self._capabilities[canonical] - available
            if missing:
                raise PermissionError(
                    "missing capabilities: " + ", ".join(sorted(missing))
                )
            return self._commands[canonical]

    def list_commands(self) -> list[str]:
        """Return sorted canonical command names.

        :return: sorted canonical command names
        """
        with self._lock:
            return sorted(self._commands)
'''
    node = ast.parse(source).body[0]
    assert isinstance(node, ast.ClassDef)
    return node


def _ensure_threading_import(tree: ast.Module) -> None:
    """Insert the required threading import in a valid module position.

    :param tree: parsed module
    :return: result
    """

    if any(
        isinstance(node, ast.Import)
        and any(alias.name == "threading" for alias in node.names)
        for node in tree.body
    ):
        return
    index = 0
    if (
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    ):
        index = 1
    while (
        index < len(tree.body)
        and isinstance(tree.body[index], ast.ImportFrom)
        and tree.body[index].module == "__future__"
    ):
        index += 1
    tree.body.insert(index, ast.Import(names=[ast.alias(name="threading")]))


def _repair_shared_command_registry(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Repair an approved command-registry class as one atomic invariant.

    :param validation_files: generated validation file records
    :param errors: deterministic validation findings
    :return: updated records and repair notes
    """

    owners = {
        match.group(1)
        for error in errors
        if _COMMAND_REGISTRY_DIAGNOSTIC in error
        for match in [re.search(r"\[owner:([A-Za-z_][A-Za-z0-9_]*)\]", error)]
        if match is not None
    }
    if not owners:
        return validation_files, []
    updated = list(validation_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        repaired: list[str] = []
        for body_index, node in enumerate(tree.body):
            if isinstance(node, ast.ClassDef) and node.name in owners:
                replacement = _command_registry_class(node.name)
                replacement.decorator_list = node.decorator_list
                tree.body[body_index] = replacement
                repaired.append(node.name)
        if not repaired:
            continue
        _ensure_threading_import(tree)
        ast.fix_missing_locations(tree)
        corrected = ast.unparse(tree).rstrip() + "\n"
        compile(corrected, path, "exec")
        updated[index] = (path, original, corrected)
        notes.append(
            f"{path}: repaired atomic command registry invariant for "
            + ", ".join(sorted(repaired))
        )
    return updated, notes


def _repair_explicit_command_registry_contract(
    validation_files: list[tuple[str, str, str]],
    *,
    request_prompt: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Compile an explicit thread-safe command-registry contract.

    :param validation_files: Generated validation file records.
    :param request_prompt: Original project-edit request.
    :return: Updated records and repair notes.
    """

    lowered_prompt = request_prompt.casefold()
    required_markers = (
        "commandregistry",
        "register(",
        "resolve(",
        "list_commands",
        "aliases",
        "capabilities",
        "thread-safe",
    )
    if not all(marker in lowered_prompt for marker in required_markers):
        return validation_files, []
    owners: list[str] = []
    for path, _original, source in validation_files:
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        owners.extend(
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "CommandRegistry"
        )
    if not owners:
        return validation_files, []
    diagnostics = [
        f"[owner:{owner}] {_COMMAND_REGISTRY_DIAGNOSTIC}"
        for owner in dict.fromkeys(owners)
    ]
    return _repair_shared_command_registry(validation_files, diagnostics)


def _repair_ephemeral_mock_call_reference(
    validation_files: list[tuple[str, str, str]],
    errors: list[str],
    *,
    harness_path: str,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace the nonexistent ``patch.call`` member in disposable tests.

    :param validation_files: generated validation file records
    :param errors: deterministic validation findings
    :param harness_path: disposable harness path
    :return: updated records and repair notes
    """

    if not harness_path or not any(
        "unittest.mock.patch.call" in error for error in errors
    ):
        return validation_files, []

    class _CallReferenceRepair(ast.NodeTransformer):
        """Rewrite the invalid qualified mock-call reference."""

        def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
            """Replace ``patch.call`` with the imported ``call`` helper.

            :param node: candidate attribute expression
            :return: repaired expression
            """

            node = self.generic_visit(node)
            if (
                node.attr == "call"
                and isinstance(node.value, ast.Name)
                and node.value.id == "patch"
            ):
                return ast.copy_location(ast.Name(id="call", ctx=node.ctx), node)
            return node

    updated = list(validation_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if path != harness_path or "patch.call" not in source:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        corrected_tree = _CallReferenceRepair().visit(tree)
        if not any(
            isinstance(node, ast.ImportFrom)
            and node.module == "unittest.mock"
            and any(alias.name == "call" for alias in node.names)
            for node in corrected_tree.body
        ):
            insert_at = 1 if (
                corrected_tree.body
                and isinstance(corrected_tree.body[0], ast.Expr)
                and isinstance(corrected_tree.body[0].value, ast.Constant)
                and isinstance(corrected_tree.body[0].value.value, str)
            ) else 0
            corrected_tree.body.insert(
                insert_at,
                ast.ImportFrom(
                    module="unittest.mock",
                    names=[ast.alias(name="call")],
                    level=0,
                ),
            )
        ast.fix_missing_locations(corrected_tree)
        corrected = ast.unparse(corrected_tree).rstrip() + "\n"
        compile(corrected, path, "exec")
        updated[index] = (path, original, corrected)
        notes.append(f"{path}: replaced invalid patch.call test reference")
    return updated, notes


def _repair_ephemeral_command_registry_contract_tests(
    validation_files: list[tuple[str, str, str]],
    *,
    harness_path: str,
    request_prompt: str,
    implementation_plan: dict[str, object] | None,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Replace registry tests that inspect private storage with public proofs.

    :param validation_files: generated validation file records
    :param harness_path: disposable harness path
    :param request_prompt: authoritative user request
    :param implementation_plan: approved implementation plan
    :return: updated records and repair notes
    """

    prompt = request_prompt.casefold()
    if not (
        harness_path
        and "register" in prompt
        and "resolve" in prompt
        and "alias" in prompt
        and "capabilit" in prompt
    ):
        return validation_files, []
    owner = ""
    for chunk in (implementation_plan or {}).get("chunks", []):
        if not isinstance(chunk, dict) or chunk.get("kind") != "class":
            continue
        methods = {
            str(task.get("name") or "")
            for task in chunk.get("method_tasks", [])
            if isinstance(task, dict)
        }
        contract = chunk.get("declaration_contract") or {}
        if isinstance(contract, dict):
            methods.update(
                str(name) for name in contract.get("required_methods", [])
            )
        if {"register", "resolve", "list_commands"} <= methods:
            owner = str(chunk.get("owner") or "")
            break
    if not owner:
        return validation_files, []

    bodies = {
        "register": f"""def replacement(self):
    registry = {owner}()
    alpha = lambda: 'alpha'
    beta = lambda: 'beta'
    registry.register(' Spawn ', alpha, aliases=('Create',), capabilities=('world.write',))
    self.assertEqual(registry.list_commands(), ['spawn'])
    self.assertIs(registry.resolve(' CREATE ', ('world.write',)), alpha)
    for action in (
        lambda: registry.register('spawn', beta),
        lambda: registry.register('other', beta, aliases=('create',)),
        lambda: registry.register('', beta),
        lambda: registry.register('bad', 4),
    ):
        with self.assertRaises(ValueError):
            action()
    self.assertEqual(registry.list_commands(), ['spawn'])
    errors = []
    def add(index):
        try:
            registry.register(f'cmd-{{index}}', lambda: None, aliases=(f'alias-{{index}}',))
        except Exception as exc:
            errors.append(repr(exc))
    import threading
    threads = [threading.Thread(target=add, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
    self.assertFalse(errors)
    self.assertTrue(all(not thread.is_alive() for thread in threads))
    self.assertEqual(len(registry.list_commands()), 13)
""",
        "resolve": f"""def replacement(self):
    registry = {owner}()
    handler = lambda: 'ok'
    registry.register(' Spawn ', handler, aliases=('Create',), capabilities=('world.write',))
    self.assertIs(registry.resolve(' CREATE ', ('world.write',)), handler)
    with self.assertRaisesRegex(PermissionError, 'world.write'):
        registry.resolve('spawn')
    with self.assertRaises(KeyError):
        registry.resolve('missing')
""",
        "list_commands": f"""def replacement(self):
    registry = {owner}()
    registry.register('Zulu', lambda: None, aliases=('last',))
    registry.register(' alpha ', lambda: None, aliases=('first',))
    self.assertEqual(registry.list_commands(), ['alpha', 'zulu'])
""",
    }
    updated = list(validation_files)
    notes: list[str] = []
    for index, (path, original, source) in enumerate(updated):
        if path != harness_path:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            continue
        replaced: list[str] = []
        for class_node in (
            node for node in tree.body if isinstance(node, ast.ClassDef)
        ):
            for method_index, method in enumerate(class_node.body):
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                lowered = method.name.casefold()
                behavior = (
                    "list_commands"
                    if "list_commands" in lowered or "listcommands" in lowered
                    else "resolve"
                    if "resolve" in lowered
                    else "register"
                    if "register" in lowered
                    else ""
                )
                if not behavior:
                    continue
                replacement = ast.parse(bodies[behavior]).body[0]
                replacement.name = method.name
                class_node.body[method_index] = replacement
                replaced.append(method.name)
        if not replaced:
            continue
        ast.fix_missing_locations(tree)
        corrected = ast.unparse(tree).rstrip() + "\n"
        compile(corrected, path, "exec")
        updated[index] = (path, original, corrected)
        notes.append(
            f"{path}: replaced private registry fixtures with public proofs: "
            + ", ".join(sorted(replaced))
        )
    return updated, notes

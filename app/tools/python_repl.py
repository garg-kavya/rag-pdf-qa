"""Sandboxed Python REPL for safe execution of LLM-generated calculation code."""
from __future__ import annotations

import asyncio
import io
import math
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.utils.logging import get_logger

logger = get_logger(__name__)

# Only these names are available inside executed code.
# __import__ is explicitly absent, blocking all import attempts.
_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": {
        "abs": abs, "round": round, "sum": sum, "min": min, "max": max,
        "pow": pow, "divmod": divmod,
        "int": int, "float": float, "str": str, "bool": bool,
        "list": list, "dict": dict, "tuple": tuple, "set": set,
        "len": len, "range": range, "enumerate": enumerate,
        "zip": zip, "sorted": sorted, "reversed": reversed,
        "map": map, "filter": filter,
        "True": True, "False": False, "None": None,
    },
    "math": math,
}

# Runs in a thread pool so asyncio event loop isn't blocked during exec()
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="repl")


class PythonREPL:
    """Execute LLM-generated Python code in a locked-down namespace.

    Only arithmetic builtins and the math module are available.
    All I/O, imports, and subprocess calls are blocked.

    Note: for production hardening, replace exec() with RestrictedPython
    to guard against __class__ / MRO escape tricks.
    """

    async def execute(self, code: str, timeout: float = 10.0) -> tuple[bool, str]:
        """Run *code* and return ``(success, output)``.

        Returns ``(True, stdout)`` on success or ``(False, error_message)``
        on syntax error, runtime exception, or timeout.
        """
        loop = asyncio.get_event_loop()
        try:
            output = await asyncio.wait_for(
                loop.run_in_executor(_EXECUTOR, self._run, code),
                timeout=timeout,
            )
            return True, output
        except asyncio.TimeoutError:
            return False, f"Execution timed out after {timeout:.0f}s"
        except Exception as exc:
            return False, str(exc)

    @staticmethod
    def _run(code: str) -> str:
        """Synchronous execution — called from a thread-pool worker."""
        stdout_buf = io.StringIO()

        def _print(*args: Any, **kwargs: Any) -> None:
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            stdout_buf.write(sep.join(str(a) for a in args) + end)

        exec_globals = {**_SAFE_GLOBALS, "print": _print}

        try:
            exec(compile(code, "<calculator>", "exec"), exec_globals)  # noqa: S102
        except SyntaxError as exc:
            raise RuntimeError(f"Syntax error in generated code: {exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"Runtime error: {exc}") from exc

        return stdout_buf.getvalue().strip() or "(no output)"

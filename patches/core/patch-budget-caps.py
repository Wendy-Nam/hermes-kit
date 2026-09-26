#!/usr/bin/env python3
"""Patch /opt/hermes/tools/budget_config.py to enforce 8k tool result cap and 24k turn budget."""
import sys
from pathlib import Path

TARGET = Path("/opt/hermes/tools/budget_config.py")

NEW_CONTENT = """\"\"\"Configurable budget constants for tool result persistence.
Per-tool resolution: pinned > config overrides > registry > default.\"\"\"

from dataclasses import dataclass, field
from typing import Dict

try:
    from agent.model_metadata import CHARS_PER_TOKEN
except ImportError:  # hermes-kit: upstream v2026.9.11 has no CHARS_PER_TOKEN (the Hostinger build does)
    CHARS_PER_TOKEN = 4

# Never overridden; read_file=inf prevents infinite persist->read->persist loops.
PINNED_THRESHOLDS: Dict[str, float] = {"read_file": float("inf")}

# Defaults: hard 8k cap per tool result, 24k turn aggregate, 1.5k preview.
DEFAULT_RESULT_SIZE_CHARS: int = 8_000
DEFAULT_TURN_BUDGET_CHARS: int = 24_000
DEFAULT_PREVIEW_SIZE_CHARS: int = 1_500
DEFAULT_MCP_RESULT_SIZE_CHARS: int = 4_000
MCP_TOOL_PREFIX: str = "mcp_"


def _configured_budget_values() -> tuple[int, int, int, int]:
    \"\"\"Read tool_budget block from config.yaml via load_config_readonly.\"\"\"
    default_res = DEFAULT_RESULT_SIZE_CHARS
    turn_bud = DEFAULT_TURN_BUDGET_CHARS
    preview = DEFAULT_PREVIEW_SIZE_CHARS
    mcp_res = DEFAULT_MCP_RESULT_SIZE_CHARS
    try:
        from hermes_cli.config import load_config_readonly
        data = load_config_readonly()
        block = data.get("tool_budget") if isinstance(data, dict) else None
        if isinstance(block, dict):
            if (raw := block.get("max_result_size_chars")) is not None and int(raw) > 0:
                default_res = int(raw)
            if (raw := block.get("turn_budget_chars")) is not None and int(raw) > 0:
                turn_bud = int(raw)
            if (raw := block.get("preview_size_chars")) is not None and int(raw) > 0:
                preview = int(raw)
            if (raw := block.get("mcp_result_size_chars")) is not None and int(raw) > 0:
                mcp_res = int(raw)
    except Exception:
        pass
    return default_res, turn_bud, preview, mcp_res


def _configured_mcp_result_size() -> int:
    return _configured_budget_values()[3]


@dataclass(frozen=True)
class BudgetConfig:
    default_result_size: int = DEFAULT_RESULT_SIZE_CHARS
    turn_budget: int = DEFAULT_TURN_BUDGET_CHARS
    preview_size: int = DEFAULT_PREVIEW_SIZE_CHARS
    mcp_result_size: int = DEFAULT_MCP_RESULT_SIZE_CHARS
    tool_overrides: Dict[str, int] = field(default_factory=dict)

    def resolve_threshold(self, tool_name: str) -> int | float:
        if tool_name in PINNED_THRESHOLDS:
            return PINNED_THRESHOLDS[tool_name]
        if tool_name in self.tool_overrides:
            return self.tool_overrides[tool_name]
        if tool_name.startswith(MCP_TOOL_PREFIX):
            return min(self.mcp_result_size, self.default_result_size)
        from tools.registry import registry
        registry_value = registry.get_max_result_size(tool_name, default=self.default_result_size)
        if registry_value == float("inf"):
            return registry_value
        return min(registry_value, self.default_result_size)


DEFAULT_BUDGET = BudgetConfig()

_CHARS_PER_TOKEN: int = CHARS_PER_TOKEN
_PER_RESULT_WINDOW_FRACTION: float = 0.15
_PER_TURN_WINDOW_FRACTION: float = 0.30
_MIN_RESULT_SIZE_CHARS: int = 8_000
_MIN_TURN_BUDGET_CHARS: int = 16_000


def budget_for_context_window(context_length: int | None) -> BudgetConfig:
    default_res, turn_bud, preview, mcp_res = _configured_budget_values()
    if not context_length or context_length <= 0:
        return BudgetConfig(
            default_result_size=default_res,
            turn_budget=turn_bud,
            preview_size=preview,
            mcp_result_size=mcp_res,
        )
    window_chars = context_length * _CHARS_PER_TOKEN
    return BudgetConfig(
        default_result_size=max(min(_MIN_RESULT_SIZE_CHARS, default_res), min(int(window_chars * _PER_RESULT_WINDOW_FRACTION), default_res)),
        turn_budget=max(min(_MIN_TURN_BUDGET_CHARS, turn_bud), min(int(window_chars * _PER_TURN_WINDOW_FRACTION), turn_bud)),
        preview_size=preview,
        mcp_result_size=mcp_res,
    )
"""

def main():
    if not TARGET.exists():
        print(f"Target {TARGET} not found!")
        return 1
    TARGET.write_text(NEW_CONTENT, encoding="utf-8")
    print(f"Successfully patched {TARGET} with 8k budget caps.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_CONFIG_PATHS = (
    Path("config/llm.toml"),
    Path("src/config/llm.toml"),
)


class LLMConfig:
    def __init__(self, values: dict[str, Any]):
        self.values = values

    @classmethod
    def load(cls, path: str | None = None) -> "LLMConfig":
        config_path = cls._resolve_path(path)
        if not config_path:
            return cls({})

        with config_path.open("rb") as config_file:
            return cls(tomllib.load(config_file))

    @staticmethod
    def _resolve_path(path: str | None) -> Path | None:
        candidates = (Path(path),) if path else DEFAULT_CONFIG_PATHS
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def get(self, section: str, key: str, default: Any = None) -> Any:
        value = self._nested_section(section).get(key)
        return value if value not in (None, "") else default

    def section(self, section: str) -> dict[str, Any]:
        return deepcopy(self._nested_section(section))

    def _nested_section(self, section: str) -> dict[str, Any]:
        current: Any = self.values
        for part in section.split("."):
            if not isinstance(current, dict):
                return {}
            current = current.get(part, {})
        return current if isinstance(current, dict) else {}

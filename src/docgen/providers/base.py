from typing import Protocol

from docgen.config import GenerationConfig
from docgen.models import Blueprint, Content


class ContentProvider(Protocol):
    def generate(self, blueprint: Blueprint, config: GenerationConfig) -> Content:
        """Produce a canonical candidate; orchestration validates identity before saving."""
        ...

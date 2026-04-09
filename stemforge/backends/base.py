from abc import ABC, abstractmethod
from pathlib import Path


class AbstractBackend(ABC):

    @abstractmethod
    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """
        Separate audio into stems.
        Returns dict mapping stem name → output WAV path.
        e.g. {"drums": Path("~/stemforge/processed/track/drums.wav"), ...}
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

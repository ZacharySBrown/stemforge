import os, time, requests
from pathlib import Path
from rich.console import Console
from .base import AbstractBackend
from ..config import LALAL_BASE, LALAL_PRESETS, LALAL_DEFAULT_PRESET

console = Console()


class LalalBackend(AbstractBackend):

    @property
    def name(self) -> str:
        return "LALAL.AI"

    def _key(self) -> str:
        key = os.environ.get("LALAL_LICENSE_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "LALAL_LICENSE_KEY not set.\n"
                "  1. Subscribe at lalal.ai (Pro plan, $15/mo)\n"
                "  2. Profile page → copy Activation Key\n"
                "  3. export LALAL_LICENSE_KEY=your_key"
            )
        return key

    def _h(self) -> dict:
        return {"X-License-Key": self._key()}

    def check_minutes(self) -> dict:
        r = requests.post(f"{LALAL_BASE}/limits/minutes_left/",
                         headers=self._h(), timeout=15)
        r.raise_for_status()
        return r.json()

    def _upload(self, path: Path) -> str:
        with open(path, "rb") as f:
            r = requests.post(
                f"{LALAL_BASE}/upload/",
                headers={
                    **self._h(),
                    "Content-Disposition": f"attachment; filename={path.name}",
                    "Content-Type": "application/octet-stream",
                },
                data=f, timeout=300,
            )
        r.raise_for_status()
        return r.json()["source_id"]

    def _submit(self, source_id: str, stems: list[str]) -> str:
        r = requests.post(
            f"{LALAL_BASE}/split/multistem/",
            headers={**self._h(), "Content-Type": "application/json"},
            json={"source_id": source_id, "stem_list": stems},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["task_id"]

    def _poll(self, task_id: str, interval: int = 8, timeout: int = 600) -> list:
        deadline = time.time() + timeout
        dots = 0
        while time.time() < deadline:
            r = requests.post(
                f"{LALAL_BASE}/check/",
                headers={**self._h(), "Content-Type": "application/json"},
                json={"task_ids": [task_id]}, timeout=15,
            )
            r.raise_for_status()
            task = r.json().get(task_id, {})
            status = task.get("status")
            if status == "success":
                console.print()
                return task.get("tracks", [])
            elif status == "error":
                raise RuntimeError(f"LALAL task failed: {task.get('error')}")
            pct = task.get("progress", 0)
            dots = (dots + 1) % 4
            console.print(f"  Processing{'.' * dots}   {pct:.0f}%", end="\r")
            time.sleep(interval)
        raise TimeoutError(f"Task {task_id} timed out")

    def _download(self, tracks: list, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        downloaded = {}
        for track in tracks:
            url = track.get("url")
            label = track.get("label", "unknown")
            if not url:
                continue
            if label == "no_multistem":
                label = "residual"
            ext = Path(url.split("?")[0]).suffix or ".wav"
            out = output_dir / f"{label}{ext}"
            r = requests.get(url, stream=True, timeout=120)
            r.raise_for_status()
            with open(out, "wb") as f:
                for chunk in r.iter_content(65536):
                    f.write(chunk)
            downloaded[label] = out
            console.print(f"  [green]OK[/green] {label}: {out.name}")
        return downloaded

    def _cleanup(self, source_id: str):
        try:
            requests.post(
                f"{LALAL_BASE}/delete/",
                headers={**self._h(), "Content-Type": "application/json"},
                json={"source_id": source_id}, timeout=15,
            )
        except Exception:
            pass

    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """
        kwargs:
          stems (list[str]): explicit stem list, OR
          preset (str): key from LALAL_PRESETS
        """
        stems = kwargs.get("stems")
        if stems is None:
            preset = kwargs.get("preset", LALAL_DEFAULT_PRESET)
            stems = LALAL_PRESETS.get(preset, LALAL_PRESETS[LALAL_DEFAULT_PRESET])

        console.print(f"  Backend: [cyan]LALAL.AI[/cyan]  stems: {', '.join(stems)}")
        console.print(f"  Cost: ~{len(stems)}x track duration in fast minutes")

        source_id = self._upload(audio_path)
        task_id = self._submit(source_id, stems)
        console.print(f"  Job: [dim]{task_id}[/dim]")

        t0 = time.time()
        tracks = self._poll(task_id)
        console.print(f"  Done in {time.time() - t0:.0f}s")

        result = self._download(tracks, output_dir)
        self._cleanup(source_id)
        return result

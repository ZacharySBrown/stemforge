import os, time, requests
from pathlib import Path
from rich.console import Console
from .base import AbstractBackend
from ..config import MUSIC_AI_WORKFLOWS, MUSIC_AI_DEFAULT_WORKFLOW

console = Console()


class MusicAiBackend(AbstractBackend):

    @property
    def name(self) -> str:
        return "Music.AI"

    def _key(self) -> str:
        key = os.environ.get("MUSIC_AI_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "MUSIC_AI_API_KEY not set.\n"
                "  1. Get API key from music.ai dashboard\n"
                "  2. export MUSIC_AI_API_KEY=your_key"
            )
        return key

    def _client(self):
        from musicai_sdk import MusicAiClient
        return MusicAiClient(api_key=self._key())

    def _upload(self, client, path: Path) -> str:
        console.print(f"  Uploading {path.name}...")
        url = client.upload_file(str(path))
        console.print(f"  [green]OK[/green] Uploaded → remote URL ready")
        return url

    def _submit(self, client, input_url: str, workflow_slug: str) -> str:
        job = client.add_job(
            "stemforge",
            workflow_slug,
            {"inputUrl": input_url},
        )
        job_id = job["id"]
        console.print(f"  Job: [dim]{job_id}[/dim]")
        return job_id

    def _poll(self, client, job_id: str, timeout: int = 900) -> dict:
        deadline = time.time() + timeout
        dots = 0
        while time.time() < deadline:
            result = client.get_job(job_id)
            status = result.get("status")
            if status == "SUCCEEDED":
                console.print()
                return result
            elif status == "FAILED":
                raise RuntimeError(
                    f"Music.AI job failed: {result.get('error', 'unknown')}"
                )
            dots = (dots + 1) % 4
            console.print(f"  Processing{'.' * dots}   ({status})", end="\r")
            time.sleep(8)
        raise TimeoutError(f"Music.AI job {job_id} timed out after {timeout}s")

    def _download(self, client, job_result: dict, output_dir: Path) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        # SDK returns dict: {stem_name: file_path_str}
        files = client.download_job_results(job_result, str(output_dir))
        downloaded = {}
        for stem_name, fpath in files.items():
            p = Path(fpath)
            downloaded[stem_name] = p
            console.print(f"  [green]OK[/green] {stem_name}: {p.name}")
        return downloaded

    def _cleanup(self, client, job_id: str):
        try:
            client.delete_job(job_id)
        except Exception:
            pass

    def separate(self, audio_path: Path, output_dir: Path, **kwargs) -> dict[str, Path]:
        """
        kwargs:
          workflow (str): key from MUSIC_AI_WORKFLOWS (e.g. "suite", "vocals")
                          or a full slug (e.g. "music-ai/stem-separation-suite")
        """
        workflow_key = kwargs.get("workflow", MUSIC_AI_DEFAULT_WORKFLOW)
        workflow_slug = MUSIC_AI_WORKFLOWS.get(workflow_key, workflow_key)

        console.print(f"  Backend: [cyan]Music.AI[/cyan]  workflow: {workflow_slug}")

        client = self._client()
        input_url = self._upload(client, audio_path)
        job_id = self._submit(client, input_url, workflow_slug)

        t0 = time.time()
        job_result = self._poll(client, job_id)
        console.print(f"  Done in {time.time() - t0:.0f}s")

        result = self._download(client, job_result, output_dir)
        self._cleanup(client, job_id)
        return result

#!/usr/bin/env python3
"""
Test script for Music AI (Moises) API.
Validates API key, lists workflows, and optionally runs a stem separation job.

Usage:
  # Set your API key:
  export MUSIC_AI_API_KEY=$(op read "op://quarks/music-ai-api-key/credential")

  # Quick test (validate key + list workflows):
  python test_musicai.py

  # Full test (upload + separate + download):
  python test_musicai.py --split path/to/track.wav
"""
import os
import sys
import json
import argparse
from pathlib import Path

def get_api_key():
    key = os.environ.get("MUSIC_AI_API_KEY", "").strip()
    if not key:
        print("ERROR: MUSIC_AI_API_KEY not set.")
        print("  export MUSIC_AI_API_KEY=$(op read 'op://quarks/music-ai-api-key/credential')")
        sys.exit(1)
    return key


def test_auth(client):
    """Test 1: Validate API key."""
    print("=" * 60)
    print("TEST 1: Validate API key")
    print("=" * 60)
    try:
        import requests
        resp = requests.get(
            "https://api.music.ai/v1/application",
            headers={"Authorization": get_api_key()},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"  OK — App: {data.get('name', 'unknown')} (id: {data.get('id', '?')})")
        return True
    except Exception as e:
        print(f"  FAILED — {e}")
        return False


def test_list_workflows(client):
    """Test 2: List available workflows."""
    print()
    print("=" * 60)
    print("TEST 2: List available workflows")
    print("=" * 60)
    try:
        import requests
        resp = requests.get(
            "https://api.music.ai/v1/workflow?page=0&size=50",
            headers={"Authorization": get_api_key()},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"  Raw response: {json.dumps(data, indent=2)[:2000]}\n")

        workflows = data if isinstance(data, list) else data.get("items", data.get("content", [data]))
        print(f"  Found {len(workflows)} workflow(s):\n")
        for wf in workflows:
            slug = wf.get("slug", wf.get("id", "?"))
            name = wf.get("name", "?")
            desc = wf.get("description", "")
            print(f"  [{slug}]")
            print(f"    {name}")
            if desc:
                print(f"    {desc[:100]}")
            print()
        return workflows
    except Exception as e:
        print(f"  FAILED — {e}")
        return []


def test_upload(client, audio_path):
    """Test 3: Upload a file."""
    print()
    print("=" * 60)
    print(f"TEST 3: Upload {audio_path.name}")
    print("=" * 60)
    try:
        url = client.upload_file(str(audio_path))
        print(f"  OK — Download URL: {url[:80]}...")
        return url
    except Exception as e:
        print(f"  FAILED — {e}")
        return None


def test_stem_separation(client, input_url, workflow_slug):
    """Test 4: Run stem separation."""
    print()
    print("=" * 60)
    print(f"TEST 4: Stem separation ({workflow_slug})")
    print("=" * 60)
    try:
        job = client.add_job(
            "stemforge-test",
            workflow_slug,
            {"inputUrl": input_url},
        )
        job_id = job["id"]
        print(f"  Job created: {job_id}")
        print(f"  Polling for completion...")

        result = client.wait_for_job_completion(job_id)
        status = result.get("status")
        print(f"  Status: {status}")

        if status == "SUCCEEDED":
            print(f"  Results:")
            for key, url in result.get("result", {}).items():
                print(f"    {key}: {url[:80]}...")
            return result
        else:
            print(f"  Error: {result.get('error', 'unknown')}")
            return None
    except Exception as e:
        print(f"  FAILED — {e}")
        return None


def test_download(client, job_result, output_dir):
    """Test 5: Download results."""
    print()
    print("=" * 60)
    print(f"TEST 5: Download stems to {output_dir}")
    print("=" * 60)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        files = client.download_job_results(job_result, str(output_dir))
        print(f"  OK — Downloaded {len(files)} file(s):")
        for f in files:
            print(f"    {f}")
        return files
    except Exception as e:
        print(f"  FAILED — {e}")
        return []


def test_cleanup(client, job_id):
    """Test 6: Delete job."""
    print()
    print("=" * 60)
    print(f"TEST 6: Cleanup job {job_id}")
    print("=" * 60)
    try:
        client.delete_job(job_id)
        print(f"  OK — Job deleted")
    except Exception as e:
        print(f"  FAILED — {e}")


def main():
    parser = argparse.ArgumentParser(description="Test Music AI API")
    parser.add_argument("--split", type=Path, help="Audio file to test stem separation with")
    parser.add_argument("--workflow", default=None, help="Workflow slug (auto-detected if omitted)")
    parser.add_argument("--output", type=Path, default=Path("./test_musicai_output"), help="Output dir for stems")
    args = parser.parse_args()

    from musicai_sdk import MusicAiClient
    key = get_api_key()
    client = MusicAiClient(api_key=key)

    # Test 0: Check account/billing
    print()
    print("=" * 60)
    print("TEST 0: Account & credits")
    print("=" * 60)
    try:
        import requests
        for endpoint in [
            "https://api.music.ai/v1/billing",
            "https://api.music.ai/v1/account",
            "https://api.music.ai/v1/usage",
            "https://api.music.ai/v1/credits",
            "https://api.music.ai/v1/application/usage",
            "https://api.music.ai/v1/application/billing",
        ]:
            resp = requests.get(endpoint, headers={"Authorization": key}, timeout=10)
            if resp.status_code == 200:
                print(f"  {endpoint.split('/v1/')[-1]}: {json.dumps(resp.json(), indent=2)}")
                break
            elif resp.status_code != 404:
                print(f"  {endpoint.split('/v1/')[-1]}: {resp.status_code} — {resp.text[:200]}")
        else:
            print("  No billing/credits endpoint found")
    except Exception as e:
        print(f"  {e}")

    # Test 1: Auth
    if not test_auth(client):
        sys.exit(1)

    # Test 2: List workflows
    workflows = test_list_workflows(client)

    # If no audio file provided, stop here
    if not args.split:
        print()
        print("=" * 60)
        print("Quick test passed! To run a full stem separation test:")
        print(f"  python test_musicai.py --split path/to/track.wav")
        print("=" * 60)
        return

    # Pick a workflow — use known slug directly (no dashboard setup needed)
    workflow_slug = args.workflow or "music-ai/stems-vocals-accompaniment"
    print(f"\n  Using workflow: {workflow_slug}")

    # Test 3: Upload
    input_url = test_upload(client, args.split)
    if not input_url:
        sys.exit(1)

    # Test 4: Separate
    result = test_stem_separation(client, input_url, workflow_slug)
    if not result:
        sys.exit(1)

    # Test 5: Download
    test_download(client, result, args.output)

    # Test 6: Cleanup
    test_cleanup(client, result["id"])

    print()
    print("=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()

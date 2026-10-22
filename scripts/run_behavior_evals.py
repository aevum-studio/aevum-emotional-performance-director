#!/usr/bin/env python3
"""Run opt-in live behavioral evaluations against an uploaded temporary skill."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "aevum-emotional-performance-director"
CASES_FILE = ROOT / "evals" / "cases.jsonl"
API_BASE = "https://api.openai.com/v1"


@dataclass(frozen=True)
class Config:
    model: str
    judge_model: str
    workers: int
    timeout: int
    api_key: str


def api_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def request_json(
    method: str,
    url: str,
    *,
    timeout: int,
    retries: int = 4,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    body: bytes | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    delay = 2.0
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, data=body, headers=request_headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = response.read()
                return json.loads(content) if content else {}
        except urllib.error.HTTPError as exc:
            status = exc.code
            detail = exc.read().decode("utf-8", errors="replace")
            if status not in {404, 408, 409, 429, 500, 502, 503, 504} or attempt == retries:
                raise RuntimeError(f"{method} {url} failed ({status}): {detail[:1000]}") from exc
        except urllib.error.URLError as exc:
            if attempt == retries:
                raise RuntimeError(f"{method} {url} failed: {exc}") from exc
        time.sleep(delay)
        delay = min(delay * 2, 20)
    raise AssertionError("unreachable")


def make_skill_zip(destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(SKILL_DIR.rglob("*")):
            if path.is_file():
                arcname = Path(SKILL_DIR.name) / path.relative_to(SKILL_DIR)
                bundle.write(path, arcname.as_posix())


def upload_skill(zip_path: Path, config: Config) -> dict[str, Any]:
    boundary = f"----aevum-{uuid.uuid4().hex}"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{zip_path.name}"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode("utf-8")
    body = prefix + zip_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode("utf-8")
    return request_json(
        "POST",
        f"{API_BASE}/skills",
        timeout=config.timeout,
        headers={**api_headers(config.api_key), "Content-Type": f"multipart/form-data; boundary={boundary}"},
        body=body,
    )


def delete_skill(skill_id: str, config: Config) -> None:
    try:
        request_json(
            "DELETE",
            f"{API_BASE}/skills/{skill_id}",
            headers=api_headers(config.api_key),
            timeout=config.timeout,
            retries=1,
        )
    except RuntimeError as exc:
        if "failed (404)" not in str(exc):
            print(f"WARNING: temporary skill cleanup failed: {exc}", file=sys.stderr)


def output_text(response: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                chunks.append(content.get("text", ""))
    return "\n".join(chunks).strip()


def run_case(case: dict[str, Any], skill: dict[str, Any], config: Config) -> dict[str, Any]:
    started = time.monotonic()
    version = str(skill.get("default_version") or skill.get("latest_version") or "latest")
    payload = {
        "model": config.model,
        "tools": [
            {
                "type": "shell",
                "environment": {
                    "type": "container_auto",
                    "skills": [
                        {
                            "type": "skill_reference",
                            "skill_id": skill["id"],
                            "version": version,
                        }
                    ],
                },
            }
        ],
        "input": case["prompt"],
    }
    response = request_json(
        "POST",
        f"{API_BASE}/responses",
        timeout=config.timeout,
        headers={**api_headers(config.api_key), "Content-Type": "application/json"},
        json_body=payload,
    )
    answer = output_text(response)
    judge_prompt = {
        "case": case,
        "candidate_response": answer,
        "instructions": (
            "Judge only against the case criteria. Return strict JSON with keys score (0-100 integer), "
            "passed (boolean), reasons (array of short strings), and violations (array of short strings). "
            "For should_activate=false cases, reward a normal direct answer without unsolicited acting analysis. "
            "Pass at 80 or above. Do not reward verbosity by itself."
        ),
    }
    judge_response = request_json(
        "POST",
        f"{API_BASE}/responses",
        timeout=config.timeout,
        headers={**api_headers(config.api_key), "Content-Type": "application/json"},
        json_body={
            "model": config.judge_model,
            "input": json.dumps(judge_prompt, ensure_ascii=False),
        },
    )
    raw_judgment = output_text(judge_response)
    try:
        cleaned = raw_judgment.strip().removeprefix("```json").removesuffix("```").strip()
        judgment = json.loads(cleaned)
    except json.JSONDecodeError:
        judgment = {"score": 0, "passed": False, "reasons": ["Judge returned invalid JSON"], "violations": [raw_judgment[:500]]}
    judgment["passed"] = bool(judgment.get("passed")) and int(judgment.get("score", 0)) >= 80
    return {
        "id": case["id"],
        "category": case["category"],
        "should_activate": case["should_activate"],
        "prompt": case["prompt"],
        "response": answer,
        "judgment": judgment,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "response_id": response.get("id"),
        "judge_response_id": judge_response.get("id"),
    }


def load_cases(path: Path, limit: int) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [case["id"] for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case IDs")
    return cases[:limit] if limit > 0 else cases


def write_reports(results: list[dict[str, Any]], output_dir: Path, config: Config) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    passed = sum(bool(result["judgment"].get("passed")) for result in results)
    report = {
        "model": config.model,
        "judge_model": config.judge_model,
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 4) if results else 0,
        "results": results,
    }
    (output_dir / "eval-report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "# AEVUM behavioral evaluation",
        "",
        f"- Task model: `{config.model}`",
        f"- Judge model: `{config.judge_model}`",
        f"- Passed: **{passed}/{len(results)}**",
        "",
        "| Case | Category | Score | Pass |",
        "|---|---|---:|:---:|",
    ]
    for result in results:
        judgment = result["judgment"]
        lines.append(f"| `{result['id']}` | {result['category']} | {judgment.get('score', 0)} | {'✅' if judgment.get('passed') else '❌'} |")
    lines.extend(["", "See `eval-report.json` for prompts, responses, reasons, and violations."])
    (output_dir / "eval-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--judge-model", default="gpt-6-astra")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--cases", type=Path, default=CASES_FILE)
    parser.add_argument("--output", type=Path, default=ROOT / "results")
    args = parser.parse_args()
    if os.environ.get("RUN_LIVE_EVALS") != "1":
        print("Live API calls are disabled. Set RUN_LIVE_EVALS=1 to opt in.", file=sys.stderr)
        return 2
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY is required.", file=sys.stderr)
        return 2
    if args.limit < 0 or not 1 <= args.workers <= 16:
        print("limit must be >= 0 and workers must be between 1 and 16", file=sys.stderr)
        return 2
    cases = load_cases(args.cases, args.limit)
    config = Config(args.model, args.judge_model, args.workers, args.timeout, api_key)
    skill: dict[str, Any] | None = None
    temp_dir = Path(tempfile.mkdtemp(prefix="aevum-evals-"))
    try:
        archive = temp_dir / "aevum-emotional-performance-director.zip"
        make_skill_zip(archive)
        skill = upload_skill(archive, config)
        results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.workers) as executor:
            future_map = {executor.submit(run_case, case, skill, config): case for case in cases}
            for future in concurrent.futures.as_completed(future_map):
                case = future_map[future]
                try:
                    result = future.result()
                except Exception as exc:  # Keep the full batch running and report the failed case.
                    result = {
                        "id": case["id"],
                        "category": case["category"],
                        "should_activate": case["should_activate"],
                        "prompt": case["prompt"],
                        "response": "",
                        "judgment": {"score": 0, "passed": False, "reasons": [str(exc)], "violations": ["execution_error"]},
                        "elapsed_seconds": 0,
                    }
                results.append(result)
                print(f"[{len(results)}/{len(cases)}] {case['id']}: {result['judgment'].get('score', 0)}")
        results.sort(key=lambda item: item["id"])
        write_reports(results, args.output, config)
        return 0 if all(result["judgment"].get("passed") for result in results) else 1
    finally:
        if skill and skill.get("id"):
            delete_skill(skill["id"], config)
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())

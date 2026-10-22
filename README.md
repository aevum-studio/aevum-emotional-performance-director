# AEVUM Emotional Performance Director

A Codex skill for directing and reviewing psychologically grounded character performance in narrative film, animation, dramatic advertising, storyboards, dialogue, and AI video prompts.

## Install on Codex Desktop for macOS

1. Download `dist/aevum-emotional-performance-director.zip`.
2. Extract the archive.
3. Move the extracted `aevum-emotional-performance-director` folder to `~/.codex/skills/`.
4. Restart Codex and start a new chat.
5. Try: `$aevum-emotional-performance-director Review this scene's motivation, performance beats, and emotional continuity.`

The installed file should be located at:

```text
~/.codex/skills/aevum-emotional-performance-director/SKILL.md
```

## Repository layout

```text
skills/aevum-emotional-performance-director/  Skill source
dist/                                         Installable ZIP
evals/cases.jsonl                             Behavioral evaluation corpus
scripts/validate_skill.py                     Offline structural validator
scripts/run_behavior_evals.py                 Opt-in live evaluation runner
tests/                                        Offline regression tests
.github/workflows/                            GitHub Actions
```

## Free checks

The `Validate skill` workflow runs on every push and pull request. It checks frontmatter, naming, internal links, package shape, ZIP integrity, unexpected files, and regression tests. It does not call an API.

Run the same checks locally:

```bash
python3 scripts/validate_skill.py
python3 -m unittest discover -s tests -v
```

## Behavioral evaluations

The `Behavior evaluations` workflow is manual because it makes paid OpenAI API calls and uses hosted shell containers. It uploads a temporary skill version, runs the selected cases, grades each result, saves JSON and Markdown reports as workflow artifacts, and deletes the temporary skill when it finishes. The runner uses only the Python standard library.

Before the first run:

1. Add an Actions repository secret named `OPENAI_API_KEY`.
2. Open **Actions → Behavior evaluations → Run workflow**.
3. Start with a small `case_limit`, such as `5`.
4. Increase the limit only after checking cost and output quality. Use `0` to run every case.

Inputs let you choose the task model, judge model, case limit, and parallelism. The live runner refuses to start unless `RUN_LIVE_EVALS=1` is explicitly set by the manual workflow.

## Evaluation design

The corpus covers automatic activation, explicit invocation, authorship preservation, evidence limits, emotional continuity, comedy, advertisements, short-shot feasibility, multilingual prompts, simple-answer routing, and non-narrative tasks that should not activate the skill.

Automated model grading is useful for regression detection, but it is not a substitute for human review. Inspect low-scoring and borderline results before changing the skill.

## Security

- Never commit API keys. Store `OPENAI_API_KEY` only as a GitHub Actions secret.
- Live evaluations run only through manual workflow dispatch.
- Pull requests from forks cannot invoke the paid workflow with repository secrets.
- The temporary uploaded skill is deleted in a cleanup step when possible.

## License

No license has been granted yet. Add a license only after the copyright owner chooses one.

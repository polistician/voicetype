"""promoter.py — turn candidate observations into deterministic bias updates.

The supervisor pipeline appends candidates into the SQLite store at
`~/.voicetype/supervisor_candidates.db`. Each row is one observation from
one (fast, slow) transcript diff. By design, ONE observation is not enough
to commit a change — the supervisor might be wrong, the audio might have
been noisy, the user might have intentionally said something unusual.

This module applies count thresholds: a vocabulary word only gets added
once it shows up in ≥2 independent recordings; a substitution rule needs
≥3. Once a candidate is promoted, its row gets `promoted_at` stamped so
the next run skips it.

The promoter writes through to `vocabulary.add(source="supervisor")` and
`corrections.add_correction(source="supervisor")`. Those layers already
feed the fast model's bias prompt + post-correction pass, so promoting
here automatically improves the next dictation with no further wiring.

Threshold tuning:
    new_vocab        ≥ 2 distinct audio recordings, word length ≥ 4
    substitution     ≥ 3 distinct audio recordings, exact (from, to) match
    punctuation      never promoted (cleanup_backend already handles it)
    language_switch  ≥ 1 occurrence (rare, low risk)

A candidate from a single audio file that came in via a `source="user_edit"`
tag bypasses the count threshold — one user confirmation is plenty.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Callable, Optional

import supervisor_candidates as candidates


# Promotion thresholds (distinct audio_path count required).
THRESHOLD_NEW_VOCAB = 2
THRESHOLD_SUBSTITUTION = 3
THRESHOLD_LANGUAGE_SWITCH = 1


def _ensure_str(payload: dict, *keys: str) -> tuple[str, ...]:
    """Pull string fields from a payload dict, defending against None."""
    return tuple((str(payload.get(k) or "")).strip() for k in keys)


def _group_new_vocab(rows: list) -> dict[str, tuple[int, set[str], float, list[int]]]:
    """Group rows by the canonical (lowercased) vocab word.

    Returns: word_lower → (count, distinct_audio_paths, max_confidence, ids)
    where `count` is the count of distinct audio paths (NOT raw rows — a
    chatty single recording shouldn't reach threshold on its own).
    """
    grouped: dict[str, tuple[int, set[str], float, list[int]]] = {}
    raw: dict[str, dict] = defaultdict(lambda: {"audio": set(), "conf": 0.0, "ids": [], "surface": ""})
    for r in rows:
        try:
            payload = json.loads(r["payload"])
        except Exception:
            continue
        (word,) = _ensure_str(payload, "word")
        if not word:
            continue
        key = word.lower()
        slot = raw[key]
        slot["audio"].add(r["audio_path"])
        slot["conf"] = max(slot["conf"], float(r["confidence"]))
        slot["ids"].append(int(r["id"]))
        if not slot["surface"]:
            slot["surface"] = word  # remember first-seen casing
    for key, slot in raw.items():
        grouped[key] = (len(slot["audio"]), slot["audio"], slot["conf"], slot["ids"])
        # piggy-back the surface form on the slot dict so the caller can read it
        grouped[key] = (
            len(slot["audio"]), slot["audio"], slot["conf"], slot["ids"],
            slot["surface"],  # extra slot for surface form
        )
    return grouped


def _group_substitution(rows: list) -> dict[tuple[str, str], tuple[int, set[str], float, list[int]]]:
    """Group substitution rows by (from_lower, to_lower)."""
    raw: dict[tuple[str, str], dict] = defaultdict(lambda: {"audio": set(), "conf": 0.0, "ids": []})
    for r in rows:
        try:
            payload = json.loads(r["payload"])
        except Exception:
            continue
        frm, to_ = _ensure_str(payload, "from", "to")
        if not frm or not to_:
            continue
        key = (frm.lower(), to_)  # preserve target casing in the key
        slot = raw[key]
        slot["audio"].add(r["audio_path"])
        slot["conf"] = max(slot["conf"], float(r["confidence"]))
        slot["ids"].append(int(r["id"]))
    return {k: (len(v["audio"]), v["audio"], v["conf"], v["ids"]) for k, v in raw.items()}


def run(*, dry_run: bool = False,
        log: Optional[Callable[[str], None]] = None) -> dict:
    """Walk unpromoted candidates, apply thresholds, write through.

    Args:
        dry_run: when True, compute what would be promoted but don't touch
                 vocabulary.json / corrections.json or mark rows promoted.
                 Used by the Settings panel preview.
        log: optional callable to receive human-readable progress lines.

    Returns:
        dict with keys: new_vocab_promoted, substitutions_promoted,
                        language_switches, evaluated_rows.
    """
    log_fn = log or (lambda _: None)

    new_vocab_rows = candidates.unpromoted(type_="new_vocab")
    substitution_rows = candidates.unpromoted(type_="substitution")
    language_rows = candidates.unpromoted(type_="language_switch")

    summary = {
        "evaluated_rows": len(new_vocab_rows) + len(substitution_rows) + len(language_rows),
        "new_vocab_promoted": 0,
        "substitutions_promoted": 0,
        "language_switches": 0,
    }

    # ── new_vocab ────────────────────────────────────────────────────────
    if new_vocab_rows:
        grouped = _group_new_vocab(new_vocab_rows)
        promoted_ids: list[int] = []
        for word_lower, group in grouped.items():
            distinct_count, _audios, _conf, ids, surface = group
            if distinct_count < THRESHOLD_NEW_VOCAB:
                continue
            log_fn(f"[promoter] new_vocab {surface!r} from {distinct_count} clips")
            if not dry_run:
                try:
                    import vocabulary as vocab
                    vocab.add(surface, source="supervisor")
                except Exception as e:  # pragma: no cover
                    log_fn(f"[promoter] vocab.add failed for {surface!r}: {e}")
                    continue
            promoted_ids.extend(ids)
            summary["new_vocab_promoted"] += 1
        if not dry_run and promoted_ids:
            candidates.mark_promoted(promoted_ids)

    # ── substitution ──────────────────────────────────────────────────────
    if substitution_rows:
        grouped = _group_substitution(substitution_rows)
        promoted_ids: list[int] = []
        for (frm, to_), (distinct_count, _audios, _conf, ids) in grouped.items():
            if distinct_count < THRESHOLD_SUBSTITUTION:
                continue
            log_fn(f"[promoter] substitution {frm!r} → {to_!r} from {distinct_count} clips")
            if not dry_run:
                try:
                    import corrections as corr
                    corr.add_correction(frm, to_, source="supervisor")
                except Exception as e:  # pragma: no cover
                    log_fn(f"[promoter] add_correction failed for {frm!r}: {e}")
                    continue
            promoted_ids.extend(ids)
            summary["substitutions_promoted"] += 1
        if not dry_run and promoted_ids:
            candidates.mark_promoted(promoted_ids)

    # ── language_switch ─────────────────────────────────────────────────
    if language_rows:
        promoted_ids = [int(r["id"]) for r in language_rows]
        if promoted_ids:
            log_fn(f"[promoter] language_switch hints: {len(promoted_ids)}")
            if not dry_run:
                _maybe_relax_input_language(log_fn)
                candidates.mark_promoted(promoted_ids)
            summary["language_switches"] = len(promoted_ids)

    return summary


def _maybe_relax_input_language(log_fn: Callable[[str], None]) -> None:
    """If `input_language` is pinned to a single ISO code and the supervisor
    spotted a language switch, flip it to "auto" so Whisper detects per clip."""
    cfg_path = os.path.expanduser("~/.voicetype/config.json")
    if not os.path.exists(cfg_path):
        return
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
    except Exception:
        return
    current = (cfg.get("input_language") or "").strip().lower()
    if current in ("auto", "", None):
        return
    cfg["input_language"] = "auto"
    try:
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
        log_fn(f"[promoter] input_language relaxed: {current!r} → 'auto'")
    except Exception:
        pass


# ── CLI -----------------------------------------------------------------------
#
# `python -m promoter` runs a one-shot promotion pass and prints the summary.
# Useful for end-to-end verification while the idle trigger isn't wired yet.

def _cli(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m promoter")
    p.add_argument("--dry-run", action="store_true",
                   help="compute what would be promoted but don't write")
    p.add_argument("--quiet", action="store_true",
                   help="suppress per-candidate log lines")
    args = p.parse_args(argv)

    def _log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    summary = run(dry_run=args.dry_run, log=_log)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))

"""Reversible removal of labeled records; source journals stay intact."""

import json
import re

import server as db


def trash_folder():
    return db.DATA / "trash" / "segments"


def trashed_records():
    return [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(trash_folder().glob("*.json"))
    ]


def move_records(ids, restore=False):
    ids = list(dict.fromkeys(ids))
    if not ids or any(not re.fullmatch(r"[0-9a-f]{32}", sid) for sid in ids):
        raise ValueError("삭제하거나 복원할 기록을 선택하세요.")
    source, target = (
        (trash_folder(), db.SEGMENTS)
        if restore
        else (db.SEGMENTS, trash_folder())
    )
    # Validate the complete batch before touching any record. Never overwrite.
    with db.LOCK:
        for sid in ids:
            if (
                not (source / f"{sid}.json").is_file()
                or (target / f"{sid}.json").exists()
            ):
                raise ValueError(
                    "목록이 변경되었습니다. 새로 고침 후 다시 선택하세요."
                )
        target.mkdir(parents=True, exist_ok=True)
        moved = []
        try:
            for sid in ids:
                (source / f"{sid}.json").rename(target / f"{sid}.json")
                moved.append(sid)
        except OSError:
            for sid in reversed(moved):
                (target / f"{sid}.json").rename(source / f"{sid}.json")
            raise
    return len(moved)

"""profile.yaml 읽기. 환경변수 AGENT_PROFILE 로 경로를 바꿀 수 있다 (테스트용)."""
import os
from pathlib import Path

import yaml

from collector import storage


def path() -> Path:
    return Path(os.getenv("AGENT_PROFILE") or storage.ROOT / "profile.yaml")


def load() -> tuple[dict, bool]:
    """(프로필, 파일이 있는지). 파일이 없으면 ({}, False)."""
    p = path()
    if not p.exists():
        return {}, False
    with open(p, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}), True

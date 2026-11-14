"""Deterministic tests for the SQAO V2.5 MTF synchronization gate."""
from datetime import datetime, timezone
from ENGINE.mtf_sync import audit_mtf_synchronization


def snap(as_of, frames):
    return {"generated_at_utc": datetime.fromtimestamp(as_of, timezone.utc).isoformat(),
            "timeframes": frames}


def test_all_six_fresh_frames_pass():
    now = 1_800_000_000
    frames = {tf: {"last_closed_epoch": now - 30} for tf in ("D1", "H4", "H1", "M15", "M5", "M1")}
    result = audit_mtf_synchronization(snap(now, frames), now_epoch=now)
    assert result["status"] == "PASS"
    assert result["decision_override"] is None


def test_missing_h4_blocks():
    now = 1_800_000_000
    frames = {tf: {"last_closed_epoch": now - 30} for tf in ("D1", "H1", "M15", "M5", "M1")}
    result = audit_mtf_synchronization(snap(now, frames), now_epoch=now)
    assert result["status"] == "BLOCKED"
    assert "H4:MISSING_QUANT_FRAME" in result["blockers"]
    assert result["decision_override"] == "NO_TRADE"


def test_stale_frame_blocks():
    now = 1_800_000_000
    frames = {tf: {"last_closed_epoch": now - 30} for tf in ("D1", "H4", "H1", "M15", "M5", "M1")}
    frames["M1"]["last_closed_epoch"] = now - 181
    result = audit_mtf_synchronization(snap(now, frames), now_epoch=now)
    assert result["frames"]["M1"]["status"] == "STALE"
    assert result["status"] == "BLOCKED"


def test_no_common_snapshot_timestamp_is_unverifiable():
    now = 1_800_000_000
    frames = {tf: {"last_closed_epoch": now - 30} for tf in ("D1", "H4", "H1", "M15", "M5", "M1")}
    result = audit_mtf_synchronization({"timeframes": frames}, now_epoch=now)
    assert result["status"] == "BLOCKED"
    assert all(x["status"] == "UNVERIFIABLE_TIMESTAMP" for x in result["frames"].values())


def test_uploaded_subset_can_be_checked_without_inventing_missing_images():
    now = 1_800_000_000
    frames = {"M5": {"last_closed_epoch": now - 30}, "M1": {"last_closed_epoch": now - 20}}
    result = audit_mtf_synchronization(snap(now, frames), expected_timeframes=("M5", "M1"), now_epoch=now)
    assert result["status"] == "PASS"

from pathlib import Path


def test_launcher_installs_media_requirements_for_existing_users():
    root = Path(__file__).resolve().parents[3]
    launcher = root / "tech_connector" / "Start_The_Entire_World_Tech_Connector.bat"
    text = launcher.read_text(encoding="utf-8", errors="replace")

    assert "Checking media analysis dependencies" in text
    assert "pip show imageio" in text
    assert "pip show imageio-ffmpeg" in text
    assert "requirements\\media.txt" in text

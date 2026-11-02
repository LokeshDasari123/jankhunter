import base64
import re
from io import BytesIO

from PIL import Image

from jankhunter.models import Defect, Frame, Track, TrackPoint
from jankhunter.report import _frame_strip


def test_evidence_strip_embeds_track_box_overlay(tmp_path):
    path = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "black").save(path)
    frame = Frame(t=1.0, path=path)
    track = Track(
        id="sam-1",
        label="sprite",
        points=[TrackPoint(
            t=1.0,
            bbox=(10, 10, 30, 20),
            centroid=(25, 20),
            area=600,
            visible=True,
        )],
    )
    defect = Defect(
        type="jitter",
        track_id="sam-1",
        label="sprite",
        t_start=1.0,
        t_end=1.1,
        severity=0.5,
        metric=2.0,
        evidence=[0],
    )

    strip = _frame_strip([frame], [defect], "Before", [track])
    match = re.search(r'src="data:image/jpeg;base64,([^"]+)"', strip)
    assert match
    with Image.open(BytesIO(base64.b64decode(match.group(1)))) as rendered:
        red, green, blue = rendered.convert("RGB").getpixel((10, 10))

    assert green > 150 and red < 100 and blue > 100

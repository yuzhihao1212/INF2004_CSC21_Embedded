"""Check RP2040 program words/wrap bounds against installed pioasm; no download."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = Path(__file__).resolve().parents[3] / "app_program/subsystem3/dht22.pio"
def program(text):
    words = re.search(r"program_instructions\[\] = \{(.*?)\};", text, re.S).group(1)
    return (re.findall(r"0x[0-9a-fA-F]+", words),
            re.findall(r"#define mosaic_dht22_wrap(?:_target)? (\d+)", text))

with tempfile.TemporaryDirectory(prefix="mosaic-s3-pio-") as tmp:
    generated = Path(tmp) / "dht22.pio.h"
    subprocess.run([sys.argv[1], "-o", "c-sdk", str(source), str(generated)], check=True)
    actual = program(generated.read_text())
    expected = program(source.with_suffix(".pio.h").read_text())
    assert actual == expected, "PIO instructions changed: regenerate checked-in header"
    assert len(actual[0]) == 20 and actual[1] == ["9", "19"]
print("PASS S3-U10: pioasm reproduces 20 instructions and wrap 9..19")

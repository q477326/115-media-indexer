import pytest

from app.services.identifier import extract_identifier, normalize_identifier


@pytest.mark.parametrize(("filename", "expected"), [
    ("SSIS-001.mp4", "SSIS-001"),
    ("ipzz_123 sample.mkv", "IPZZ-123"),
    ("MIDV 888.mp4", "MIDV-888"),
    ("CAWD456.mp4", "CAWD-456"),
    ("348NTR-102.strm", "348NTR-102"),
    ("390JAC-052.strm", "390JAC-052"),
    ("hhd800.com@ABW-249.mp4", "ABW-249"),
    ("4k2.me@cawd-985.mp4", "CAWD-985"),
    ("489155.com@CAWD-949.mp4", "CAWD-949"),
    ("www.98T.la@ABW-121@BVPP1XdfBVPP4X(STD)_apo8_iris2_watermusk.mp4", "ABW-121"),
    ("98T@PRED-107.mp4", "PRED-107"),
    ("ordinary-video.mp4", None),
    ("hhd800.com.mp4", None),
    ("FC2-1650265.strm", None),
    ("011219-004.strm", None),
    ("n0724.strm", None),
    ("BD-M17.strm", None),
    ("DPFanatics.16.10.09.strm", None),
    ("PureTaboo.24.08.27.strm", None),
])
def test_extract_identifier(filename, expected):
    assert extract_identifier(filename) == expected


@pytest.mark.parametrize(("value", "expected"), [
    ("ssis001", "SSIS-001"),
    ("ipzz_123", "IPZZ-123"),
    (" MIDV-888 ", "MIDV-888"),
    ("348ntr_102", "348NTR-102"),
    ("invalid", None),
])
def test_normalize_identifier(value, expected):
    assert normalize_identifier(value) == expected

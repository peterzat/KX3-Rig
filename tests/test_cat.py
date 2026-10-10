import pytest

from kx3rig import cat
from kx3rig.cat import DataSubmode, Mode

# Built from the Programmer's Reference field table (p.14): 14.074 MHz, DATA, RX, VFO A.
IF_DATA_RX = "IF00014074000     +000000 0006000001 ;"
IF_LSB_TX_RIT = "IF00007185000     -012010 0011001001 ;"


def test_if_reply_is_38_bytes():
    assert len(IF_DATA_RX) == 38


def test_parse_if_basic():
    info = cat.parse_if(IF_DATA_RX)
    assert info.frequency == 14_074_000
    assert info.mode is Mode.DATA
    assert not info.transmitting
    assert not info.split and not info.rit_on and not info.xit_on


def test_parse_if_tx_rit_split():
    info = cat.parse_if(IF_LSB_TX_RIT)
    assert info.frequency == 7_185_000
    assert info.rit_offset == -120
    assert info.rit_on and not info.xit_on
    assert info.transmitting
    assert info.mode is Mode.LSB
    assert info.split


@pytest.mark.parametrize("bad", ["IF;", IF_DATA_RX[:-1], "IF0001407400X     +000000 0006000001 ;", "?;"])
def test_parse_if_rejects_malformed(bad):
    assert cat.parse_if(bad) is None


def test_frequency_round_trip():
    assert cat.set_frequency(14_074_000) == "FA00014074000;"
    assert cat.parse_fa("FA00014074000;") == 14_074_000
    assert cat.parse_fa("FA0001407400;") is None
    with pytest.raises(ValueError):
        cat.set_frequency(0)


def test_modes():
    assert cat.set_mode(Mode.USB) == "MD2;"
    assert cat.parse_md("MD6;") is Mode.DATA
    assert cat.parse_md("MD9;") is Mode.DATA_REV
    assert cat.parse_md("MD8;") is None
    assert Mode.USB.is_voice and Mode.DATA.is_data and Mode.CW.is_cw
    assert not Mode.DATA.is_voice


def test_data_submode():
    assert cat.set_data_submode(DataSubmode.DATA_A) == "DT0;"
    assert cat.parse_dt("DT3;") is DataSubmode.PSK_D
    assert cat.parse_dt("DT7;") is None


def test_bandwidth_in_10hz_units():
    assert cat.set_bandwidth(2800) == "BW0280;"
    assert cat.parse_bw("BW0270;") == 2700


def test_power_formats():
    assert cat.set_power(5) == "PC005;"
    assert cat.set_power(99) == "PC015;"
    assert cat.parse_pc("PC005;") == 5.0
    assert cat.parse_pc("PC0500;") == 5.0     # K22 low range, tenths of a watt
    assert cat.parse_pc("PC0101;") == 10.0    # K22 high range, watts
    assert cat.parse_po("PO050;") == 5.0
    assert cat.parse_sw("SW015;") == 1.5


def test_meta_and_identity():
    assert cat.parse_id("ID017;") == 17
    assert cat.parse_k2("K22;") == 2
    assert cat.parse_ai("AI0;") == 0
    assert cat.parse_tq("TQ1;") is True
    assert cat.parse_rv("RVM02.93;") == pytest.approx(2.93)


def test_om_identifies_kx3_and_options():
    opts = cat.parse_om("OM A-F-------02;")
    assert opts.is_kx3 and opts.atu and opts.roofing and not opts.pa100
    assert not cat.parse_om("OM ----------01;").is_kx3
    assert cat.parse_om("OM;") is None


def test_smeter():
    assert cat.parse_sm("SM0006;") == 6
    assert cat.smeter_db(6) == 0
    assert cat.smeter_db(9) == 20
    assert cat.smeter_db(15) == 60
    assert cat.smeter_db(99) == 60
    assert cat.smeter_db(9, k31=True) == 0
    assert cat.smeter_label(0) == "S9"
    assert cat.smeter_label(20) == "S9+20"
    assert cat.smeter_label(-24) == "S5"


def test_frame_splitter_handles_partial_and_garbage():
    fs = cat.FrameSplitter()
    assert fs.feed(b"FA000140") == []
    assert fs.feed(b"74000;SM00") == ["FA00014074000;"]
    assert fs.feed(b"06;\xff?;") == ["SM0006;", "\xff?;"]
    assert cat.frame_kind("?;") == "?"
    assert cat.frame_kind("SM0006;") == "SM"
    assert cat.frame_kind("K22;") == "K2"
    assert cat.frame_kind("RVM02.93;") == "RV"


@pytest.mark.parametrize("cmd", [
    "FA;", "FA00014074000;", "MD2;", "DT0;", "BW0280;", "PC005;", "IF;", "SM;", "TQ;",
    "ID;", "OM;", "RVM;", "K2;", "K20;", "AI0;", "RX;", "SW;", "PO;", "BN05;", "BN10;",
])
def test_allow_list_accepts_driver_commands(cmd):
    assert cat.is_allowed(cmd)


@pytest.mark.parametrize("cmd", [
    "TX;",           # CAT keying (PTT is the RTS line, which has a watchdog)
    "SWH16;",        # TUNE (transmits a carrier)
    "SWT44;",        # ATU TUNE (transmits)
    "KYCQ CQ;",      # keyed text
    "PS0;",          # power off; cannot be undone over CAT
    "BR0;",          # baud change
    "MN057;",        # menu access
    "MP001;",
    "UP;", "DN;",    # edit an open menu
    "MD8;",          # not a mode
    "FA1407400;",    # malformed frequency
    "FA00014074000;MD2;",  # one command at a time
    "BN16;",         # transverter band
])
def test_allow_list_rejects_dangerous_commands(cmd):
    assert not cat.is_allowed(cmd)


def test_band_number():
    assert cat.set_band(5) == "BN05;"
    assert cat.parse_bn("BN10;") == 10
    with pytest.raises(ValueError):
        cat.set_band(16)

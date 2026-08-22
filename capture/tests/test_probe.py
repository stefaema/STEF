"""What a camera's own description turns into, read from the reference's example."""

from __future__ import annotations

from capture import probe

# Chapter 2.5 of the Camera Control API reference, verbatim but for the address.
DESCRIPTION = b"""<?xml version="1.0"?>
<root xmlns="urn:schemas-upnp-org:device-1-0">
<specVersion><major>1</major><minor>0</minor></specVersion>
<URLBase>http://192.168.1.2:49152/upnp/</URLBase>
<device>
<deviceType>urn:schemas-canon-com:device:ICPO-CameraControlAPIService:1</deviceType>
<friendlyName>Degital Camera</friendlyName>
<manufacturer>Canon</manufacturer>
<manufacturerURL>http://www.canon.com/</manufacturerURL>
<modelDescription>Canon Digital Camera</modelDescription>
<modelName>EOS R6</modelName>
<serialNumber>012345678901</serialNumber>
<UDN>uuid:00000000-0000-0607-0001-0A0B0C0D0E0F</UDN>
<serviceList>
<service>
<serviceType>urn:schemas-canon-com:service:ICPO-CameraControlAPIService:1</serviceType>
<serviceId>urn:schemas-canon-com:serviceId:ICPO-CameraControlAPIService-1</serviceId>
<SCPDURL>CameraSvcDesc.xml</SCPDURL>
<controlURL>control/CanonCamera/</controlURL>
<eventSubURL></eventSubURL>
<ns:X_onService xmlns:ns="urn:schemas-canon-com:schema-upnp">%s</ns:X_onService>
<ns:X_accessURL xmlns:ns="urn:schemas-canon-com:schema-upnp">%s</ns:X_accessURL>
<ns:X_deviceNickname xmlns:ns="urn:schemas-canon-com:schema-upnp">Camera</ns:X_deviceNickname>
</service>
</serviceList>
<presentationURL>/</presentationURL>
</device>
</root>
"""

WHERE = "http://192.168.1.2:49152/upnp/CameraDevDesc.xml"


def described(
    on_service: bytes = b"0", access: bytes = b"http://192.168.1.2:8080/ccapi"
) -> probe.Found:
    """Return what one description reads as, written the way a camera writes it."""
    found = probe._read(DESCRIPTION % (on_service, access), WHERE)
    assert found is not None
    return found


# ── What the description says ────────────────────────────────────────────────


def test_the_camera_is_reached_where_it_says_and_not_where_it_was_fetched():
    found = described()

    assert found.host == "192.168.1.2"
    assert found.port == 8080


def test_a_description_names_the_body_and_its_serial():
    found = described()

    assert found.model == "EOS R6"
    assert found.serial == "012345678901"


def test_a_camera_nobody_holds_is_free_rather_than_switched_off():
    assert not described(on_service=b"0").held
    assert described(on_service=b"1").held


def test_a_held_camera_says_so_where_an_operator_reads_it():
    assert "in use" in described(on_service=b"1").label
    assert "in use" not in described(on_service=b"0").label


def test_the_usual_port_is_left_out_of_a_label_and_an_unusual_one_is_not():
    assert described().address == "192.168.1.2"
    unusual = described(access=b"http://192.168.1.2:8081/ccapi")

    assert unusual.address == "192.168.1.2:8081"


def test_a_camera_serving_over_tls_is_read_as_such():
    assert described(access=b"https://192.168.1.2:443/ccapi").ssl
    assert not described().ssl


# ── What a description leaves out ────────────────────────────────────────────


def test_a_description_without_an_access_url_falls_back_to_the_default_port():
    found = described(access=b"")

    assert found.host == "192.168.1.2"
    assert found.port == 8080


def test_something_that_is_not_a_description_is_no_camera():
    assert probe._read(b"<html>not me</html>", WHERE) is None
    assert probe._read(b"not xml at all", WHERE) is None


# ── What silence turned out to be ────────────────────────────────────────────


def test_an_unasked_search_is_not_reported_as_an_absent_camera():
    swept = probe.Sweep(found=(), carried=(), refused=("wlan0",), answered=0)

    assert not swept
    assert "no interface carried" in swept.sentence


def test_a_search_that_went_out_and_heard_nothing_says_where_it_went():
    swept = probe.Sweep(found=(), carried=("wlan0",), refused=(), answered=0)

    assert "wlan0" in swept.sentence
    assert "multicast" in swept.sentence


def test_a_device_that_answers_and_will_not_describe_itself_is_its_own_case():
    swept = probe.Sweep(found=(), carried=("wlan0",), refused=(), answered=2)

    assert "none of them would describe itself" in swept.sentence

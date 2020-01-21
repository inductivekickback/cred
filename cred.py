"""
Build and download a disposable hex file for programming TLS credentials.

The firmware component consists of a simple executable that looks for a list of credentials
at a known location in flash and then programs them into the modem side of the nRF91 SoC. The
block of credential information starts at the first flash page boundary following the firmware
stub and consists of the following:
[MAGIC_NUMBER (4 bytes)][FW_RESULT_CODE (4 bytes)][CRED_COUNT (1 byte)]
    [SEC_TAG (4 bytes)][CRED_TYPE (1 byte)][CRED_LEN (2 bytes)][CRED_DATA (N bytes)]
    ...
    [SEC_TAG (4 bytes)][CRED_TYPE (1 byte)][CRED_LEN (2 bytes)][CRED_DATA (N bytes)]

NOTE: Does not parse existing credentials when reading from an in_file so there is no
      check to prevent adding duplicate credentials.
"""
import sys
import os
import argparse
import struct
import tempfile
import time

from intelhex import IntelHex
from pynrfjprog import HighLevel


DEFAULT_CRED_WRITE_TIME_S = 7

HEX_PATH = os.path.sep.join(("build", "zephyr", "merged.hex"))
TMP_FILE_NAME = "cred_hex.hex"
MAGIC_NUMBER_BYTES = struct.pack('I', 0xca5cad1a)
BLANK_FW_RESULT_CODE = 0xFFFFFFFF

CRED_PAGE_ADDR = 0x2B000
FW_RESULT_CODE_ADDR = (CRED_PAGE_ADDR + 4)
CRED_COUNT_ADDR = (FW_RESULT_CODE_ADDR + 4)
FIRST_CRED_ADDR = (CRED_COUNT_ADDR + 1)

# For more information: https://tools.ietf.org/html/rfc4279
MAX_PSK_IDENT_LEN_BYTES = 128
MAX_PSK_LEN_BYTES = 64
MAX_KEY_MATERIAL_LEN_BYTES = 4077 # Appears to be the case as of modem firmware 1.1.0

CRED_TYPE_ROOT_CA = 0
CRED_TYPE_CLIENT_CERT = 1
CRED_TYPE_CLIENT_PRIVATE_KEY = 2
CRED_TYPE_PSK = 3
CRED_TYPE_PSK_IDENTITY = 4


def _write_firmware(nrfjprog_probe, fw_hex):
    """Program and verify a hex file."""
    nrfjprog_probe.program(fw_hex)
    nrfjprog_probe.verify(fw_hex)
    nrfjprog_probe.reset()


def _close_and_exit(nrfjprog_api, status):
    """Close the nrfjprog connection if necessary and exit."""
    if nrfjprog_api:
        nrfjprog_api.close()
    sys.exit(status)


def _connect_to_jlink(args):
    """Connect to the debug probe."""
    api = HighLevel.API()
    api.open()
    connected_serials = api.get_connected_probes()
    if args.serial_number:
        if args.serial_number in connected_serials:
            connected_serials = [args.serial_number]
        else:
            print("error: serial_number not found ({})".format(args.serial_number))
            _close_and_exit(api, -1)
    if not connected_serials:
        print("error: no debug probes found")
        _close_and_exit(api, -1)
    if len(connected_serials) > 1:
        print("error: multiple debug probes found, use --serial_number")
        _close_and_exit(api, -1)
    probe = HighLevel.DebugProbe(api, connected_serials[0], HighLevel.CoProcessor.CP_APPLICATION)
    return (api, probe)


def _read_key_material_from_file(path):
    """Read a certificate file and return it as a string. Line endings should be <LF>."""
    with open(path, 'r') as in_file:
        content = [line.strip() for line in in_file.readlines()]
        content = '\n'.join(content)
        if len(content) > MAX_KEY_MATERIAL_LEN_BYTES:
            raise Exception("Key material is too long ({} bytes)".format(len(content)))
        return content


def _append_cred(intel_hex, sec_tag, cred_type, content):
    """Append the specified credential to the hex file."""
    addr = (intel_hex.maxaddr() + 1)
    # [uint32_t nrf_sec_tag_t]
    intel_hex.puts(addr, struct.pack('I', sec_tag))
    addr = addr + 4
    # [uint8_t nrf_key_mgnt_cred_type_t]
    intel_hex[addr] = cred_type
    addr = addr + 1
    # [uin16_t len]
    intel_hex.puts(addr, struct.pack('H', len(content)))
    addr = addr + 2
    # [uint8_t *credential]
    intel_hex.puts(addr, content)


def _append_creds(intel_hex, args):
    """Iterate through the provided credential arguments and add them"""
    count = struct.unpack('B', intel_hex.gets(CRED_COUNT_ADDR, 1))[0]
    if args.psk:
        _append_cred(intel_hex, args.sec_tag, CRED_TYPE_PSK, args.psk)
        count = count + 1
    if args.psk_ident:
        _append_cred(intel_hex, args.sec_tag, CRED_TYPE_PSK_IDENTITY, args.psk_ident)
        count = count + 1
    if args.CA_cert_path:
        _append_cred(intel_hex,
                     args.sec_tag,
                     CRED_TYPE_ROOT_CA,
                     _read_key_material_from_file(args.CA_cert_path))
        count = count + 1
    if args.client_cert_path:
        _append_cred(intel_hex,
                     args.sec_tag,
                     CRED_TYPE_CLIENT_CERT,
                     _read_key_material_from_file(args.client_cert_path))
        count = count + 1
    if args.client_private_key_path:
        _append_cred(intel_hex,
                     args.sec_tag,
                     CRED_TYPE_CLIENT_PRIVATE_KEY,
                     _read_key_material_from_file(args.client_private_key_path))
        count = count + 1
    intel_hex.puts(CRED_COUNT_ADDR, struct.pack('B', count))


def _add_and_parse_args():
    """Build the argparse object and parse the args."""
    parser = argparse.ArgumentParser(prog='cred',
                                     description=('A command line interface for ' +
                                                  'managing nRF91 credentials via SWD.'),
                                     epilog=('WARNING: nrf_cloud relies on credentials '+
                                             'with sec_tag 16842753.'))
    parser.add_argument("-i", "--in_file", type=str, metavar="PATH_TO_IN_FILE",
                        help="read existing hex file instead of generating a new one")
    parser.add_argument("-o", "--out_file", type=str, metavar="PATH_TO_OUT_FILE",
                        help="write output from read operation to file instead of programming it")
    parser.add_argument("-d", "--fw_delay", type=int, metavar="FW_EXECUTE_DELAY",
                        help="delay in seconds to allow firmware on nRF91 to execute")
    parser.add_argument("-s", "--serial_number", type=int, metavar="JLINK_SERIAL_NUMBER",
                        help="serial number of J-Link")
    parser.add_argument("--sec_tag", type=int,
                        help="sec_tag to use for credential")
    parser.add_argument("--psk", type=str, metavar="PRESHARED_KEY",
                        help="add a preshared key (PSK) as a string")
    parser.add_argument("--psk_ident", type=str, metavar="PRESHARED_KEY_IDENTITY",
                        help="add a preshared key (PSK) identity as a string")
    parser.add_argument("--CA_cert_path", type=str, metavar="CA_CERT_PATH",
                        help="path to a root Certificate Authority certificate")
    parser.add_argument("--client_cert_path", type=str, metavar="CLIENT_CERT_PATH",
                        help="path to a client certificate")
    parser.add_argument("--client_private_key_path", type=str, metavar="CLIENT_PRIVATE_KEY_PATH",
                        help="path to a client private key")
    args = parser.parse_args()
    if args.psk:
        if args.psk.upper().startswith("0X"):
            args.psk = args.psk[2:]
    if args.sec_tag is None:
        parser.print_usage()
        print("error: sec_tag is required")
        sys.exit(-1)
    if not (args.psk or args.psk_ident or args.CA_cert_path or args.client_cert_path or
            args.client_private_key_path or args.client_public_key_path):
        parser.print_usage()
        print("error: at least one credential is required")
        sys.exit(-1)
    if args.out_file:
        if args.serial_number or args.fw_delay:
            parser.print_usage()
            print("error: out_file is mutually exclusive with delay or serial_number")
            sys.exit(-1)
    else:
        if not args.fw_delay:
            args.fw_delay = DEFAULT_CRED_WRITE_TIME_S
    return args


def _main():
    """Append credentials to a prebuilt hex file, download it via a J-Link debug probe,
    allow the hex file to run, verify the result code, and then erase the hex file.
    """
    args = _add_and_parse_args()
    nrfjprog_api = None
    nrfjprog_probe = None
    try:
        hex_path = HEX_PATH
        if args.in_file:
            hex_path = args.in_file
        intel_hex = IntelHex(hex_path)
        if intel_hex.maxaddr() >= CRED_PAGE_ADDR:
            if hex_path == HEX_PATH:
                print("error: Prebuilt hex file is too large.")
                _close_and_exit(nrfjprog_api, -3)
            elif (intel_hex.maxaddr() < FW_RESULT_CODE_ADDR or
                  intel_hex.gets(CRED_PAGE_ADDR, 4) != MAGIC_NUMBER_BYTES):
                print("error: Magic number not found in hex file.")
                _close_and_exit(nrfjprog_api, -2)
        else:
            intel_hex.puts(CRED_PAGE_ADDR, MAGIC_NUMBER_BYTES)
            intel_hex.puts(CRED_COUNT_ADDR, struct.pack('B', 0x00))
        if not args.out_file:
            nrfjprog_api, nrfjprog_probe = _connect_to_jlink(args)
        _append_creds(intel_hex, args)
        if args.out_file:
            intel_hex.tofile(args.out_file, "hex")
        else:
            # Create a temporary file to pass to pynrfjprog and then delete it when finished.
            tmp_file = os.path.sep.join((tempfile.mkdtemp(), TMP_FILE_NAME))
            intel_hex.tofile(tmp_file, "hex")
            _write_firmware(nrfjprog_probe, tmp_file)
            time.sleep(args.fw_delay)
            result_code = nrfjprog_probe.read(FW_RESULT_CODE_ADDR)
            if result_code:
                print("error: Firmware result is 0x{:X}".format(result_code))
                _close_and_exit(nrfjprog_api, -4)
            nrfjprog_probe.erase(HighLevel.EraseAction.ERASE_ALL)
            os.remove(tmp_file)
            os.removedirs(os.path.dirname(tmp_file))

        _close_and_exit(nrfjprog_api, 0)
    except Exception as ex:
        print("error: " + str(ex))
        _close_and_exit(nrfjprog_api, -2)


if __name__ == "__main__":
    _main()

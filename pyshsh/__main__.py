import argparse
import asyncio

import pytss
import plistlib
from .baseband_data import gen_baseband_data
from random import getrandbits
from importlib.metadata import version

__version__ = version(__package__)


async def _main() -> None:
    parser = argparse.ArgumentParser(
        usage='pyshsh [options]',
    )
    parser.add_argument(
        '-d',
        '--device',
        help='Device identifier (e.g. iPod7,1)',
        required=True,
    )
    parser.add_argument(
        '-e',
        '--ecid',
        help='Device ECID (e.g. abcdef01234567)',
        required=True,
    )
    parser.add_argument(
        '-o',
        '--output',
        help='File to output SHSH blob to',
        type=argparse.FileType('wb'),
        required=True,
    )

    build = parser.add_mutually_exclusive_group(required=True)
    build.add_argument('-v', '--version', help='Firmware version')
    build.add_argument('-b', '--buildid', help='Firmware buildid')
    build.add_argument(
        '-m',
        '--buildmanifest',
        help='Firmware build manifest',
        type=argparse.FileType('rb'),
        dest='manifest',
    )

    args = parser.parse_args()

    print(f'PySHSH {__version__}')

    print('Fetching device information...')
    device = await pytss.fetch_device(args.device)
    device.ecid = args.ecid
    device.ap_nonce = bytes(
        getrandbits(8) for _ in range(32 if 0x8010 <= device.chip_id < 0x8900 else 20)
    )
    print('Fetching firmware information...')
    if args.manifest:
        print('[NOTE] Using provided build manifest')
        manifest = pytss.BuildManifest(args.manifest.read())
        firmware = None
    else:
        manifest = None
        firmware = await device.fetch_firmware(
            version=args.version, buildid=args.buildid
        )

    try:
        baseband = gen_baseband_data(device)

    except ValueError:
        print('[NOTE] No baseband data available, not saving baseband ticket')
        baseband = None

    shsh_blob = dict()

    for restore_type in pytss.RestoreType:
        print(f'Creating {restore_type.name.lower()} install TSS request...')
        tss = await pytss.TSS.new(
            device,
            firmware=firmware,
            build_manifest=manifest,
            restore_type=restore_type,
        )

        if baseband is not None:
            tss.add_image(pytss.FirmwareImage.Baseband, baseband)

        print(f'Sending {restore_type.name.lower()} install TSS request...')
        response = await tss.send()

        if restore_type == pytss.RestoreType.ERASE:
            shsh_blob.update(response)
        else:
            shsh_blob['updateInstall'] = dict()
            shsh_blob['updateInstall'].update(response)

    print('Creating noNonce TSS request...')
    device.ap_nonce = None

    tss = await pytss.TSS.new(
        device,
        firmware=firmware,
        build_manifest=manifest,
        restore_type=pytss.RestoreType.ERASE,
    )

    if baseband is not None:
        tss.add_image(pytss.FirmwareImage.Baseband, baseband)

    print(f'Sending noNonce TSS request...')

    try:
        response = await tss.send()

        shsh_blob['noNonce'] = dict()
        shsh_blob['noNonce'].update(response)
    except pytss.APIError:
        print('[NOTE] Failed to save noNonce blobs, skipping...')

    plistlib.dump(shsh_blob, args.output)
    print('Outputted SHSH blob.')


def main() -> None:
    asyncio.run(_main())


if __name__ == '__main__':
    main()

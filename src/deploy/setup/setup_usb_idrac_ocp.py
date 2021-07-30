#!/usr/bin/env python3

# Copyright (c) 2015-2021 Dell Inc. or its subsidiaries.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
import time
import subprocess
import logging
import traceback
import argparse
import os
from ocp_deployer.settings.ocp_config import OCP_Settings as Settings
from ocp_deployer.csah import CSah

logger = logging.getLogger("osp_deployer")


def setup():
    try:
        hdlr = logging.FileHandler('setup_usb_idrac_ocp.log')
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        hdlr.setFormatter(formatter)
        logger.addHandler(hdlr)
        logger.setLevel(logging.DEBUG)
        out = logging.StreamHandler(sys.stdout)
        out.setLevel(logging.INFO)
        logger.addHandler(out)
        logger.info("* Creating the SAH node usb image.")
        parser = argparse.ArgumentParser(description='CHANGEME 10.x usb ' +
                                                     ' image  prep.')
        parser.add_argument('-s', '--settings',
                            help='ini settings file, e.g settings/acme.ini',
                            required=True)
        parser.add_argument('-usb_key', '--usb_key',
                            help='Use a physical USB key - device to use ' +
                                 ' eg : -usb_key /dev/sdb',
                            required=False)
        parser.add_argument('-idrac_vmedia_img', '--idrac_vmedia_img',
                            help='Use an idrac virtual media image',
                            action='store_true', required=False)
        parser.add_argument('-idrac_bundle_iso', '--idrac_bundle_iso',
                            help='Bundles generated kickstart into provided RHEL 8.x ISO',
                            action='store_true', required=False)

        args, ignore = parser.parse_known_args()

        if args.usb_key is None and args.idrac_vmedia_img is False and not args.idrac_bundle_iso:
            raise AssertionError("You need to spefify the type of" +
                                 " installation to perform \n" +
                                 "-usb_key devideID if using a " +
                                 "physical key\n" +
                                 "-idrac_vmedia_img if using " +
                                 "an idrac virtual media image\n" + 
                                 "-idrac_bundle_iso if using " + 
                                 "a RHEL 8.x ISO with an embedded kickstart\n")

        logger.debug("loading settings files " + args.settings)
        settings = Settings(args.settings)
        logger.info("Settings .ini: " + settings.settings_file)
        logger.info("Settings .yaml " + settings.nodes_yaml)

        
        sah = CSah()
        sah.update_kickstart_usb()

        # Create the usb Media & update path references
        target_ini = settings.settings_file.replace('/root', "/mnt/usb")
        if args.idrac_vmedia_img is True:
            cmds = ['cd ~;rm -f ocp_ks.img',
                    'cd ~;dd if=/dev/zero of=ocp_ks.img bs=1M count=10000',
                    'cd ~;mkfs ext3 -F ocp_ks.img',
                    'mkdir -p /mnt/usb',
                    'cd ~;mount -o loop ocp_ks.img /mnt/usb',
                    'cd ~;cp -R ~/ansible /mnt/usb',
                    'cd ~;cp ocp-csah.ks /mnt/usb',
                    'cd ~;mkdir -p /mnt/usb/ansible/pilot',
                    'cd ~;cp ~/ansible/JetPack/src/pilot/dell_systems.json /mnt/usb/ansible/pilot/',
                    'sync; umount /mnt/usb']
        elif args.idrac_bundle_iso:
            work_dir = '/home' # depending on storage constrainst, maybe a different mount path would be good
            label_cmd = f'export LABEL=$(blkid {settings.rhel_iso} | cut -d " " -f 4 | cut -d "=" -f 2 | tr -d \'"\') '
            sed_cmd_isolinux = 'sed -i "0,/append initrd=initrd.img inst.stage2=hd:LABEL=$LABEL/s//append initrd=initrd.img inst.stage2=hd:LABEL=$LABEL inst.ks=cdrom:\/ks.cfg/" /tmp/rhel8/isolinux/isolinux.cfg'
            sed_cmd_grub = 'sed -i "s|linuxefi /images/pxeboot/vmlinuz inst.stage2=hd:LABEL=$LABEL quiet|linuxefi /images/pxeboot/vmlinuz inst.stage2=hd:LABEL=$LABEL inst.ks=cdrom:/ks.cfg quiet|" /tmp/rhel8/EFI/BOOT/grub.cfg'
            cmds = [f'cd ~; rm -f {work_dir}/ocp_csah_dvd.iso',
                    'cd ~; umount /mnt',
                    f'rm -rf {work_dir}/rhel8/', # clean up any existing iso files
                    f'cd ~; mount -o loop {settings.rhel_iso} /mnt',
                    'shopt -s dotglob',
                    f'mkdir {work_dir}/rhel8', # /tmp/rhel8 needs enough space for the whole iso, ~8gb
                    f'cp -avRf /mnt/* {work_dir}/rhel8',
                    f'cd ~; cp ocp-csah.ks {work_dir}/rhel8/ks.cfg',
                    f'cd ~; {label_cmd}; {sed_cmd_isolinux}',
                    f'cd ~; {label_cmd}; {sed_cmd_grub}',
                    f'cd {work_dir}/rhel8; {label_cmd}; mkisofs -o {work_dir}/ocp_csah_dvd.iso -b isolinux/isolinux.bin -J -R -l -c isolinux/boot.cat -no-emul-boot -boot-load-size 4 -boot-info-table -eltorito-alt-boot -e images/efiboot.img -no-emul-boot -graft-points -V "$LABEL" .',
                    f'isohybrid --uefi {work_dir}/ocp_csah_dvd.iso'
            ]
        else:
            cmds = ['mkfs.ext3 -F ' + args.usb_key,
                    'mkdir -p /mnt/usb',
                    'cd ~;mount -o loop ' + args.usb_key +
                    ' /mnt/usb',
                    'cd ~;cp -R ~/ansible /mnt/usb',
                    'cd ~;cp ocp-sah.ks /mnt/usb',
                    'cd ~;mkdir -p /mnt/usb/ansible/pilot',
                    'cd ~;cp ~/ansible/JetPack/src/pilot/dell_systems.json /mnt/usb/ansible/pilot/',
                    'sync; umount /mnt/usb']

        for cmd in cmds:
            logger.debug("running " + cmd)
            logger.debug(subprocess.check_output(cmd,
                                                 stderr=subprocess.STDOUT,
                                                 shell=True))

        if args.idrac_vmedia_img:
            logger.info("All done - attach ~/ocp_ks.img to the sah node" +
                        " & continue with the deployment ...")
        else:
            logger.info("All done - plug the usb into the sah node" +
                        " & continue with the deployment ...")

    except:
        logger.error(traceback.format_exc())
        e = sys.exc_info()[0]
        logger.error(e)
        print(e)
        print(traceback.format_exc())


if __name__ == "__main__":
    setup()

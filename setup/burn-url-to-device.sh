set -u
set -e

DOWNLOAD_URL=$1   #https://github.com/armbian/community/releases/download/202249/Armbian_23.02.0-trunk_Pine64_kinetic_edge_6.0.10_minimal.img.xz
DEVICE=$2  #/dev/disk2

diskutil unmountDisk $DEVICE
curl -L -f "$DOWNLOAD_URL" | xz -d | dd of=$DEVICE

set -u
set -e

OLD_HOSTNAME=$1   #quartz64
NEW_HOSTNAME=$2   #homelab-nas
DISK_MNT_DIR=$3   #/mnt/disk1
DISK_DEVICE=$4    #/dev/sdb
NCDATA_DIR=$3

# Set hostname
echo "Changin hostname $OLD_HOSTNAME > $NEW_HOSTNAME"
sudo hostnamectl set-hostname $NEW_HOSTNAME
sudo perl -i -p -e "s/$OLD_HOSTNAME/$NEW_HOSTNAME/g" /etc/hosts

sudo mkdir $DISK_MNT_DIR
sudo mount $DISK_DEVICE $DISK_MNT_DIR
# Add to /etc/fstab
# UUID=$DISK_UUID /mnt/disk1 ext4 defaults 0 1
# sudo mount -a

echo "Installing Docker"
curl -fsSL get.docker.com | sudo sh

echo "Installing Nextcloud AIO"
sudo docker run \
--sig-proxy=false \
--name nextcloud-aio-mastercontainer \
--restart always \
--publish 80:80 \
--publish 8080:8080 \
--publish 8443:8443 \
--volume nextcloud_aio_mastercontainer:/mnt/docker-aio-config \
--volume /var/run/docker.sock:/var/run/docker.sock:ro -e NEXTCLOUD_DATADIR="$DISK_MNT_DIR/ncdata" -e NEXTCLOUD_MOUNT="/mnt/" \
nextcloud/all-in-one:latest-arm64

#!/bin/bash
set -e

DOWNLOAD_URL=$1   #https://dietpi.com/downloads/images/DietPi_SOQuartz-ARMv8-Trixie.img.xz
DEVICE=$2
AUTO_SETUP_NET_HOSTNAME=$3   #https://dietpi.com/downloads/images/DietPi_SOQuartz-ARMv8-Trixie.img.xz
AUTO_SETUP_GLOBAL_PASSWORD=$4
EJECT_DEVICE=$5

# if $device is unset, prompt for the device to write to
if [ -z "${DEVICE:-}" ]; then
  diskutil list
  read -p "Enter the device to write to (e.g. /dev/disk2): " DEVICE
fi

# present the list of images available at https://dietpi.com/downloads/images/ and prompt the user to select one
if [ -z "${DOWNLOAD_URL:-}" ]; then
  echo "Available images:"
  curl -s https://dietpi.com/downloads/images/ | grep -Eo '"([^"]+\.xz)"' | sed 's/"//g' | sed "s/^/https:\/\/dietpi.com\/downloads\/images\//" | nl
  read -p "Enter the number of the image to download: " IMAGE_NUMBER
  DOWNLOAD_URL=$(curl -s https://dietpi.com/downloads/images/ | grep -Eo '"([^"]+\.xz)"' | sed 's/"//g' | sed "s/^/https:\/\/dietpi.com\/downloads\/images\//" | sed -n "${IMAGE_NUMBER}p")
fi

if [ -z "${AUTO_SETUP_NET_HOSTNAME:-}" ]; then
  read -p "Enter the hostname: " AUTO_SETUP_NET_HOSTNAME
fi

if [ -z "${AUTO_SETUP_GLOBAL_PASSWORD:-}" ]; then
  read -p "Enter the password: " AUTO_SETUP_GLOBAL_PASSWORD
fi

diskutil unmountDisk $DEVICE
curl -L -f "$DOWNLOAD_URL" | xz -d | dd of=$DEVICE bs=4M conv=fsync
sleep 1

sed -i -e "/AUTO_SETUP_GLOBAL_PASSWORD=/ s/=.*/=$AUTO_SETUP_GLOBAL_PASSWORD/" /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_LOCALE=/ s/=.*/=en_US\.UTF-8/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_KEYBOARD_LAYOUT=/ s/=.*/=us/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_TIMEZONE=/ s/=.*/=America\/New_York/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e "/AUTO_SETUP_NET_HOSTNAME=/ s/=.*/=$AUTO_SETUP_NET_HOSTNAME/" /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_AUTOMATED=/ s/=.*/=1/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_BROWSER_INDEX=/ s/=.*/=-2/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/SURVEY_OPTED_IN=/ s/=.*/=0/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_NET_WIFI_COUNTRY_CODE=/ s/=.*/=US/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_UNMASK_LOGIND=/ s/=.*/=1/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_BROWSER_INDEX=/ s/=.*/=0/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/AUTO_SETUP_INSTALL_SOFTWARE_ID=/ s/=.*/=58/' /Volumes/DIETPISETUP/dietpi.txt
sed -i -e '/#AUTO_SETUP_INSTALL_SOFTWARE_ID=/ s/#AUTO_SETUP_INSTALL_SOFTWARE_ID=/AUTO_SETUP_INSTALL_SOFTWARE_ID=/' /Volumes/DIETPISETUP/dietpi.txt

if [ -z "${EJECT_DEVICE:-}" ]; then
  read -p "Eject device [y/N]: " EJECT_DEVICE
fi

if [[ "$EJECT_DEVICE" == "y" || "$EJECT_DEVICE" == "Y" ]]; then
  diskutil eject $DEVICE
fi

echo "SUCCESS!"
# If anyone needs it on older macos, you may install anylinuxfs and mount the device

# diskutil list
# read -p "Enter the device partition to mount (e.g. /dev/disk2s1): " DEVICE_PARTITION
# 
# diskutil eject $DEVICE


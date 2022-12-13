set -u
set -e

OLD_HOSTNAME=$1   #EG: pine64
NEW_HOSTNAME=$2   #EG: homelab-primary
K3S_URL=$3        #EG: https://homelab-primary:6443
K3S_TOKEN=$4      #EG: K10e12e687cc3bd959eb05f011addb1d5d05d454ba98015b576e12de62c12fc98dc::server:57f669d7737f97bfdd2db1d912b647b3

# Set hostname
echo "Changin hostname $OLD_HOSTNAME > $NEW_HOSTNAME"
sudo hostnamectl set-hostname $NEW_HOSTNAME
sudo perl -i -p -e "s/$OLD_HOSTNAME/$NEW_HOSTNAME/g" /etc/hosts

# Install docker and start docker
echo "Installing Docker"
sudo apt install docker.io
sudo systemctl start docker
sudo systemctl enable docker

# Install as worker node
echo "Installing K3s for Worker"
sudo curl -sfL https://get.k3s.io | K3S_URL=$K3S_URL K3S_TOKEN=$K3S_TOKEN INSTALL_K3S_VERSION=v1.25.4+k3s1 sh -
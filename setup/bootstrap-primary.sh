set -u
set -e

OLD_HOSTNAME=$1   #https://github.com/armbian/community/releases/download/202249/Armbian_23.02.0-trunk_Pine64_kinetic_edge_6.0.10_minimal.img.xz
NEW_HOSTNAME=$2   #/dev/disk2

# Set hostname
sudo hostnamectl set-hostname $NEW_HOSTNAME
sudo perl -i -p -e "s/$OLD_HOSTNAME/$NEW_HOSTNAME/g" /etc/hosts

# Install docker and start docker
sudo apt install docker.io
sudo systemctl start docker
sudo systemctl enable docker

# Install K3s
sudo curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.25.4+k3s1 sh -

# Check status K3s
sudo kubectl get nodes

# Print token for use on workers
sudo cat /var/lib/rancher/k3s/server/node-token
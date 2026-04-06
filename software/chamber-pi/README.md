

SETUP

sudo apt update
sudo apt install git -y

# Set your identity (Only needed for commiting from PI)
git config --global user.name "Your Name"
git config --global user.email "youremail@example.com"

ssh-keygen -t ed25519 -C "youremail@example.com"

eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519

cat ~/.ssh/id_ed25519.pub

copy to github ssh

# For GitHub
ssh -T git@github.com

# For GitLab
ssh -T git@gitlab.com


NEW INSTRUCTIONS

git clone git@github.com:username/repository-name.git

bash ORCA-Optical-Replication-Control-Apparatus/software/chamber-pi/scripts/setup.sh


sudo apt install -y python3-venv python3-pip build-essential

# Create the environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

pip install -r requirements.txt

update / start commands

call sudo raspi-config to update SPI under interfaces





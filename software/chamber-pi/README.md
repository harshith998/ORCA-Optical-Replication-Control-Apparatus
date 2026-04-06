

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

git clone git@github.com:username/repository-name.git
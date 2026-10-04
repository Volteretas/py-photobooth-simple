# Installation Guide

This guide will help you install and configure the Simple PhotoBooth application on your Raspberry Pi or other compatible systems.

## System Requirements

- Raspberry Pi 5 (8GB recommended) or compatible PC/laptop
- Raspberry Pi OS, Debian, Ubuntu, Fedora, or Arch Linux / CachyOS
- Python 3.9+
- Internet connection for initial setup

## Quick Installation

For automated installation, you can use the installation script:

```bash
chmod +x install.sh
./install.sh
```

The script will guide you through the installation process and ask which components you want to install.

## Manual Installation

### 1. Global Packages

Install system dependencies and development libraries for your distribution:

**Debian / Ubuntu / Raspberry Pi OS:**
```bash
sudo apt update
sudo apt install -y build-essential git python3-pip python3-venv python3-dev libgl1 libcups2-dev
```

**Fedora:**
```bash
sudo dnf install -y gcc make git python3-pip python3-devel mesa-libGL cups-devel
```

**Arch Linux / CachyOS:**
```bash
sudo pacman -S --needed base-devel git python-pip libglvnd libcups
```

Then create and activate the Python virtual environment:

```bash
# Create and activate a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
```

### 2. Kiosk Mode Configuration (Optional)

To run the photobooth in kiosk mode on Raspberry Pi:

```bash
# Hide mouse cursor and background panel
sudo sed -i 's/\[autostart\]/\[autostart]\r\background = wf-background/g /etc/wayfire/defaults.ini

# Hide taskbar
sudo sed -i '/^[^#].*wfrespawn wf-panel-pi/ s/^/# /' /etc/wayfire/defaults.ini

# Disable power warning
echo "avoid_warnings=1" | sudo tee -a /boot/firmware/config.txt && sudo apt remove lxplug-ptbatt -y

# Disable media mount dialog
sudo sed -i -e 's/autorun=1/autorun=0/g' /etc/xdg/pcmanfm/LXDE-pi/pcmanfm.conf
sudo sed -i -e 's/autorun=1/autorun=0/g' /etc/xdg/pcmanfm/default/pcmanfm.conf

# Reboot to apply changes
sudo reboot
```

### 3. Ingcool 7" Touchscreen Configuration (Optional)

If you're using the Ingcool 7" touchscreen:

```bash
sudo sh -c "echo '# Ingcool 7in touch screen' >> /boot/firmware/config.txt"
sudo sh -c "echo 'max_usb_current=1' >> /boot/firmware/config.txt"
sudo sh -c "echo 'hdmi_group=2' >> /boot/firmware/config.txt"
sudo sh -c "echo 'hdmi_mode=87' >> /boot/firmware/config.txt"
sudo sh -c "echo 'hdmi_cvt 1024 600 60 6 0 0 0' >> /boot/firmware/config.txt"
sudo sh -c "echo 'hdmi_drive=1' >> /boot/firmware/config.txt"
sudo sh -c "echo '' >> /boot/firmware/config.txt"

# Reboot to apply changes
sudo reboot
```

### 4. Raspberry Pi Camera Module V3 Setup (Recommended)

If you're using the Raspberry Pi Camera Module V3:

```bash
# Allocate more memory for camera
sudo sed -i 's/^dtoverlay=vc4-kms-v3d/dtoverlay=vc4-kms-v3d,cma-512/' /boot/firmware/config.txt

# Enable camera overlay
sudo sh -c "echo '# Camera module 3' >> /boot/firmware/config.txt"
sudo sh -c "echo 'dtoverlay=imx708,cam0' >> /boot/firmware/config.txt"
sudo sh -c "echo '' >> /boot/firmware/config.txt"

# Reboot to apply changes
sudo reboot

# Test camera after reboot
libcamera-still --list-camera
libcamera-still --autofocus-mode=auto -f -o test.jpg
```

### 5. DSLR Camera Support with GPhoto2 (Optional)

If you plan to use a DSLR camera:

**Debian / Ubuntu / Raspberry Pi OS:**
```bash
sudo apt install -y gphoto2 libgphoto2-dev
```

**Fedora:**
```bash
sudo dnf install -y gphoto2 libgphoto2-devel
```

**Arch Linux / CachyOS:**
```bash
sudo pacman -S --needed gphoto2 libgphoto2
```

Test camera connection:
```bash
gphoto2 --capture-image
```

### 6. Printer Setup with CUPS (Optional)

If you want to print photos directly from the photobooth:

**Debian / Ubuntu / Raspberry Pi OS:**
```bash
sudo apt install -y cups printer-driver-gutenprint
sudo usermod -a -G lpadmin $USER
```

**Fedora:**
```bash
sudo dnf install -y cups gutenprint-cups
```

**Arch Linux / CachyOS:**
```bash
sudo pacman -S --needed cups gutenprint
```

**Enable and start CUPS service:**
```bash
sudo systemctl enable --now cups
sudo cupsctl --remote-admin --remote-any
```

**Printer Configuration:**
1. Connect your printer via USB
2. Open a web browser and navigate to `https://<raspberry-ip>:631/admin/` (or `http://localhost:631/admin/`)
3. Click "Add Printer" (you'll need to enter your admin credentials)
4. Select your printer from the list
5. Assign a queue name (e.g., your printer model)
6. Update `PRINTER` in `config.ini` to match that exact name

### 7. LED Ring Configuration (Optional)

If you're using a WS2812 LED ring on Raspberry Pi:

```bash
# Enable SPI interface
sudo sed -i 's/^#dtparam=spi=on/dtparam=spi=on/' /boot/firmware/config.txt

# Install Python SPI library in the virtual environment
.venv/bin/pip install spidev

# Reboot to apply changes
sudo reboot
```

**LED Ring Wiring:**

Connect your WS2812 LED ring to the Raspberry Pi GPIO pins:

| WS2812 Pin | Raspberry Pi Pin           |
|------------|----------------------------|
| GND        | Pin 6, 9, 14, 20, or 25    |
| DIN        | Pin 19 (MOSI, GPIO 10)     |
| VCC        | Pin 2 or 4 (5V)            |

### 8. Autostart on Boot (Optional)

To automatically start the photobooth when the system boots:

```bash
# Create startup script in your home directory
cat << 'EOF' > "$HOME/photobooth.sh"
#!/bin/bash
cd "$HOME/py-photobooth-simple"
source .venv/bin/activate
exec python photoboothapp.py
EOF
chmod +x "$HOME/photobooth.sh"

# Create autostart configuration for Wayfire (if using Wayfire)
mkdir -p ~/.config
echo '[autostart]' >> ~/.config/wayfire.ini
echo "photobooth = $HOME/photobooth.sh" >> ~/.config/wayfire.ini
```

**Note:** Adjust the path in the script if you've installed the photobooth in a different directory.

## Running the Application

To start the photobooth manually:

```bash
cd /path/to/photobooth
.venv/bin/python photoboothapp.py
# or:
# source .venv/bin/activate && python photoboothapp.py
```

## Configuration

You can customize the photobooth behavior by editing `config.ini`:

- **Autorestart on failure:** Automatically restart if the app crashes
- **Full screen mode:** Run in fullscreen or windowed mode
- **Countdown duration:** Time before capturing the photo
- **Storage directories:** Where photos and collages are saved
- **Printer name:** CUPS printer name for printing
- **Calibration matrix:** For hybrid camera setups (DSLR + piCamera)
- **Overlays:** Custom overlay images for photos

## Troubleshooting

### Camera Not Detected

- **Pi Camera:** Check cable connection and ensure camera is enabled in `raspi-config`
- **DSLR:** Ensure gPhoto2 is properly installed and camera is compatible
- **Webcam:** Check USB connection and camera permissions

### Printer Not Working

- Verify printer is connected via USB
- Check CUPS web interface (`https://<raspberry-ip>:631/`)
- Ensure printer is set as default and named correctly in `config.ini`
- Check printer driver installation

### LED Ring Not Lighting

- Verify SPI is enabled in `/boot/firmware/config.txt`
- Check wiring connections
- Ensure LED ring is powered with 5V
- Test with a simple SPI test script

### Screen Resolution Issues

- For Ingcool screen, verify HDMI configuration in `/boot/firmware/config.txt`
- For other screens, adjust `hdmi_mode` and `hdmi_cvt` settings accordingly
- Check screen documentation for recommended settings

## USB Photo Dump

The photobooth automatically detects USB drives and copies all photos:

- Insert a FAT32-formatted USB drive
- The application will automatically copy photos to the drive
- Wait for the copy process to complete (screen will show progress)
- Safely remove the USB drive when prompted

**Important:** USB drives must be formatted as FAT32 for compatibility.

## Support and Updates

For updates, bug reports, or feature requests, please visit the project repository.

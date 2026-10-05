#!/bin/bash
# Builds a newer BlueZ into /usr/local WITHOUT touching the system's bluez package, Wi-Fi, kernel or firmware.
# The running Bluetooth service keeps using /usr/lib/bluetooth/bluetoothd until a systemd drop-in switches it.
set -u
LOG=/home/pi/Documents/backups/bluez-build.log
exec >>"$LOG" 2>&1
echo "=== $(date) start"
sudo -n apt-get install -y --no-upgrade build-essential libdbus-1-dev libglib2.0-dev libudev-dev libical-dev libreadline-dev || { echo "APT FAILED"; exit 1; }
mkdir -p /home/pi/build && cd /home/pi/build
for V in 5.79 5.66; do
  echo "--- trying bluez-$V"
  rm -rf bluez-$V
  curl -fsSLO https://www.kernel.org/pub/linux/bluetooth/bluez-$V.tar.xz || { echo "download failed for $V"; continue; }
  tar xf bluez-$V.tar.xz && cd bluez-$V || { cd /home/pi/build; continue; }
  if ./configure --prefix=/usr/local --sysconfdir=/etc --localstatedir=/var \
       --disable-manpages --disable-obex --disable-sap --disable-nfc --disable-mesh --disable-midi --disable-cups \
       --with-systemdsystemunitdir=/usr/local/lib/systemd/system --with-systemduserunitdir=/usr/local/lib/systemd/user \
       --with-dbusconfdir=/usr/local/share --with-udevdir=/usr/local/lib/udev \
     && nice -n 19 make -j3 \
     && sudo -n make install; then
    echo "BUILD OK $V"
    /usr/local/libexec/bluetooth/bluetoothd -v
    echo "$V" > /home/pi/build/BLUEZ_VERSION
    exit 0
  fi
  echo "build failed for $V"
  cd /home/pi/build
done
echo "ALL BUILDS FAILED"
exit 1

"""
Scoreboard link: Arduino state (UART) -> Bluetooth LE -> phone.

The Arduino broadcasts its full state once per change and at least once a second on Serial3 (38400 8N1):

    $S,<home>,<away>,<sportMode>,<scoreTo>,<piOn>,<homeColor>,<awayColor>,<d0>,<d1>,<d2>,<d3>,<event>,<eventSeq>*<XOR>

This service keeps the latest valid line and publishes it as a BLE GATT characteristic (read + notify) for the
Web Bluetooth page in web/. It is separate from the vision engine on purpose: nothing here can affect scoring,
and the Arduino never waits for it.

The page can also change two settings (sport mode, volleyball game-to) by writing to the command characteristic.
Only whitelisted commands are forwarded to the Arduino, as checksummed lines on the same UART:

    $C,MODE,<0|1>*<XOR>        $C,TO,<15|21|25>*<XOR>

BLE uses BlueZ's D-Bus API (BlueZ 5.50 on Raspbian Buster) through python3-dbus and python3-gi, so it needs no
pip packages. Bluetooth is started ~20 s after boot by scoreboard-bt.timer; until bluetoothd appears (and after
it restarts) the service keeps reading the UART and retries the BLE registration every few seconds.

Usage:
    python3 scoreboard_link.py                     # UART + BLE (the systemd service)
    python3 scoreboard_link.py --stdin --no-ble    # parse lines from stdin and print packets (desktop testing)
Environment:
    SCOREBOARD_LINK_PORT   serial device (default /dev/ttyAMA1 = PL011 UART2 on GPIO 0/1, dtoverlay=uart2)
    SCOREBOARD_BLE_SECURE  1 = require an encrypted (paired) link to write commands
"""

import argparse
import os
import re
import struct
import sys
import threading
import time

LINK_PORT = os.environ.get('SCOREBOARD_LINK_PORT', '/dev/ttyAMA1')
LINK_BAUD = 38400

BLE_NAME = 'Scoreboard'                                   # advertised name; the page filters on it
SERVICE_UUID = 'b3710001-1a78-4239-800f-cf4fa9544bbe'
STATE_CHAR_UUID = 'b3710002-1a78-4239-800f-cf4fa9544bbe'  # read + notify, PACKET_FORMAT below
COMMAND_CHAR_UUID = 'b3710003-1a78-4239-800f-cf4fa9544bbe'  # write: ASCII command, COMMAND_RE below
SECURE_WRITES = os.environ.get('SCOREBOARD_BLE_SECURE', '0') == '1'

# The only commands the phone may send (sport mode, volleyball game-to). Scores are not remote-controllable yet.
COMMAND_RE = re.compile(r'^(MODE,[01]|TO,(15|21|25))$')

FRESH_SECONDS = 3.0          # Arduino data older than this is flagged stale (it sends at least once a second)
KEEPALIVE_SECONDS = 2.0      # notify at least this often so the phone can tell a dead link from a quiet game
BLE_RETRY_SECONDS = 5

COLOR_WHITE = 256
COLOR_RAINBOW = 257

# Event codes from the Arduino, in wire order (index = byte in the BLE packet; 0 = unknown)
EVENTS = ['', 'BOOT', 'HU', 'HD', 'AU', 'AD', 'HP', 'AP', 'HC', 'AC', 'RS', 'HW', 'AW', 'MD', 'GT', 'SM']

# BLE state packet, 17 bytes (fits the default ATT MTU of 23 without a long read). Little endian.
#   B  version (1)
#   B  flags: bit0 Pi heartbeat accepted by the Arduino (gestures live), bit1 Arduino data fresh
#   B  home score     B  away score     (clamped to 0-255)
#   B  sport mode (0 volleyball, 1 tennis)
#   B  game-to score
#   H  home color     H  away color     (0-255 FastLED hue, 256 white, 257 rainbow)
#   4b digits as drawn: home tens, home ones, away tens, away ones (digitTable index, -1 blank)
#   B  event code (EVENTS index)
#   B  event sequence (wraps at 256)
#   B  age of the Arduino data in 0.1 s (capped at 255)
PACKET_FORMAT = '<BBBBBBHH4bBBB'
PACKET_VERSION = 1
FLAG_PI_ON = 0x01
FLAG_FRESH = 0x02


def log(msg):
    print(time.strftime('%H:%M:%S ') + msg, flush=True)


def parse_state_line(line):
    """Parse one '$S,...*CS' line. Returns a dict, or None if it is malformed or the checksum fails."""
    line = line.strip()
    if not line.startswith('$') or '*' not in line:
        return None
    body, _, cs = line[1:].rpartition('*')
    try:
        expected = int(cs, 16)
    except ValueError:
        return None
    checksum = 0
    for ch in body:
        checksum ^= ord(ch)
    if checksum != expected:
        return None
    f = body.split(',')
    if len(f) != 14 or f[0] != 'S':
        return None
    try:
        n = [int(x) for x in f[1:12]]
        seq = int(f[13])
    except ValueError:
        return None
    return {
        'home': n[0], 'away': n[1], 'mode': n[2], 'score_to': n[3], 'pi_on': bool(n[4]),
        'home_color': n[5], 'away_color': n[6], 'digits': n[7:11],
        'event': f[12], 'event_seq': seq & 0xFF,
    }


def build_command(text):
    """'TO,25' -> '$C,TO,25*XX\r\n' for the Arduino, or None if the command is not allowed."""
    text = text.strip()
    if not COMMAND_RE.match(text):
        return None
    body = 'C,' + text
    checksum = 0
    for ch in body:
        checksum ^= ord(ch)
    return '$%s*%02X' % (body, checksum) + chr(13) + chr(10)


def pack_state(state, age_s):
    """Pack a parsed state (or None = nothing received yet) into the BLE packet."""
    if state is None:
        return struct.pack(PACKET_FORMAT, PACKET_VERSION, 0, 0, 0, 0, 21,
                           COLOR_WHITE, COLOR_WHITE, -1, 0, -1, 0, 0, 0, 255)
    flags = (FLAG_PI_ON if state['pi_on'] else 0) | (FLAG_FRESH if age_s < FRESH_SECONDS else 0)

    def u8(v):
        return max(0, min(255, v))

    def digit(v):
        return v if 0 <= v <= 15 else -1

    def color(v):
        return v if 0 <= v <= COLOR_RAINBOW else COLOR_WHITE

    event = EVENTS.index(state['event']) if state['event'] in EVENTS else 0
    return struct.pack(PACKET_FORMAT, PACKET_VERSION, flags, u8(state['home']), u8(state['away']),
                       u8(state['mode']), u8(state['score_to']),
                       color(state['home_color']), color(state['away_color']),
                       *[digit(d) for d in state['digits']],
                       event, state['event_seq'], u8(int(age_s * 10)))


class LinkState:
    """Latest Arduino state, shared between the reader thread and the main loop."""

    def __init__(self):
        self._lock = threading.Lock()
        self.state = None
        self.received_at = None
        self.lines_ok = 0
        self.lines_bad = 0
        self.serial = None   # the open UART, for commands to the Arduino

    def send_command(self, text):
        """Forward a whitelisted command to the Arduino. Returns an error string, or None on success."""
        line = build_command(text)
        if line is None:
            return 'command not allowed: %r' % text
        with self._lock:
            ser = self.serial
        if ser is None:
            return 'UART not open'
        try:
            ser.write(line.encode('ascii'))
        except Exception as e:
            return 'UART write failed: %s' % e
        log('command to Arduino: %s' % line.strip())
        return None

    def update(self, state):
        with self._lock:
            self.state = state
            self.received_at = time.monotonic()
            self.lines_ok += 1

    def bad_line(self):
        with self._lock:
            self.lines_bad += 1

    def packet(self):
        with self._lock:
            age = 999.0 if self.received_at is None else time.monotonic() - self.received_at
            return pack_state(self.state, age), self.state


def describe(state):
    if state is None:
        return 'no data'
    return ('home %d  away %d  mode %d  to %d  pi %s  colors %d/%d  digits %s  event %s#%d' % (
        state['home'], state['away'], state['mode'], state['score_to'], 'on' if state['pi_on'] else 'off',
        state['home_color'], state['away_color'], state['digits'], state['event'], state['event_seq']))


def serial_reader(link, port):
    """Read state lines forever; re-open the port after any error."""
    import serial
    while True:
        try:
            with serial.Serial(port, LINK_BAUD, timeout=1.0, write_timeout=0.5) as ser:
                log('UART open: %s @ %d' % (port, LINK_BAUD))
                link.serial = ser
                while True:
                    raw = ser.readline()
                    if not raw.strip():
                        continue
                    state = parse_state_line(raw.decode('ascii', errors='replace'))
                    if state is None:
                        link.bad_line()   # boot noise (HAT EEPROM probe on GPIO 0/1), partial lines
                    else:
                        link.update(state)
        except Exception as e:  # unplugged / not configured yet: keep trying, never exit
            link.serial = None
            log('UART %s: %s (retrying in 5 s)' % (port, e))
            time.sleep(5)


def stdin_reader(link):
    for raw in sys.stdin.buffer:   # bytes, like the UART: boot noise must not kill the reader
        if not raw.strip():
            continue
        state = parse_state_line(raw.decode('ascii', errors='replace'))
        if state is None:
            link.bad_line()
        else:
            link.update(state)


# ---------------------------------------------------------------------------------------------------------
# BLE peripheral (BlueZ D-Bus). Imported lazily so the parser and packer run anywhere.
# ---------------------------------------------------------------------------------------------------------

def run_ble(link):
    import dbus
    import dbus.exceptions
    import dbus.mainloop.glib
    import dbus.service
    from gi.repository import GLib

    BLUEZ = 'org.bluez'
    OM_IFACE = 'org.freedesktop.DBus.ObjectManager'
    PROP_IFACE = 'org.freedesktop.DBus.Properties'
    ADAPTER_IFACE = 'org.bluez.Adapter1'
    DEVICE_IFACE = 'org.bluez.Device1'
    GATT_MANAGER_IFACE = 'org.bluez.GattManager1'
    GATT_SERVICE_IFACE = 'org.bluez.GattService1'
    GATT_CHRC_IFACE = 'org.bluez.GattCharacteristic1'
    ADV_MANAGER_IFACE = 'org.bluez.LEAdvertisingManager1'
    ADV_IFACE = 'org.bluez.LEAdvertisement1'
    APP_PATH = '/com/scoreboard/link'

    class InvalidArgs(dbus.exceptions.DBusException):
        _dbus_error_name = 'org.freedesktop.DBus.Error.InvalidArgs'

    class Failed(dbus.exceptions.DBusException):
        _dbus_error_name = 'org.bluez.Error.Failed'

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    class Application(dbus.service.Object):
        def __init__(self):
            self.services = []
            dbus.service.Object.__init__(self, bus, APP_PATH)

        @dbus.service.method(OM_IFACE, out_signature='a{oa{sa{sv}}}')
        def GetManagedObjects(self):
            objects = {}
            for service in self.services:
                objects[service.path] = service.properties()
                for chrc in service.characteristics:
                    objects[chrc.path] = chrc.properties()
            return objects

    class Service(dbus.service.Object):
        def __init__(self, index, uuid):
            self.path = '%s/service%d' % (APP_PATH, index)
            self.uuid = uuid
            self.characteristics = []
            dbus.service.Object.__init__(self, bus, self.path)

        def properties(self):
            return {GATT_SERVICE_IFACE: {
                'UUID': self.uuid, 'Primary': True,
                'Characteristics': dbus.Array([c.path for c in self.characteristics], signature='o')}}

        @dbus.service.method(PROP_IFACE, in_signature='s', out_signature='a{sv}')
        def GetAll(self, interface):
            if interface != GATT_SERVICE_IFACE:
                raise InvalidArgs()
            return self.properties()[GATT_SERVICE_IFACE]

    class StateCharacteristic(dbus.service.Object):
        def __init__(self, service):
            self.path = service.path + '/char0'
            self.service = service
            self.value = b''
            self.notifying = False
            dbus.service.Object.__init__(self, bus, self.path)

        def properties(self):
            return {GATT_CHRC_IFACE: {
                'Service': self.service.path, 'UUID': STATE_CHAR_UUID,
                'Flags': dbus.Array(['read', 'notify'], signature='s')}}

        @dbus.service.method(PROP_IFACE, in_signature='s', out_signature='a{sv}')
        def GetAll(self, interface):
            if interface != GATT_CHRC_IFACE:
                raise InvalidArgs()
            return self.properties()[GATT_CHRC_IFACE]

        @dbus.service.method(GATT_CHRC_IFACE, in_signature='a{sv}', out_signature='ay')
        def ReadValue(self, options):
            return dbus.Array(link.packet()[0], signature='y')

        @dbus.service.method(GATT_CHRC_IFACE)
        def StartNotify(self):
            if not self.notifying:
                self.notifying = True
                log('phone subscribed')
                self.push(link.packet()[0])

        @dbus.service.method(GATT_CHRC_IFACE)
        def StopNotify(self):
            if self.notifying:
                self.notifying = False
                log('phone unsubscribed')

        @dbus.service.signal(PROP_IFACE, signature='sa{sv}as')
        def PropertiesChanged(self, interface, changed, invalidated):
            pass

        def push(self, value):
            self.value = value
            if self.notifying:
                self.PropertiesChanged(GATT_CHRC_IFACE, {'Value': dbus.Array(value, signature='y')}, [])

    class CommandCharacteristic(dbus.service.Object):
        def __init__(self, service):
            self.path = service.path + '/char1'
            self.service = service
            dbus.service.Object.__init__(self, bus, self.path)

        def properties(self):
            flags = ['encrypt-write'] if SECURE_WRITES else ['write']
            return {GATT_CHRC_IFACE: {
                'Service': self.service.path, 'UUID': COMMAND_CHAR_UUID,
                'Flags': dbus.Array(flags, signature='s')}}

        @dbus.service.method(PROP_IFACE, in_signature='s', out_signature='a{sv}')
        def GetAll(self, interface):
            if interface != GATT_CHRC_IFACE:
                raise InvalidArgs()
            return self.properties()[GATT_CHRC_IFACE]

        @dbus.service.method(GATT_CHRC_IFACE, in_signature='aya{sv}')
        def WriteValue(self, value, options):
            text = bytes(value).decode('ascii', errors='replace')
            error = link.send_command(text)
            if error:
                log('phone command rejected: %s' % error)
                raise Failed(error)

    class Advertisement(dbus.service.Object):
        def __init__(self):
            self.path = APP_PATH + '/advertisement0'
            dbus.service.Object.__init__(self, bus, self.path)

        def properties(self):
            # Name only: a 128-bit service UUID plus the name would not fit in the 31-byte legacy
            # advertisement. The page filters on the name and lists the service as optionalServices.
            return {ADV_IFACE: {'Type': 'peripheral', 'LocalName': dbus.String(BLE_NAME)}}

        @dbus.service.method(PROP_IFACE, in_signature='s', out_signature='a{sv}')
        def GetAll(self, interface):
            if interface != ADV_IFACE:
                raise InvalidArgs()
            return self.properties()[ADV_IFACE]

        @dbus.service.method(ADV_IFACE)
        def Release(self):
            log('advertisement released by BlueZ')
            ble['adv_ok'] = False

    app = Application()
    service = Service(0, SERVICE_UUID)
    chrc = StateCharacteristic(service)
    service.characteristics.append(chrc)
    service.characteristics.append(CommandCharacteristic(service))
    app.services.append(service)
    adv = Advertisement()

    ble = {'adapter': None, 'app_ok': False, 'adv_ok': False, 'pending': False}

    def find_adapter():
        om = dbus.Interface(bus.get_object(BLUEZ, '/'), OM_IFACE)
        for path, ifaces in om.GetManagedObjects().items():
            if GATT_MANAGER_IFACE in ifaces and ADV_MANAGER_IFACE in ifaces:
                return path
        return None

    def register_adv():
        ble['pending'] = True
        mgr = dbus.Interface(bus.get_object(BLUEZ, ble['adapter']), ADV_MANAGER_IFACE)

        def ok():
            ble['adv_ok'], ble['pending'] = True, False
            log('advertising as "%s"' % BLE_NAME)

        def fail(e):
            ble['pending'] = False
            log('advertisement registration failed: %s' % e)
        mgr.RegisterAdvertisement(adv.path, {}, reply_handler=ok, error_handler=fail)

    def readvertise():
        """BlueZ 5.50 can stop advertising after a central disconnects: register the advertisement again."""
        if not ble['adapter'] or ble['pending']:
            return
        ble['adv_ok'] = False
        ble['pending'] = True
        mgr = dbus.Interface(bus.get_object(BLUEZ, ble['adapter']), ADV_MANAGER_IFACE)

        def done(*_):
            ble['pending'] = False
            register_adv()
        mgr.UnregisterAdvertisement(adv.path, reply_handler=done, error_handler=done)

    def ensure_registered():
        if ble['pending'] or (ble['app_ok'] and ble['adv_ok']):
            return True
        try:
            if ble['adapter'] is None:
                ble['adapter'] = find_adapter()
                if ble['adapter'] is None:
                    return True   # bluetoothd not up yet (scoreboard-bt.timer starts it ~20 s after boot)
                props = dbus.Interface(bus.get_object(BLUEZ, ble['adapter']), PROP_IFACE)
                props.Set(ADAPTER_IFACE, 'Powered', dbus.Boolean(True))
                props.Set(ADAPTER_IFACE, 'Alias', dbus.String(BLE_NAME))
                log('adapter %s' % ble['adapter'])
            if not ble['app_ok']:
                ble['pending'] = True
                mgr = dbus.Interface(bus.get_object(BLUEZ, ble['adapter']), GATT_MANAGER_IFACE)

                def ok():
                    ble['app_ok'], ble['pending'] = True, False
                    log('GATT service registered')
                    register_adv()

                def fail(e):
                    ble['pending'] = False
                    log('GATT registration failed: %s' % e)
                mgr.RegisterApplication(APP_PATH, {}, reply_handler=ok, error_handler=fail)
            elif not ble['adv_ok']:
                register_adv()
        except dbus.exceptions.DBusException as e:
            ble.update(adapter=None, pending=False)
            log('BlueZ not ready: %s' % e.get_dbus_name())
        return True

    def on_owner_changed(name, old, new):
        if name == BLUEZ:
            log('bluetoothd %s' % ('started' if new else 'stopped'))
            ble.update(adapter=None, app_ok=False, adv_ok=False, pending=False)
            if new:
                GLib.timeout_add_seconds(1, lambda: ensure_registered() and False)

    def on_props_changed(interface, changed, invalidated, path=None):
        if interface == DEVICE_IFACE and 'Connected' in changed:
            if changed['Connected']:
                log('phone connected (%s)' % path)
            else:
                log('phone disconnected (%s)' % path)
                readvertise()

    bus.add_signal_receiver(on_owner_changed, signal_name='NameOwnerChanged',
                            dbus_interface='org.freedesktop.DBus', arg0=BLUEZ)
    bus.add_signal_receiver(on_props_changed, signal_name='PropertiesChanged', dbus_interface=PROP_IFACE,
                            bus_name=BLUEZ, path_keyword='path')

    last = {'packet': None, 'sent_at': 0.0, 'state': None}

    def tick():
        packet, state = link.packet()
        now = time.monotonic()
        # Compare without the age byte, which changes every tick
        if packet[:-1] != (last['packet'] or b'')[:-1] or now - last['sent_at'] >= KEEPALIVE_SECONDS:
            chrc.push(packet)
            last.update(packet=packet, sent_at=now)
        if state is not None and (last['state'] is None or
                                  {k: v for k, v in state.items()} != last['state']):
            log(describe(state))
            last['state'] = dict(state)
        return True

    ensure_registered()
    GLib.timeout_add_seconds(BLE_RETRY_SECONDS, ensure_registered)
    GLib.timeout_add(200, tick)
    GLib.MainLoop().run()


def run_console(link):
    """No BLE: print each new packet (desktop testing)."""
    last = None
    while True:
        packet, state = link.packet()
        if packet[:-1] != (last or b'')[:-1]:
            print(describe(state), '|', packet.hex(), flush=True)
            last = packet
        time.sleep(0.2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--stdin', action='store_true', help='read state lines from stdin instead of the UART')
    ap.add_argument('--no-ble', action='store_true', help='print packets instead of serving them over BLE')
    ap.add_argument('--port', default=LINK_PORT)
    args = ap.parse_args()

    link = LinkState()
    if args.stdin:
        reader = threading.Thread(target=stdin_reader, args=(link,), daemon=True)
    else:
        reader = threading.Thread(target=serial_reader, args=(link, args.port), daemon=True)
    reader.start()

    log('scoreboard link starting (%s, %s)' % ('stdin' if args.stdin else args.port,
                                               'console' if args.no_ble else 'BLE'))
    if args.no_ble:
        if args.stdin:
            reader.join()
            time.sleep(0.3)
            packet, state = link.packet()
            print(describe(state), '|', packet.hex(), '| ok %d bad %d' % (link.lines_ok, link.lines_bad))
            return
        run_console(link)
    else:
        run_ble(link)


if __name__ == '__main__':
    main()

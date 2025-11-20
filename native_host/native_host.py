# native_host.py — Python native messaging host (no TCP). Demo: on 'pageReady' sends setValue.
import sys, struct, json, threading

def send_message(msg):
    raw = json.dumps(msg).encode('utf-8')
    sys.stdout.buffer.write(struct.pack('I', len(raw)))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()

def read_message():
    raw_len = sys.stdin.buffer.read(4)
    if len(raw_len) == 0:
        return None
    msg_len = struct.unpack('I', raw_len)[0]
    data = sys.stdin.buffer.read(msg_len)
    return json.loads(data.decode('utf-8'))

def main():
    while True:
        msg = read_message()
        if msg is None:
            break
        # When page is ready, send command to set Email=1234 (demo)
        if msg.get('event') == 'pageReady':
            send_message({
                "action": "setValue",
                "params": {"selector": "input[placeholder='Email']", "value": "1234"}
            })

if __name__ == "__main__":
    main()
